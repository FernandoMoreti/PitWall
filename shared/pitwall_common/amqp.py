"""Helpers de RabbitMQ (pika, bloqueante) para gateway e workers.

As filas, exchanges e bindings são declarados pelo definitions.json do RabbitMQ;
os serviços só publicam/consomem (usuários sem permissão de configure).
"""
import logging
import os
import time
from pathlib import Path

import pika

from .config import env, env_int

log = logging.getLogger("amqp")
logging.getLogger("pika").setLevel(logging.WARNING)

HEARTBEAT_FILE = Path("/tmp/heartbeat")


def connect(user_env: str, password_env: str, retries: int = 90) -> pika.BlockingConnection:
    params = pika.ConnectionParameters(
        host=env("RABBITMQ_HOST", "rabbitmq"),
        port=env_int("RABBITMQ_PORT", 5672),
        virtual_host=env("RABBITMQ_VHOST", "pitwall"),
        credentials=pika.PlainCredentials(env(user_env), env(password_env)),
        heartbeat=30,
        blocked_connection_timeout=60,
    )
    for attempt in range(1, retries + 1):
        try:
            conn = pika.BlockingConnection(params)
            log.info("Conectado ao RabbitMQ como %s", os.getenv(user_env))
            return conn
        except Exception as exc:  # noqa: BLE001
            log.warning("RabbitMQ indisponível (%s), tentativa %d/%d", exc, attempt, retries)
            time.sleep(2)
    raise RuntimeError("não foi possível conectar ao RabbitMQ")


def json_props() -> pika.BasicProperties:
    return pika.BasicProperties(content_type="application/json", delivery_mode=1)


def beat() -> None:
    """Atualiza o arquivo usado pelo healthcheck do container."""
    try:
        HEARTBEAT_FILE.touch()
    except OSError:
        pass
