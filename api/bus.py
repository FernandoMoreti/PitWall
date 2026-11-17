"""Ponte RabbitMQ → WebSocket e publicação de comandos.

* Consome q.ws (telemetria, eventos, alertas, comandos e previsões da IA) e mantém o último
  estado de cada carro.
* A cada 100 ms envia aos navegadores um lote com os carros atualizados
  (eventos/alertas vão na hora). O 3D lê esse estado no loop de animação.
* Publica comandos em command.<carro> (q.commands → gateway → MQTT).
"""
from __future__ import annotations

import asyncio
import json
import logging
import secrets
import time
from collections import deque

import aio_pika
from fastapi import WebSocket

from pitwall_common import envelope, topics
from pitwall_common.config import env, env_int

log = logging.getLogger("api.bus")

TICKET_TTL = 30


class Hub:
    def __init__(self) -> None:
        self.clients: set[WebSocket] = set()
        self.latest: dict[str, dict] = {}       # car_id -> {"ts":..., **payload}
        self.predictions: dict[str, dict] = {}  # car_id -> última previsão da IA
        self.dirty: set[str] = set()
        self.sim_status: dict = {"online": False, "ts": 0}
        self.recent: deque = deque(maxlen=60)
        self.tickets: dict[str, float] = {}
        self.received = 0
        self.conn: aio_pika.abc.AbstractRobustConnection | None = None
        self.exchange: aio_pika.abc.AbstractExchange | None = None
        self._tasks: list[asyncio.Task] = []

    # ------------------------------------------------------------ tickets WS
    def new_ticket(self) -> str:
        now = time.time()
        self.tickets = {t: exp for t, exp in self.tickets.items() if exp > now}
        ticket = secrets.token_urlsafe(24)
        self.tickets[ticket] = now + TICKET_TTL
        return ticket

    def use_ticket(self, ticket: str | None) -> bool:
        exp = self.tickets.pop(ticket or "", 0)
        return exp > time.time()

    # ------------------------------------------------------------ RabbitMQ
    async def start(self) -> None:
        url = "amqp://{u}:{p}@{h}:{port}/{v}".format(
            u=env("RABBITMQ_API_USER"), p=env("RABBITMQ_API_PASSWORD"), h=env("RABBITMQ_HOST", "rabbitmq"),
            port=env_int("RABBITMQ_PORT", 5672), v=env("RABBITMQ_VHOST", "pitwall"))
        for attempt in range(90):
            try:
                self.conn = await aio_pika.connect_robust(url)
                break
            except Exception as exc:  # noqa: BLE001
                log.warning("RabbitMQ indisponível (%s) %d/90", exc, attempt + 1)
                await asyncio.sleep(2)
        if not self.conn:
            raise RuntimeError("RabbitMQ indisponível")
        channel = await self.conn.channel()
        await channel.set_qos(prefetch_count=500)
        self.exchange = await channel.get_exchange(topics.EXCHANGE, ensure=False)
        queue = await channel.get_queue(topics.Q_WS, ensure=False)
        await queue.consume(self._on_message, no_ack=True)
        self._tasks = [asyncio.create_task(self._flusher()), asyncio.create_task(self._pinger())]
        log.info("Consumindo %s", topics.Q_WS)

    async def stop(self) -> None:
        for t in self._tasks:
            t.cancel()
        if self.conn:
            await self.conn.close()

    async def publish(self, routing_key: str, msg: dict) -> None:
        if not self.exchange:
            raise RuntimeError("barramento indisponível")
        await self.exchange.publish(
            aio_pika.Message(envelope.dumps(msg), content_type="application/json"), routing_key=routing_key)

    async def _on_message(self, message: aio_pika.abc.AbstractIncomingMessage) -> None:
        try:
            msg = envelope.loads(message.body)
        except ValueError:
            return
        self.received += 1
        rk = message.routing_key or ""
        kind = msg["type"]
        if (kind not in ("telemetry", "prediction")) or self.received % 25 == 0:
            self.recent.appendleft({"rk": rk, "type": kind, "device": msg["device"], "ts": msg["ts"],
                                    "source": msg.get("source"), "size": len(message.body),
                                    "preview": json.dumps(msg["payload"])[:160]})
        if kind == "telemetry":
            self.latest[msg["device"]] = {"ts": msg["ts"], **msg["payload"]}
            self.dirty.add(msg["device"])
            return
        if kind == "prediction":
            self.predictions[msg["device"]] = {"ts": msg["ts"], "car_id": msg["device"], **msg["payload"]}
        if kind == "event" and msg["payload"].get("kind") == "sim_status":
            self.sim_status = {"online": bool(msg["payload"].get("online")), "ts": msg["ts"]}
        await self.broadcast({"t": kind, "msg": msg})

    # ------------------------------------------------------------ WebSocket
    async def _flusher(self) -> None:
        while True:
            await asyncio.sleep(0.1)
            if not self.dirty or not self.clients:
                self.dirty.clear()
                continue
            items = [self.latest[c] for c in self.dirty if c in self.latest]
            self.dirty.clear()
            await self.broadcast({"t": "telemetry", "items": items, "server_ts": time.time()})

    async def _pinger(self) -> None:
        while True:
            await asyncio.sleep(3)
            await self.broadcast({"t": "ping", "server_ts": time.time(), "sim": self.sim_status})

    async def broadcast(self, data: dict) -> None:
        if not self.clients:
            return
        text = json.dumps(data, separators=(",", ":"))
        dead = []
        for ws in list(self.clients):
            try:
                await asyncio.wait_for(ws.send_text(text), timeout=2)
            except Exception:  # noqa: BLE001
                dead.append(ws)
        for ws in dead:
            self.clients.discard(ws)

    def snapshot(self) -> dict:
        return {"t": "hello", "cars": list(self.latest.values()), "predictions": list(self.predictions.values()),
                "sim": self.sim_status, "server_ts": time.time()}


hub = Hub()
