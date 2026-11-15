"""InfluxDB: consulta do histórico de telemetria (evolução de configs/db.py do 1º bimestre).

As queries são montadas só com valores validados (regex/whitelist) — nada do
usuário entra cru no Flux.
"""
from __future__ import annotations

import re

from influxdb_client import InfluxDBClient

from pitwall_common.config import env

CAR_RE = re.compile(r"^[A-Z0-9]{2,8}$")
FIELD_RE = re.compile(r"^[A-Za-z0-9_]{1,40}$")
EVERY = {"1s", "2s", "5s", "10s", "30s", "1m", "5m"}

client = InfluxDBClient(url=env("INFLUXDB_URL", "http://influxdb:8086"), token=env("INFLUXDB_TOKEN"),
                        org=env("INFLUXDB_ORG", "pitwall"), timeout=15000)
BUCKET = env("INFLUXDB_BUCKET", "telemetry")


def history(car_id: str, fields: list[str], minutes: int, every: str) -> dict:
    if not CAR_RE.match(car_id):
        raise ValueError("car_id inválido")
    if not fields or len(fields) > 12 or not all(FIELD_RE.match(f) for f in fields):
        raise ValueError("fields inválidos")
    if every not in EVERY:
        raise ValueError("every inválido")
    minutes = max(1, min(int(minutes), 1440))
    field_set = ", ".join(f'"{f}"' for f in fields)
    flux = f'''
from(bucket: "{BUCKET}")
  |> range(start: -{minutes}m)
  |> filter(fn: (r) => r._measurement == "telemetry" and r.car_id == "{car_id}")
  |> filter(fn: (r) => contains(value: r._field, set: [{field_set}]))
  |> drop(columns: ["tyre_compound", "team"])
  |> group(columns: ["_field"])
  |> aggregateWindow(every: {every}, fn: mean, createEmpty: false)
  |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
  |> sort(columns: ["_time"])
'''
    tables = client.query_api().query(flux)
    rows: list[dict] = []
    for table in tables:
        for rec in table.records:
            row = {"time": rec.get_time().isoformat()}
            for f in fields:
                v = rec.values.get(f)
                if v is not None:
                    row[f] = round(float(v), 3)
            rows.append(row)
    rows.sort(key=lambda r: r["time"])
    return {"car_id": car_id, "fields": fields, "minutes": minutes, "every": every, "rows": rows}


def ping() -> bool:
    try:
        return bool(client.ping())
    except Exception:  # noqa: BLE001
        return False
