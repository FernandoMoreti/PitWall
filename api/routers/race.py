"""Pista, estado ao vivo, comandos (Web → IoT) e histórico."""
from __future__ import annotations

import time
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

import db
import influx
from bus import hub
from pitwall_common import envelope, topics
from pitwall_common.track import build

router = APIRouter(prefix="/api", tags=["corrida"])

_track_json = build().to_json()

ALLOWED: dict[str, set | None] = {
    "engine_mode": {"PUSH", "STANDARD", "CONSERVE"},
    "ers_mode": {"HARVEST", "BALANCED", "OVERTAKE"},
    "box": {"SOFT", "MEDIUM", "HARD"},
    "cancel_box": None,
    "cooling": {True, False},
    "fault": {"pu_bearing", "slow_puncture"},
    "repair": None,
    "restart": None,
}


class Command(BaseModel):
    car_id: str
    action: Literal["engine_mode", "ers_mode", "box", "cancel_box", "cooling", "fault", "repair", "restart"]
    value: Any = None


@router.get("/track")
def track():
    return _track_json


@router.get("/state")
def state():
    return {"cars": list(hub.latest.values()), "sim": hub.sim_status, "server_ts": time.time()}


@router.post("/commands")
async def send_command(cmd: Command):
    if not influx.CAR_RE.match(cmd.car_id):
        raise HTTPException(400, "car_id inválido")
    allowed = ALLOWED[cmd.action]
    if allowed is not None and cmd.value not in allowed:
        raise HTTPException(400, f"valor inválido para {cmd.action}")
    msg = envelope.make("command", cmd.car_id, {"action": cmd.action, "value": cmd.value}, "web")
    await hub.publish(topics.rk_command(cmd.car_id), msg)
    await run_in_threadpool(db.audit, "web", f"command.{cmd.action}", cmd.car_id,
                            {"value": cmd.value, "command_id": msg["id"]})
    return {"ok": True, "command_id": msg["id"]}


@router.get("/history")
def history(car_id: str, fields: str = Query(..., description="campos separados por vírgula"),
            minutes: int = 10, every: str = "5s"):
    try:
        return influx.history(car_id, [f.strip() for f in fields.split(",") if f.strip()], minutes, every)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
