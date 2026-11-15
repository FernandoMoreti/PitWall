"""Formato único das mensagens: {id, ts, type, device, source, payload}.

Toda mensagem que trafega no MQTT e no RabbitMQ usa este envelope.
"""
import json
import time
import uuid
from typing import Any

REQUIRED = ("id", "ts", "type", "device", "payload")


def make(type_: str, device: str, payload: dict[str, Any], source: str) -> dict[str, Any]:
    return {
        "id": uuid.uuid4().hex,
        "ts": time.time(),
        "type": type_,
        "device": device,
        "source": source,
        "payload": payload,
    }


def dumps(msg: dict[str, Any]) -> bytes:
    return json.dumps(msg, separators=(",", ":")).encode("utf-8")


def loads(raw: bytes | str) -> dict[str, Any]:
    msg = json.loads(raw)
    if not isinstance(msg, dict) or any(k not in msg for k in REQUIRED):
        raise ValueError("mensagem fora do envelope padrão")
    if not isinstance(msg["payload"], dict):
        raise ValueError("payload precisa ser um objeto")
    return msg
