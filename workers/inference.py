"""Inferência em tempo real (consome q.inference).

Para cada carro guarda as últimas leituras da PU (1 por segundo), calcula as
features com o MESMO código do treino (pitwall_common.features) e aplica os
2 modelos: índice de saúde (0–100) e vida útil restante (h). Publica
prediction.<carro> e alertas preditivos (alert.<carro>) com histerese.

Quando o ml-worker salva um modelo novo (current.json muda), ele é recarregado
sem reiniciar o serviço.
"""
from __future__ import annotations

import json
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

import joblib
import numpy as np
import psycopg
from psycopg.rows import dict_row

from pitwall_common import amqp, envelope, features, topics
from pitwall_common.config import env

logging.basicConfig(level=logging.INFO, format="%(asctime)s [inference] %(message)s")
log = logging.getLogger("inference")

MODELS_DIR = Path(env("MODELS_DIR", "/data/models"))
EVERY = 10                     # 1 de cada 10 leituras (10 Hz -> 1 Hz), como o "minuto" do laboratório
RAISE_BELOW, RAISE_COUNT = 50.0, 3       # 3 previsões seguidas abaixo de 50 disparam
CLEAR_ABOVE, CLEAR_COUNT = 60.0, 10      # 10 previsões seguidas acima de 60 limpam
RULE = "ia_pu_health"


@dataclass
class CarState:
    n: int = 0
    rows: deque = field(default_factory=lambda: deque(maxlen=features.WINDOW))
    health_hist: deque = field(default_factory=lambda: deque(maxlen=30))
    health: float | None = None
    rul: float | None = None
    below: int = 0
    above: int = 0
    alert_id: int | None = None
    status: str = "RUNNING"


class Models:
    def __init__(self) -> None:
        self.version: int | None = None
        self.health = self.rul = None
        self._mtime = 0.0
        self._checked = 0.0

    def refresh(self) -> None:
        if time.time() - self._checked < 5:
            return
        self._checked = time.time()
        cur = MODELS_DIR / "current.json"
        try:
            mtime = cur.stat().st_mtime
        except FileNotFoundError:
            return
        if mtime == self._mtime:
            return
        try:
            version = int(json.loads(cur.read_text(encoding="utf-8"))["version"])
            vdir = MODELS_DIR / f"v{version}"
            health, rul = joblib.load(vdir / "health.joblib"), joblib.load(vdir / "rul.joblib")
            for m in (health, rul):
                m.n_jobs = 1
            self.health, self.rul, self.version, self._mtime = health, rul, version, mtime
            log.info("Modelo v%d carregado (troca a quente)", version)
        except Exception as exc:  # noqa: BLE001
            log.warning("Não foi possível carregar o modelo: %s", exc)

    @property
    def ready(self) -> bool:
        return self.health is not None


def pg():
    for attempt in range(60):
        try:
            return psycopg.connect(env("POSTGRES_DSN"), autocommit=True, row_factory=dict_row)
        except Exception as exc:  # noqa: BLE001
            log.warning("Postgres indisponível (%s) %d/60", exc, attempt + 1)
            time.sleep(2)
    raise RuntimeError("Postgres indisponível")


