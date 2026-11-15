"""Consumidor q.influx → InfluxDB.

Evolução do on_message do 1º bimestre (antigo backend-iot/configs/broker.py):
cada leitura vira um Point do measurement "telemetry" com tags car_id/team e um
field por variável numérica. Grava em lotes; se a gravação falhar, o lote vai
para a DLQ (nack sem requeue) com a mensagem preservada.
"""
from __future__ import annotations

import logging
import time

from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS

from pitwall_common import amqp, envelope, topics
from pitwall_common.config import env

logging.basicConfig(level=logging.INFO, format="%(asctime)s [influx-writer] %(message)s")
log = logging.getLogger("influx-writer")

TAGS = ("car_id", "team", "tyre_compound")
STRING_FIELDS = ("status", "engine_mode", "ers_mode", "cooling_source", "driver")
BATCH = 120
EVENT_NUMERIC = ("lap", "last_lap", "stops")
FLUSH_S = 1.0


def to_point(msg: dict) -> Point:
    p = msg["payload"]
    if msg["type"] == "telemetry":
        point = Point("telemetry")
    else:
        point = Point("events").field("kind", str(p.get("kind", "generic")))
    point.tag("car_id", msg["device"])
    for tag in TAGS[1:]:
        if tag in p:
            point.tag(tag, str(p[tag]))
    for key, value in p.items():
        if key in TAGS or key == "car_id":
            continue
        if msg["type"] != "telemetry":
            # eventos têm payload heterogêneo (ex.: value = "PUSH" ou true): tipo fixo por campo evita conflito no Influx
            if key in EVENT_NUMERIC and isinstance(value, (int, float)):
                point.field(key, float(value))
            elif value is not None:
                point.field(key, str(value))
            continue
        if isinstance(value, bool):
            point.field(key, int(value))
        elif isinstance(value, (int, float)):
            point.field(key, float(value))
        elif key in STRING_FIELDS:
            point.field(key, str(value))
    return point.time(int(msg["ts"] * 1000), WritePrecision.MS)


def main() -> None:
    client = InfluxDBClient(url=env("INFLUXDB_URL", "http://influxdb:8086"), token=env("INFLUXDB_TOKEN"),
                            org=env("INFLUXDB_ORG", "pitwall"))
    write = client.write_api(write_options=SYNCHRONOUS)
    bucket = env("INFLUXDB_BUCKET", "telemetry")

    while True:
        conn = amqp.connect("RABBITMQ_WRITER_USER", "RABBITMQ_WRITER_PASSWORD")
        ch = conn.channel()
        ch.basic_qos(prefetch_count=BATCH * 2)
        pending: list[tuple[int, Point]] = []
        last_flush = time.time()
        written = 0

        def on_msg(chan, method, props, body):
            try:
                pending.append((method.delivery_tag, to_point(envelope.loads(body))))
            except Exception as exc:  # noqa: BLE001
                log.warning("Mensagem inválida -> DLQ: %s", exc)
                chan.basic_nack(method.delivery_tag, requeue=False)

        ch.basic_consume(topics.Q_INFLUX, on_msg)
        try:
            while True:
                conn.process_data_events(time_limit=0.2)
                amqp.beat()
                if pending and (len(pending) >= BATCH or time.time() - last_flush > FLUSH_S):
                    tags = [t for t, _ in pending]
                    try:
                        write.write(bucket=bucket, record=[p for _, p in pending])
                        for t in tags:
                            ch.basic_ack(t)
                        written += len(tags)
                    except Exception as exc:  # noqa: BLE001
                        log.error("Falha ao gravar lote de %d no InfluxDB -> DLQ: %s", len(tags), exc)
                        for t in tags:
                            ch.basic_nack(t, requeue=False)
                    pending.clear()
                    last_flush = time.time()
                    if written and written % 3000 < BATCH:
                        log.info("%d pontos gravados", written)
        except Exception as exc:  # noqa: BLE001
            log.error("Conexão perdida (%s), reconectando...", exc)
            time.sleep(2)


if __name__ == "__main__":
    main()
