"""Mensageria (API de gerenciamento do RabbitMQ) e saúde do sistema.

O navegador nunca fala com o broker: o backend consulta a API de gerenciamento
com o usuário de monitoramento e devolve só o necessário.
"""
from __future__ import annotations

import time

import httpx
from fastapi import APIRouter

import db
import influx
from bus import hub
from pitwall_common.config import env

router = APIRouter(prefix="/api", tags=["operação"])

MGMT = env("RABBITMQ_MGMT_URL", "http://rabbitmq:15672")
VHOST = env("RABBITMQ_VHOST", "pitwall")
AUTH = (env("RABBITMQ_API_USER"), env("RABBITMQ_API_PASSWORD"))


def _rate(stats: dict | None, key: str) -> float:
    return round(((stats or {}).get(f"{key}_details") or {}).get("rate", 0.0), 1)


@router.get("/messaging")
async def messaging():
    async with httpx.AsyncClient(base_url=MGMT, auth=AUTH, timeout=5) as c:
        try:
            queues = (await c.get(f"/api/queues/{VHOST}")).json()
            overview = (await c.get("/api/overview")).json()
            consumers = (await c.get(f"/api/consumers/{VHOST}")).json()
            dead = []
            r = await c.post(f"/api/queues/{VHOST}/q.dead/get",
                             json={"count": 5, "ackmode": "ack_requeue_true", "encoding": "auto", "truncate": 400})
            if r.status_code == 200:
                dead = [{"routing_key": m.get("routing_key"), "payload": m.get("payload"),
                         "reason": ((m.get("properties") or {}).get("headers") or {}).get("x-death", [{}])[0].get("reason")}
                        for m in r.json()]
        except (httpx.HTTPError, ValueError) as exc:
            return {"ok": False, "error": str(exc)}

    by_queue: dict[str, list] = {}
    for con in consumers if isinstance(consumers, list) else []:
        q = (con.get("queue") or {}).get("name")
        by_queue.setdefault(q, []).append({
            "tag": con.get("consumer_tag"),
            "user": (con.get("channel_details") or {}).get("user"),
            "prefetch": con.get("prefetch_count"),
        })

    ms = overview.get("message_stats", {})
    return {
        "ok": True,
        "ts": time.time(),
        "overview": {
            "publish_rate": _rate(ms, "publish"), "deliver_rate": _rate(ms, "deliver_get"),
            "ack_rate": _rate(ms, "ack"),
            "messages": (overview.get("queue_totals") or {}).get("messages", 0),
            "connections": (overview.get("object_totals") or {}).get("connections", 0),
            "consumers": (overview.get("object_totals") or {}).get("consumers", 0),
        },
        "queues": [{
            "name": q["name"],
            "messages": q.get("messages", 0), "ready": q.get("messages_ready", 0),
            "unacked": q.get("messages_unacknowledged", 0), "consumers": q.get("consumers", 0),
            "publish_rate": _rate(q.get("message_stats"), "publish"),
            "deliver_rate": _rate(q.get("message_stats"), "deliver_get"),
            "consumer_list": by_queue.get(q["name"], []),
            "arguments": q.get("arguments", {}),
        } for q in sorted(queues, key=lambda q: q["name"])] if isinstance(queues, list) else [],
        "recent": list(hub.recent)[:30],
        "dead_letters": dead,
    }


@router.get("/health")
def health():
    return {"status": "online", "ws_clients": len(hub.clients), "received": hub.received}


@router.get("/system")
def system():
    checks = {}
    try:
        db.one("select 1 as ok")
        checks["postgres"] = True
    except Exception:  # noqa: BLE001
        checks["postgres"] = False
    checks["influxdb"] = influx.ping()
    checks["rabbitmq"] = hub.conn is not None and not hub.conn.is_closed
    last = max((c.get("ts", 0) for c in hub.latest.values()), default=0)
    checks["simulator"] = hub.sim_status.get("online", False) and time.time() - last < 3
    return {
        "checks": checks,
        "last_telemetry_age_s": round(time.time() - last, 1) if last else None,
        "links": [
            {"name": "Documentação da API (Swagger)", "url": "/api/docs"},
            {"name": "RabbitMQ Management", "url": "http://127.0.0.1:15672"},
            {"name": "InfluxDB", "url": "http://127.0.0.1:8086"},
            {"name": "pgAdmin (PostgreSQL)", "url": "http://127.0.0.1:5050"},
        ],
    }