class Inference:
    def __init__(self) -> None:
        self.db = pg()
        self.db.execute("update alerts set cleared_at = now() where cleared_at is null and rule_id is null and field = 'pu_health'")
        self.models = Models()
        self.cars: dict[str, CarState] = {}

    def on_telemetry(self, msg: dict, publish) -> None:
        if msg["type"] != "telemetry":
            return
        car, p = msg["device"], msg["payload"]
        st = self.cars.setdefault(car, CarState())
        if p.get("status") != st.status:                 # quebrou, voltou ou foi reparado: recomeça a janela
            if st.status == "DNF" or p.get("status") == "DNF":
                st.rows.clear(); st.health_hist.clear(); st.health = st.rul = None
            st.status = p.get("status", "RUNNING")
        st.n += 1
        if st.n % EVERY:
            return
        self.models.refresh()
        if not self.models.ready:
            return

        if st.status == "DNF":
            health, rul = 0.0, 0.0
        else:
            st.rows.append([p.get(s, np.nan) for s in features.SIGNALS])
            if len(st.rows) < 10:
                return
            x = features.last_row(np.array(st.rows))
            h_raw = float(np.clip(self.models.health.predict(x)[0], 0, 100))
            r_raw = float(max(0.0, self.models.rul.predict(x)[0]))
            # suavização exponencial: a previsão não fica pulando a cada segundo
            health = h_raw if st.health is None else st.health + 0.3 * (h_raw - st.health)
            rul = r_raw if st.rul is None else st.rul + 0.3 * (r_raw - st.rul)
        st.health, st.rul = health, rul
        st.health_hist.append(health)
        trend = (health - st.health_hist[0]) / len(st.health_hist) * 60 if len(st.health_hist) > 5 else 0.0

        publish(topics.rk_prediction(car), envelope.make("prediction", car, {
            "health": round(health, 1), "rul_h": round(rul, 1), "trend_per_min": round(trend, 2),
            "model_version": self.models.version}, "inference"))
        self._hysteresis(car, st, publish)

    def _hysteresis(self, car: str, st: CarState, publish) -> None:
        h = st.health
        if st.alert_id is None:
            st.below = st.below + 1 if h < RAISE_BELOW else 0
            if st.below >= RAISE_COUNT:
                sev = "critical" if h < 30 else "warning"
                message = f"{car}: IA prevê saúde da PU {h:.0f}/100 e falha em ~{st.rul:.1f} h — planejar troca/reparo"
                row = self.db.execute(
                    "insert into alerts (car_id, rule_id, field, severity, message, value) values (%s,null,'pu_health',%s,%s,%s) returning id",
                    (car, sev, message, h)).fetchone()
                st.alert_id, st.above = row["id"], 0
                log.info("ALERTA PREDITIVO %s", message)
                publish(topics.rk_alert(car), envelope.make("alert", car, {
                    "state": "raised", "alert_id": st.alert_id, "rule": RULE, "field": "pu_health",
                    "severity": sev, "message": message, "value": round(h, 1)}, "inference"))
        else:
            st.above = st.above + 1 if h >= CLEAR_ABOVE else 0
            if st.above >= CLEAR_COUNT:
                self.db.execute("update alerts set cleared_at = now() where id = %s", (st.alert_id,))
                publish(topics.rk_alert(car), envelope.make("alert", car, {
                    "state": "cleared", "alert_id": st.alert_id, "rule": RULE, "field": "pu_health",
                    "severity": "warning", "value": round(h, 1)}, "inference"))
                log.info("Alerta preditivo limpo %s", car)
                st.alert_id, st.below = None, 0


def main() -> None:
    engine = Inference()
    while True:
        conn = amqp.connect("RABBITMQ_INFER_USER", "RABBITMQ_INFER_PASSWORD")
        ch = conn.channel()
        ch.basic_qos(prefetch_count=200)

        def publish(rk: str, msg: dict) -> None:
            ch.basic_publish(topics.EXCHANGE, rk, envelope.dumps(msg), amqp.json_props())

        def on_msg(chan, method, props, body):
            try:
                engine.on_telemetry(envelope.loads(body), publish)
                chan.basic_ack(method.delivery_tag)
            except Exception as exc:  # noqa: BLE001
                log.exception("Falha na inferência -> DLQ: %s", exc)
                chan.basic_nack(method.delivery_tag, requeue=False)

        ch.basic_consume(topics.Q_INFERENCE, on_msg)
        log.info("Consumindo %s", topics.Q_INFERENCE)
        try:
            while True:
                conn.process_data_events(time_limit=1.0)
                amqp.beat()
                engine.models.refresh()
        except Exception as exc:  # noqa: BLE001
            log.error("Conexão perdida (%s), reconectando...", exc)
            time.sleep(2)


if __name__ == "__main__":
    main()
