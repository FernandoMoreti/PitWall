"""Gateway MQTT ⇄ RabbitMQ.

IoT → Web: assina f1/+/telemetry e f1/+/event no Mosquitto, valida o envelope e
republica no exchange topic "f1" com routing key telemetry.<equipe>.car.<id>.

Web → IoT: consome q.commands (command.<id>) e publica em f1/<id>/cmd.

O paho roda na própria thread; tudo o que fala com o pika fica na thread
principal (pika não é thread-safe), ligado por uma queue.Queue.
"""
from __future__ import annotations

import json
import logging
import queue
import time

from pitwall_common import amqp, envelope, topics
from pitwall_common.config import env, env_int
from pitwall_common.mqtt import Broker

logging.basicConfig(level=logging.INFO, format="%(asctime)s [gateway] %(message)s")
log = logging.getLogger("gateway")

inbox: "queue.Queue[tuple[str, bytes]]" = queue.Queue(maxsize=20000)
stats = {"mqtt_in": 0, "amqp_out": 0, "invalid": 0, "commands": 0}


def on_mqtt(topic: str, raw: bytes) -> None:
    try:
        inbox.put_nowait((topic, raw))
    except queue.Full:
        log.warning("fila interna cheia, descartando %s", topic)


def route(topic: str, msg: dict) -> str | None:
    parts = topic.split("/")
    if topic == topics.MQTT_SIM_STATUS:
        return "event.sim_status.sim"
    if len(parts) != 3:
        return None
    car, kind = parts[1], parts[2]
    if msg["device"] != car:
        raise ValueError("device do envelope não confere com o tópico")
    team = str(msg["payload"].get("team", "unknown"))
    if kind == "telemetry":
        return topics.rk_telemetry(team, car)
    if kind == "event":
        return topics.rk_event(str(msg["payload"].get("kind", "generic")), car)
    return None


def main() -> None:
    mqtt = Broker(env("MQTT_HOST", "mosquitto"), env_int("MQTT_PORT", 1883),
                  env("MQTT_GATEWAY_USER", "gateway"), env("MQTT_GATEWAY_PASSWORD"),
                  client_id="pitwall-gateway", subscriptions=topics.MQTT_SUB_FROM_DEVICES, on_message=on_mqtt)
    mqtt.connect()

    while True:
        conn = amqp.connect("RABBITMQ_GATEWAY_USER", "RABBITMQ_GATEWAY_PASSWORD")
        ch = conn.channel()
        ch.confirm_delivery()
        ch.basic_qos(prefetch_count=50)

        def on_command(chan, method, props, body):
            try:
                msg = envelope.loads(body)
                car = msg["device"]
                mqtt.publish(topics.MQTT_CMD.format(car=car), body, qos=1)
                stats["commands"] += 1
                log.info("Comando -> f1/%s/cmd %s", car, msg["payload"])
                chan.basic_ack(method.delivery_tag)
            except Exception as exc:  # noqa: BLE001
                log.error("Comando inválido, enviado à DLQ: %s", exc)
                chan.basic_nack(method.delivery_tag, requeue=False)

        ch.basic_consume(topics.Q_COMMANDS, on_command)
        last_log = time.time()
        try:
            while True:
                conn.process_data_events(time_limit=0.05)
                drained = 0
                while drained < 2000:
                    try:
                        topic, raw = inbox.get_nowait()
                    except queue.Empty:
                        break
                    drained += 1
                    stats["mqtt_in"] += 1
                    try:
                        if topic == topics.MQTT_SIM_STATUS:
                            msg = envelope.make("event", "sim", {"kind": "sim_status", **json.loads(raw)}, "gateway")
                        else:
                            msg = envelope.loads(raw)
                        rk = route(topic, msg)
                        if not rk:
                            continue
                        ch.basic_publish(topics.EXCHANGE, rk, envelope.dumps(msg), amqp.json_props())
                        stats["amqp_out"] += 1
                    except (ValueError, json.JSONDecodeError) as exc:
                        stats["invalid"] += 1
                        log.warning("Mensagem inválida em %s: %s", topic, exc)
                amqp.beat()
                if time.time() - last_log > 30:
                    log.info("stats %s", stats)
                    last_log = time.time()
        except Exception as exc:  # noqa: BLE001
            log.error("Conexão AMQP perdida (%s), reconectando...", exc)
            try:
                conn.close()
            except Exception:  # noqa: BLE001
                pass
            time.sleep(2)


if __name__ == "__main__":
    main()
