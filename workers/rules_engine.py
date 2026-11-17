"""Motor de regras — consumidor q.rules.

Lê as regras do PostgreSQL (tabela rules), avalia cada leitura de telemetria com
histerese (N leituras seguidas para disparar, M para limpar) e:
  * registra/encerra alertas na tabela alerts;
  * publica alert.<carro> no RabbitMQ (chega na interface pelo WebSocket);
  * quando a regra tem ação, publica command.<carro> (atuador automático —
    ex.: motor > 118 °C liga o resfriamento) e grava na auditoria.
"""
from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass

import psycopg
from psycopg.rows import dict_row

from pitwall_common import amqp, envelope, topics
from pitwall_common.config import env

logging.basicConfig(level=logging.INFO, format="%(asctime)s [rules] %(message)s")
log = logging.getLogger("rules")

WHEELS = ("FL", "FR", "RL", "RR")
RELOAD_S = 10


def derived(p: dict) -> dict:
    """Campos agregados que as regras podem usar além dos crus."""
    out = dict(p)
    try:
        out["tyre_wear_max"] = max(p[f"tyre_wear_{w}"] for w in WHEELS)
        out["tyre_temp_max"] = max(p[f"tyre_temp_{w}"] for w in WHEELS)
        out["tyre_press_min"] = min(p[f"tyre_press_{w}"] for w in WHEELS)
        out["brake_temp_max"] = max(p[f"brake_temp_{w}"] for w in WHEELS)
    except KeyError:
        pass
    return out


@dataclass
class RuleState:
    active: bool = False
    on: int = 0
    off: int = 0
    alert_id: int | None = None


class Engine:
    def __init__(self) -> None:
        self.db = self._db()
        self.rules: list[dict] = []
        self.state: dict[tuple[str, int], RuleState] = {}
        self.loaded_at = 0.0
        # o estado de histerese vive em memória: ao reiniciar, encerra os alertas de regra que ficaram abertos
        closed = self.db.execute("update alerts set cleared_at = now() where cleared_at is null and rule_id is not null returning id").fetchall()
        if closed:
            log.info("%d alertas antigos encerrados na inicialização", len(closed))

    def _db(self):
        for attempt in range(60):
            try:
                return psycopg.connect(env("POSTGRES_DSN"), autocommit=True, row_factory=dict_row)
            except Exception as exc:  # noqa: BLE001
                log.warning("Postgres indisponível (%s) %d/60", exc, attempt + 1)
                time.sleep(2)
        raise RuntimeError("Postgres indisponível")

    def reload(self) -> None:
        if time.time() - self.loaded_at < RELOAD_S:
            return
        try:
            self.rules = self.db.execute("select * from rules where enabled order by id").fetchall()
            self.loaded_at = time.time()
        except Exception as exc:  # noqa: BLE001
            log.error("Erro ao carregar regras: %s", exc)
            self.db = self._db()

    def evaluate(self, msg: dict, publish) -> None:
        self.reload()
        p = derived(msg["payload"])
        car = msg["device"]
        if p.get("status") == "DNF":
            return
        for rule in self.rules:
            if rule["team_only"] and not p.get("team_car"):
                continue
            value = p.get(rule["field"])
            if not isinstance(value, (int, float)):
                continue
            st = self.state.setdefault((car, rule["id"]), RuleState())
            above = rule["op"] == ">"
            trip = value > rule["threshold"] if above else value < rule["threshold"]
            clear = value < rule["clear_threshold"] if above else value > rule["clear_threshold"]
            if not st.active:
                st.on = st.on + 1 if trip else 0
                if st.on >= rule["on_count"]:
                    st.active, st.off = True, 0
                    self._raise(car, rule, value, st, publish)
            else:
                st.off = st.off + 1 if clear else 0
                if st.off >= rule["off_count"]:
                    st.active, st.on = False, 0
                    self._clear(car, rule, value, st, publish)

    def _raise(self, car: str, rule: dict, value: float, st: RuleState, publish) -> None:
        message = rule["message"].format(car=car, value=round(value, 2), threshold=rule["threshold"])
        row = self.db.execute(
            "insert into alerts (car_id, rule_id, field, severity, message, value) values (%s,%s,%s,%s,%s,%s) returning id",
            (car, rule["id"], rule["field"], rule["severity"], message, value)).fetchone()
        st.alert_id = row["id"]
        log.info("ALERTA %s: %s", car, message)
        publish(topics.rk_alert(car), envelope.make("alert", car, {
            "state": "raised", "alert_id": st.alert_id, "rule": rule["name"], "field": rule["field"],
            "severity": rule["severity"], "message": message, "value": value}, "rules-engine"))
        if rule["action_on"]:
            self._command(car, rule, rule["action_on"], value, publish)

    def _clear(self, car: str, rule: dict, value: float, st: RuleState, publish) -> None:
        if st.alert_id:
            self.db.execute("update alerts set cleared_at = now() where id = %s", (st.alert_id,))
        log.info("Alerta limpo %s: %s", car, rule["name"])
        publish(topics.rk_alert(car), envelope.make("alert", car, {
            "state": "cleared", "alert_id": st.alert_id, "rule": rule["name"], "field": rule["field"],
            "severity": rule["severity"], "value": value}, "rules-engine"))
        if rule["action_off"]:
            self._command(car, rule, rule["action_off"], value, publish)
        st.alert_id = None

    def _command(self, car: str, rule: dict, action: dict, value: float, publish) -> None:
        cmd = envelope.make("command", car, {"action": action["action"], "value": action.get("value"),
                                             "rule": rule["name"], "trigger_value": value}, "rules")
        publish(topics.rk_command(car), cmd)
        self.db.execute("insert into audit_log (actor, action, target, details) values (%s,%s,%s,%s)",
                        ("rules-engine", f"command.{action['action']}", car,
                         json.dumps({"value": action.get("value"), "rule": rule["name"], "trigger": value,
                                     "command_id": cmd["id"]})))


def main() -> None:
    engine = Engine()
    while True:
        conn = amqp.connect("RABBITMQ_RULES_USER", "RABBITMQ_RULES_PASSWORD")
        ch = conn.channel()
        ch.basic_qos(prefetch_count=200)

        def publish(rk: str, msg: dict) -> None:
            ch.basic_publish(topics.EXCHANGE, rk, envelope.dumps(msg), amqp.json_props())

        def on_msg(chan, method, props, body):
            try:
                engine.evaluate(envelope.loads(body), publish)
                chan.basic_ack(method.delivery_tag)
            except Exception as exc:  # noqa: BLE001
                log.exception("Falha ao avaliar -> DLQ: %s", exc)
                chan.basic_nack(method.delivery_tag, requeue=False)

        ch.basic_consume(topics.Q_RULES, on_msg)
        try:
            while True:
                conn.process_data_events(time_limit=1.0)
                amqp.beat()
        except Exception as exc:  # noqa: BLE001
            log.error("Conexão perdida (%s), reconectando...", exc)
            time.sleep(2)


if __name__ == "__main__":
    main()
