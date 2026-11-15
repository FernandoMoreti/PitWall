"""API PITWALL — FastAPI (REST + WebSocket).

Mantém o lifespan/CORS do backend do 1º bimestre; o consumo MQTT direto foi
substituído pelo RabbitMQ (q.ws) e o polling de /datas pelo WebSocket.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

import db
from bus import hub
from routers import ops, race, registry

logging.basicConfig(level=logging.INFO, format="%(asctime)s [api] %(message)s")


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.pool.open(wait=True, timeout=120)
    await hub.start()
    yield
    await hub.stop()
    db.pool.close()


app = FastAPI(
    title="PITWALL — Telemetria F1",
    description="REST + WebSocket do gêmeo digital de F1 (IoT → MQTT → RabbitMQ → FastAPI → Web 3D)",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
)

app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_methods=["*"], allow_headers=["*"])

app.include_router(race.router)
app.include_router(registry.router)
app.include_router(ops.router)


@app.post("/api/ws/ticket", tags=["tempo real"])
def ws_ticket():
    """Ticket curto e de uso único para abrir o WebSocket (nada de token na URL)."""
    return {"ticket": hub.new_ticket(), "ttl": 30}


@app.websocket("/ws")
async def websocket(ws: WebSocket):
    if not hub.use_ticket(ws.query_params.get("ticket")):
        await ws.close(code=4401)
        return
    await ws.accept()
    hub.clients.add(ws)
    try:
        await ws.send_json(hub.snapshot())
        while True:
            await ws.receive_text()   # o cliente só escuta; mantém a conexão viva
    except WebSocketDisconnect:
        pass
    finally:
        hub.clients.discard(ws)
