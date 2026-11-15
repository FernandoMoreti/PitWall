"""Cadastro de dispositivos, regras, alertas e auditoria (PostgreSQL)."""
from __future__ import annotations

import json
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

import db

router = APIRouter(prefix="/api", tags=["cadastro"])

DEVICE_COLS = ("kind", "name", "car_id", "component", "field", "unit", "normal_min", "normal_max",
               "crit_min", "crit_max", "control", "metadata", "enabled")


class DeviceIn(BaseModel):
    id: str = Field(pattern=r"^[A-Za-z0-9_.\-]{2,64}$")
    kind: Literal["car", "equipment", "sensor", "actuator"]
    name: str = Field(min_length=1, max_length=120)
    car_id: str | None = None
    component: str | None = None
    field: str | None = None
    unit: str | None = None
    normal_min: float | None = None
    normal_max: float | None = None
    crit_min: float | None = None
    crit_max: float | None = None
    control: Literal["web", "auto", "rule"] | None = None
    metadata: dict = {}
    enabled: bool = True


class DevicePatch(BaseModel):
    name: str | None = None
    component: str | None = None
    unit: str | None = None
    normal_min: float | None = None
    normal_max: float | None = None
    crit_min: float | None = None
    crit_max: float | None = None
    enabled: bool | None = None


class RulePatch(BaseModel):
    threshold: float | None = None
    clear_threshold: float | None = None
    on_count: int | None = Field(default=None, ge=1, le=100)
    off_count: int | None = Field(default=None, ge=1, le=500)
    enabled: bool | None = None


@router.get("/devices")
def list_devices(car_id: str | None = None, kind: str | None = None):
    sql = "select * from devices where (%(car)s::text is null or car_id = %(car)s) and (%(kind)s::text is null or kind = %(kind)s) order by car_id, kind, id"
    return db.query(sql, {"car": car_id, "kind": kind})


@router.get("/devices/{device_id}")
def get_device(device_id: str):
    row = db.one("select * from devices where id = %s", (device_id,))
    if not row:
        raise HTTPException(404, "dispositivo não encontrado")
    return row


@router.post("/devices", status_code=201)
def create_device(dev: DeviceIn):
    if db.one("select 1 from devices where id = %s", (dev.id,)):
        raise HTTPException(409, "id já cadastrado")
    data = dev.model_dump()
    data["metadata"] = json.dumps(data["metadata"])
    cols = ("id",) + DEVICE_COLS
    row = db.one(f"insert into devices ({', '.join(cols)}) values ({', '.join('%(' + c + ')s' for c in cols)}) returning *", data)
    db.audit("web", "device.create", dev.id, {"kind": dev.kind})
    return row


@router.patch("/devices/{device_id}")
def update_device(device_id: str, patch: DevicePatch):
    data = patch.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(400, "nada para atualizar")
    sets = ", ".join(f"{k} = %({k})s" for k in data)
    row = db.one(f"update devices set {sets}, updated_at = now() where id = %(id)s returning *", {**data, "id": device_id})
    if not row:
        raise HTTPException(404, "dispositivo não encontrado")
    db.audit("web", "device.update", device_id, data)
    return row


@router.delete("/devices/{device_id}", status_code=204)
def delete_device(device_id: str):
    row = db.one("delete from devices where id = %s returning id", (device_id,))
    if not row:
        raise HTTPException(404, "dispositivo não encontrado")
    db.audit("web", "device.delete", device_id, {})


@router.get("/rules")
def list_rules():
    return db.query("select * from rules order by id")


@router.patch("/rules/{rule_id}")
def update_rule(rule_id: int, patch: RulePatch):
    data = patch.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(400, "nada para atualizar")
    sets = ", ".join(f"{k} = %({k})s" for k in data)
    row = db.one(f"update rules set {sets} where id = %(id)s returning *", {**data, "id": rule_id})
    if not row:
        raise HTTPException(404, "regra não encontrada")
    db.audit("web", "rule.update", str(rule_id), data)
    return row


@router.get("/alerts")
def list_alerts(open_only: bool = False, car_id: str | None = None, limit: int = 100):
    return db.query(
        "select * from alerts where (not %(open)s or cleared_at is null) and (%(car)s::text is null or car_id = %(car)s) "
        "order by raised_at desc limit %(limit)s",
        {"open": open_only, "car": car_id, "limit": max(1, min(limit, 500))})


@router.get("/audit")
def list_audit(limit: int = 100):
    return db.query("select * from audit_log order by ts desc limit %s", (max(1, min(limit, 500)),))
