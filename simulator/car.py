"""Modelo físico simplificado de um carro de F1 (o "dispositivo" simulado).

Sensores publicados: velocidade, RPM, marcha, acelerador/freio, temperaturas do
motor e do óleo, pressão do óleo, vibração da PU, combustível, ERS e, por roda,
temperatura/desgaste/pressão do pneu e temperatura do freio.

Atuadores: modo do motor, modo ERS, resfriamento (regra automática), DRS,
chamada para o box. O estado de cada atuador aparece nas leituras seguintes.

Estado oculto (rótulo de verdade, NUNCA publicado): pu_wear e as falhas ativas.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

from pitwall_common.track import PIT_OFFSET, Track, V_MAX

WHEELS = ("FL", "FR", "RL", "RR")

COMPOUNDS = {
    "SOFT": {"life_laps": 18, "grip": 1.012, "opt": (92, 108)},
    "MEDIUM": {"life_laps": 28, "grip": 1.0, "opt": (88, 104)},
    "HARD": {"life_laps": 40, "grip": 0.99, "opt": (84, 100)},
}

ENGINE_MODES = {
    #            fator vel. combustível  °C   desgaste pneu  rpm   desgaste PU
    "PUSH":     {"speed": 1.012, "fuel": 1.12, "temp": 13, "wear": 1.25, "rpm": 350, "pu": 2.0},
    "STANDARD": {"speed": 1.000, "fuel": 1.00, "temp": 0, "wear": 1.00, "rpm": 0, "pu": 1.0},
    "CONSERVE": {"speed": 0.982, "fuel": 0.86, "temp": -7, "wear": 0.80, "rpm": -450, "pu": 0.6},
}

ERS_MODES = {
    "HARVEST": {"deploy": 0.0, "harvest": 1.6, "temp": -1},
    "BALANCED": {"deploy": 0.010, "harvest": 1.0, "temp": 0},
    "OVERTAKE": {"deploy": 0.030, "harvest": 0.8, "temp": 3},
}

GEAR_KPH = [0, 85, 125, 160, 195, 230, 265, 300, 345]
FUEL_KG_PER_M = 0.36 / 1000
FUEL_START = 100.0


def _clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v


def _toward(cur: float, target: float, dt: float, tau: float) -> float:
    return cur + (target - cur) * min(1.0, dt / tau)


@dataclass
class Car:
    car_id: str
    number: int
    driver: str
    team: str
    team_car: bool
    skill: float
    lane: float
    compound: str
    s: float
    consumable_mult: float = 3.0
    rng: random.Random = field(default_factory=random.Random)

    # dinâmica
    lap: int = 0
    total: float = 0.0
    speed: float = 0.0
    throttle: float = 0.0
    brake: float = 0.0
    gear: int = 1
    rpm: float = 4000.0
    lat: float = 0.0

    # atuadores
    engine_mode: str = "STANDARD"
    ers_mode: str = "BALANCED"
    cooling: bool = False
    cooling_source: str = "auto"
    drs: bool = False
    box_compound: str | None = None

    # sensores
    engine_temp: float = 95.0
    oil_temp: float = 92.0
    oil_pressure: float = 5.4
    vibration: float = 0.9
    fuel: float = FUEL_START
    ers: float = 0.8
    tyre_age: float = 0.0
    wear: dict = field(default_factory=lambda: {w: 0.0 for w in WHEELS})
    ttemp: dict = field(default_factory=lambda: {w: 80.0 for w in WHEELS})
    tpress: dict = field(default_factory=lambda: {w: 21.0 for w in WHEELS})
    btemp: dict = field(default_factory=lambda: {w: 300.0 for w in WHEELS})

    # cronometragem
    lap_start: float = 0.0
    last_lap: float = 0.0
    best_lap: float = 0.0
    position: int = 0
    gap_leader: float = 0.0
    interval: float = 0.0
    pits: int = 0
    status: str = "RUNNING"         # RUNNING | PIT | DNF

    # estado oculto (rótulos de verdade) — nunca publicados
    _pu_wear: float = 0.1
    _faults: set = field(default_factory=set)
    _leak: dict = field(default_factory=lambda: {w: 0.0 for w in WHEELS})
    _pit_phase: str | None = None
    _pit_timer: float = 0.0
    _dnf_reason: str = ""

    events: list = field(default_factory=list)

    # ------------------------------------------------------------------ comandos
    def apply_command(self, action: str, value, source: str) -> str:
        if action == "engine_mode" and value in ENGINE_MODES:
            self.engine_mode = value
        elif action == "ers_mode" and value in ERS_MODES:
            self.ers_mode = value
        elif action == "cooling":
            self.cooling = bool(value)
            self.cooling_source = source
        elif action == "box":
            self.box_compound = value if value in COMPOUNDS else self.compound
        elif action == "cancel_box":
            if self._pit_phase is None:
                self.box_compound = None
        elif action == "fault":
            if value in ("pu_bearing", "slow_puncture"):
                self._faults.add(value)
                if value == "slow_puncture":
                    self._faults.add(f"leak_{self.rng.choice(WHEELS)}")
        elif action == "repair":
            self._faults.clear()
            self._pu_wear = 0.05
        elif action == "restart":
            if self.status == "DNF":
                self._reset_after_dnf()
        else:
            return "ignored"
        return "ok"

    def _reset_after_dnf(self) -> None:
        self.status = "RUNNING"
        self._pu_wear = 0.05
        self._faults.clear()
        self.fuel = FUEL_START
        self._fit_tyres(self.compound)
        self.engine_temp = self.oil_temp = 90.0

    def _fit_tyres(self, compound: str) -> None:
        self.compound = compound
        self.tyre_age = 0.0
        for w in WHEELS:
            self.wear[w] = 0.0
            self.ttemp[w] = 70.0
            self._leak[w] = 0.0
        self._faults = {f for f in self._faults if not f.startswith("leak_") and f != "slow_puncture"}

    # ------------------------------------------------------------------ passo
    def step(self, dt: float, t: float, tr: Track, ahead_interval: float) -> None:
        mode = ENGINE_MODES[self.engine_mode]
        ers_mode = ERS_MODES[self.ers_mode]
        i = tr.idx(self.s)
        k = float(tr.k[i])
        v_prof = float(tr.v[i])

        # ---- estado do PU (degradação progressiva, oculta)
        rate = (1 / (3 * 3600)) * mode["pu"]
        if "pu_bearing" in self._faults:
            rate += (1 / 240) * (0.4 + self._pu_wear)
        if self.status != "DNF":
            self._pu_wear = min(1.0, self._pu_wear + rate * dt * (self.consumable_mult if "pu_bearing" not in self._faults else 1))
        deg = self._pu_wear ** 2

        if self.status != "DNF" and self._pu_wear >= 1.0:
            self._dnf("engine_failure")
        if self.status != "DNF" and self.fuel <= 0.0:
            self._dnf("out_of_fuel")

        # ---- velocidade alvo
        avg_wear = sum(self.wear.values()) / 4
        grip = COMPOUNDS[self.compound]["grip"]
        grip *= (1 - 0.03 * avg_wear) if avg_wear < 0.65 else (1 - 0.0195 - (avg_wear - 0.65) * 0.45)
        lo, hi = COMPOUNDS[self.compound]["opt"]
        avg_t = sum(self.ttemp.values()) / 4
        grip -= min(0.03, 0.0015 * max(0.0, lo - avg_t, avg_t - hi))
        grip -= 0.04 * sum(1 for w in WHEELS if self.tpress[w] < 16) / 4

        target = v_prof * self.skill * mode["speed"] * grip
        if self.cooling and v_prof > 70:
            target *= 0.97                 # lift-and-coast nas retas
        self.drs = tr.in_drs(self.s) and 0 < ahead_interval < 1.0 and self._pit_phase is None
        if self.drs:
            target *= 1.035
        deploying = self.ers > 0.02 and ers_mode["deploy"] > 0 and self.throttle > 0.9 and self.speed > 50
        if deploying:
            target *= 1 + 0.6 * ers_mode["deploy"]
        if deg > 0.35:
            target *= 1 - 0.25 * (deg - 0.35)   # PU perdendo potência

        target = self._pit_logic(target, tr, dt)
        if self.status == "DNF":
            target = 0.0

        # ---- aceleração
        dv = target - self.speed
        a = min(dv / dt, 3 + 10 * (1 - self.speed / V_MAX)) if dv > 0 else max(dv / dt, -45.0)
        self.speed = max(0.0, self.speed + a * dt)
        kph = self.speed * 3.6
        if self.status == "DNF":
            self.throttle, self.brake = 0.0, 0.0
        elif a > 0.5:
            self.throttle, self.brake = 1.0, 0.0
        elif a > -2:
            self.throttle, self.brake = 0.25 + 0.7 * self.speed / V_MAX, 0.0
        else:
            self.throttle, self.brake = 0.0, _clamp(-a / 45, 0, 1)

        g = 1
        while g < 8 and kph > GEAR_KPH[g]:
            g += 1
        self.gear = g
        frac = _clamp((kph - GEAR_KPH[g - 1]) / (GEAR_KPH[g] - GEAR_KPH[g - 1]), 0, 1)
        rpm = (9800 + 2300 * frac + mode["rpm"]) if kph > 20 else 4500 + kph * 150
        if self.status == "DNF":
            rpm = 0.0 if "engine" in self._dnf_reason else 4000.0
        self.rpm = rpm + self.rng.gauss(0, 40) if rpm > 0 else 0.0

        # ---- deslocamento
        ds = self.speed * dt
        self.s += ds
        self.total += ds
        if self.s >= tr.length:
            self.s -= tr.length
            self.lap += 1
            if self.lap > 1:
                self.last_lap = t - self.lap_start
                self.best_lap = self.last_lap if not self.best_lap else min(self.best_lap, self.last_lap)
            self.lap_start = t
            self.tyre_age += 1
            self.events.append(("lap", {"lap": self.lap, "last_lap": round(self.last_lap, 3)}))
        lat_target = PIT_OFFSET if self._pit_phase else self.lane
        self.lat += _clamp(lat_target - self.lat, -4 * dt, 4 * dt)

        # ---- pneus
        alat = self.speed ** 2 * abs(k)
        lat_n = _clamp(alat / 44, 0, 1.2)
        base_wear = 1 / (COMPOUNDS[self.compound]["life_laps"] * tr.length) * self.consumable_mult
        for w in WHEELS:
            side = 1 if w[1] == "R" else -1
            outer = side * (1 if k > 0 else -1) > 0
            front = w[0] == "F"
            load = 0.35 + lat_n * (1.3 if outer else 0.7) + (self.brake * 0.5 if front else self.throttle * 0.35)
            if f"leak_{w}" in self._faults:
                self._leak[w] += 0.03 * dt
            press_mult = 4.0 if self.tpress[w] < 15 else 1.0
            temp_mult = 1 + max(0.0, self.ttemp[w] - hi) / 20
            self.wear[w] = min(1.0, self.wear[w] + base_wear * ds * load * mode["wear"] * temp_mult * press_mult)
            moving = min(1.0, self.speed / 40)
            t_target = 62 + 40 * load * moving + mode["temp"] * 0.5 + max(0.0, self.wear[w] - 0.65) * 60
            if self.tpress[w] < 16:
                t_target += 18
            self.ttemp[w] = _toward(self.ttemp[w], t_target, dt, 6) + self.rng.gauss(0, 0.15)
            self.tpress[w] = max(5.0, 19.5 + (self.ttemp[w] - 70) * 0.06 - self._leak[w])
            b_target = 280 + 720 * self.brake * (1.2 if front else 0.8) + 120 * moving
            self.btemp[w] = _toward(self.btemp[w], b_target, dt, 0.6 if b_target > self.btemp[w] else 3.0)

        # ---- motor / PU
        eng_target = 94 + 16 * self.throttle + mode["temp"] + ers_mode["temp"] - (16 if self.cooling else 0) + 14 * deg
        eng_target += 2.5 * math.sin(t / 300)            # deriva lenta de ambiente
        if self.status == "DNF":
            eng_target = 60
        self.engine_temp = _toward(self.engine_temp, eng_target, dt, 25) + self.rng.gauss(0, 0.05)
        self.oil_temp = _toward(self.oil_temp, self.engine_temp - 4 + 25 * deg, dt, 40)
        self.oil_pressure = (5.2 + 0.9 * (self.rpm / 12000) - 2.6 * deg - 0.01 * (self.oil_temp - 100)
                             + self.rng.gauss(0, 0.04)) if self.rpm > 0 else 0.0
        self.vibration = (0.6 + 0.5 * (self.rpm / 12000) + 2.8 * deg + self.rng.gauss(0, 0.04)) if self.rpm > 0 else 0.02

        # ---- combustível e ERS
        self.fuel = max(0.0, self.fuel - FUEL_KG_PER_M * ds * (0.35 + 0.65 * self.throttle) / 0.84
                        * mode["fuel"] * self.consumable_mult)
        if deploying:
            self.ers -= ers_mode["deploy"] * dt
        self.ers = _clamp(self.ers + self.brake * 0.14 * ers_mode["harvest"] * dt, 0, 1)

    # ------------------------------------------------------------------ pit
    def _pit_logic(self, target: float, tr: Track, dt: float) -> float:
        phase = self._pit_phase
        if phase is None:
            if self.box_compound and tr.pit_entry <= self.s <= tr.pit_entry + 60 and self.status == "RUNNING":
                self._pit_phase, self.status = "entry", "PIT"
                self.events.append(("pit_in", {"lap": self.lap}))
            return target
        if phase == "entry":
            if tr.pit_box <= self.s < tr.pit_exit:
                self._pit_phase, self._pit_timer = "stopped", 2.4
                self.speed = 0.0
                return 0.0
            return min(target, 22.2)
        if phase == "stopped":
            self._pit_timer -= dt
            if self._pit_timer <= 0:
                old = self.compound
                self._fit_tyres(self.box_compound or self.compound)
                self.fuel = FUEL_START  # reabastecimento (modo demonstração)
                self.pits += 1
                self.box_compound = None
                self._pit_phase = "exit"
                self.events.append(("pit_stop", {"from": old, "to": self.compound, "stops": self.pits}))
                return 5.0
            return 0.0
        if phase == "exit":
            if self.s >= tr.pit_exit:
                self._pit_phase, self.status = None, "RUNNING"
                self.events.append(("pit_out", {"lap": self.lap}))
                return target
            return min(target, 22.2)
        return target

    def _dnf(self, reason: str) -> None:
        self.status = "DNF"
        self._dnf_reason = reason
        self._pit_phase = None
        self.box_compound = None
        self.events.append(("dnf", {"reason": reason, "lap": self.lap}))

    # ------------------------------------------------------------------ leitura
    def telemetry(self, tr: Track) -> dict:
        r1 = lambda v: round(v, 1)  # noqa: E731
        p = {
            "car_id": self.car_id, "number": self.number, "driver": self.driver, "team": self.team,
            "team_car": self.team_car, "status": self.status, "position": self.position,
            "lap": self.lap, "lap_dist": r1(self.s), "track_pos": round(self.s / tr.length, 5),
            "lat": round(self.lat, 2), "sector": tr.sector(self.s),
            "gap_leader": round(self.gap_leader, 2), "interval": round(self.interval, 2),
            "last_lap": round(self.last_lap, 3), "best_lap": round(self.best_lap, 3), "pits": self.pits,
            "speed_kph": r1(self.speed * 3.6), "rpm": int(self.rpm), "gear": self.gear,
            "throttle": round(self.throttle, 2), "brake": round(self.brake, 2),
            "engine_temp": r1(self.engine_temp), "oil_temp": r1(self.oil_temp),
            "oil_pressure": round(self.oil_pressure, 2), "pu_vibration": round(self.vibration, 3),
            "fuel_kg": round(self.fuel, 2), "ers_soc": round(self.ers * 100, 1),
            "engine_mode": self.engine_mode, "ers_mode": self.ers_mode,
            "cooling": int(self.cooling), "cooling_source": self.cooling_source,
            "drs": int(self.drs), "box_requested": int(self.box_compound is not None),
            "in_pit": int(self._pit_phase is not None),
            "tyre_compound": self.compound, "tyre_age": round(self.tyre_age, 1),
        }
        for w in WHEELS:
            p[f"tyre_temp_{w}"] = r1(self.ttemp[w])
            p[f"tyre_wear_{w}"] = r1(self.wear[w] * 100)
            p[f"tyre_press_{w}"] = r1(self.tpress[w])
            p[f"brake_temp_{w}"] = int(self.btemp[w])
        return p
