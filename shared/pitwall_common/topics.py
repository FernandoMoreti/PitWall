"""Nomes de tópicos MQTT e routing keys do RabbitMQ (uma única fonte)."""

# ---- MQTT (borda: simulador <-> gateway)
MQTT_TELEMETRY = "f1/{car}/telemetry"
MQTT_EVENT = "f1/{car}/event"
MQTT_CMD = "f1/{car}/cmd"
MQTT_SIM_STATUS = "f1/sim/status"
MQTT_SUB_FROM_DEVICES = ["f1/+/telemetry", "f1/+/event", MQTT_SIM_STATUS]

# ---- RabbitMQ (barramento interno)
EXCHANGE = "f1"            # topic (DLX f1.dlx -> q.dead, definidos em scripts/gen_secrets.py)

Q_INFLUX = "q.influx"
Q_RULES = "q.rules"
Q_WS = "q.ws"
Q_COMMANDS = "q.commands"
Q_INFERENCE = "q.inference"
Q_JOB_GENERATE = "q.jobs.generate"
Q_JOB_TRAIN = "q.jobs.train"

RK_JOB_GENERATE = "job.generate"
RK_JOB_TRAIN = "job.train"


def rk_telemetry(team: str, car: str) -> str:
    return f"telemetry.{slug(team)}.car.{car}"


def rk_event(kind: str, car: str) -> str:
    return f"event.{slug(kind)}.{car}"


def rk_command(car: str) -> str:
    return f"command.{car}"


def rk_alert(car: str) -> str:
    return f"alert.{car}"


def rk_prediction(car: str) -> str:
    return f"prediction.{car}"


def slug(text: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in text.lower())
