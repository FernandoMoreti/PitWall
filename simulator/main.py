"""Simulador de corrida PITWALL — substitui o Arduino/ESP32 do 1º bimestre.

Publica a telemetria de cada carro no Mosquitto (f1/<car>/telemetry, 10 Hz),
eventos de corrida (f1/<car>/event) e escuta comandos (f1/<car>/cmd).
"""
from __future__ import annotations

import json
import logging
import queue
import random
import signal
import time

from pitwall_common import amqp, envelope, topics
from pitwall_common.config import env, env_float, env_int
from pitwall_common.mqtt import Broker
from pitwall_common.track import build

from car import Car

logging.basicConfig(level=logging.INFO, format="%(asctime)s [sim] %(message)s")
log = logging.getLogger("sim")

GRID = [
    # id, nº, piloto, equipe, carro da equipe, habilidade, faixa lateral, composto
    ("PW16", 16, "L. Moreau", "Pitwall Racing", True, 0.996, -2.0, "SOFT"),
    ("PW55", 55, "K. Sato", "Pitwall Racing", True, 0.993, 2.0, "MEDIUM"),
    ("AU01", 1, "D. Varga", "Aurora GP", False, 0.997, 0.0, "MEDIUM"),
    ("AU44", 44, "M. Okafor", "Aurora GP", False, 0.991, -3.0, "SOFT"),
    ("VX07", 7, "R. Lindqvist", "Vortex Motorsport", False, 0.989, 3.0, "HARD"),
    ("VX23", 23, "T. Ferraz", "Vortex Motorsport", False, 0.987, -1.0, "MEDIUM"),
]


class Race:
    def __init__(self) -> None:
        self.track = build()
        self.rng = random.Random(env_int("SIM_SEED", 42))
        mult = env_float("SIM_CONSUMABLE_MULT", 3.0)
        self.cars: list[Car] = []
        for i, (cid, num, drv, team, mine, skill, lane, comp) in enumerate(GRID):
            car = Car(car_id=cid, number=num, driver=drv, team=team, team_car=mine, skill=skill,
                      lane=lane, compound=comp, s=self.track.length - 12 - i * 18,
                      consumable_mult=mult, rng=random.Random(self.rng.random()))
            car.lat = lane
            car._pu_wear = self.rng.uniform(0.05, 0.22)
            self.cars.append(car)
        self.by_id = {c.car_id: c for c in self.cars}
        self.commands: "queue.Queue[tuple[str, dict]]" = queue.Queue()
        self.t = 0.0

    # comandos chegam pela thread do paho -> fila -> loop principal
    def on_mqtt(self, topic: str, raw: bytes) -> None:
        parts = topic.split("/")
        if len(parts) == 3 and parts[2] == "cmd":
            try:
                self.commands.put((parts[1], envelope.loads(raw)))
            except ValueError as exc:
                log.warning("Comando inválido em %s: %s", topic, exc)

    def order(self) -> None:
        ranked = sorted(self.cars, key=lambda c: (c.status != "DNF", c.total), reverse=True)
        leader = ranked[0]
        for pos, car in enumerate(ranked, start=1):
            car.position = pos
            car.gap_leader = (leader.total - car.total) / 62.0 if pos > 1 else 0.0
            car.interval = (ranked[pos - 2].total - car.total) / 62.0 if pos > 1 else 0.0

    def rival_strategy(self, car: Car) -> None:
        if car.team_car or car.box_compound or car.status != "RUNNING":
            return
        avg = sum(car.wear.values()) / 4
        if avg > 0.72 or car.fuel < 9:
            car.box_compound = "HARD" if car.compound != "HARD" else "MEDIUM"
        if car.engine_temp > 117 and not car.cooling:
            car.engine_mode = "CONSERVE"
        elif car.engine_temp < 105 and car.engine_mode == "CONSERVE":
            car.engine_mode = "STANDARD"


def main() -> None:
    race = Race()
    hz = env_int("SIM_HZ", 10)
    dt = 1.0 / hz
    time_scale = env_float("SIM_TIME_SCALE", 1.0)

    broker = Broker(env("MQTT_HOST", "mosquitto"), env_int("MQTT_PORT", 1883),
                    env("MQTT_SIM_USER", "sim"), env("MQTT_SIM_PASSWORD"), client_id="pitwall-simulator",
                    subscriptions=[topics.MQTT_CMD.format(car="+")], on_message=race.on_mqtt,
                    will=(topics.MQTT_SIM_STATUS, json.dumps({"online": False})))
    broker.connect()
    broker.publish(topics.MQTT_SIM_STATUS, {"online": True, "cars": len(race.cars), "hz": hz}, qos=1, retain=True)
    log.info("Pista %.0f m, %d carros, %d Hz", race.track.length, len(race.cars), hz)

    running = True

    def stop(*_):
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    next_tick = time.monotonic()
    while running:
        # 1. comandos recebidos
        while not race.commands.empty():
            cid, msg = race.commands.get()
            car = race.by_id.get(cid)
            if not car:
                continue
            p = msg["payload"]
            result = car.apply_command(str(p.get("action")), p.get("value"), msg.get("source", "web"))
            log.info("Comando %s -> %s=%s (%s)", cid, p.get("action"), p.get("value"), result)
            broker.publish(topics.MQTT_EVENT.format(car=cid), envelope.make(
                "event", cid, {"kind": "command_ack", "action": p.get("action"), "value": p.get("value"),
                               "result": result, "command_id": msg["id"], "team": car.team}, "simulator"))

        # 2. física
        sim_dt = dt * time_scale
        race.t += sim_dt
        race.order()
        for car in race.cars:
            race.rival_strategy(car)
            car.step(sim_dt, race.t, race.track, car.interval)

        # 3. publicação
        for car in race.cars:
            broker.publish(topics.MQTT_TELEMETRY.format(car=car.car_id),
                           envelope.make("telemetry", car.car_id, car.telemetry(race.track), "simulator"))
            for kind, data in car.events:
                data.update({"kind": kind, "team": car.team})
                broker.publish(topics.MQTT_EVENT.format(car=car.car_id),
                               envelope.make("event", car.car_id, data, "simulator"), qos=1)
                log.info("Evento %s %s %s", car.car_id, kind, data)
            car.events.clear()

        if int(race.t * hz) % hz == 0:
            amqp.beat()
        next_tick += dt
        delay = next_tick - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        else:
            next_tick = time.monotonic()

    broker.publish(topics.MQTT_SIM_STATUS, {"online": False}, qos=1, retain=True)
    time.sleep(0.2)
    broker.disconnect()


if __name__ == "__main__":
    main()
