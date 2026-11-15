"""Gera os segredos do PITWALL (nada disso vai para o Git).

  python scripts/gen_secrets.py          # cria .env e infra/rabbitmq/definitions.json
  python scripts/gen_secrets.py --force  # recria tudo (apaga os volumes antes: docker compose down -v)

* .env                           senhas/tokens aleatórios de todos os serviços
* infra/rabbitmq/definitions.json  vhost, exchanges, filas, DLQ, bindings e um usuário por
                                   serviço, com hash de senha (sem guest)
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENV = ROOT / ".env"
DEFS = ROOT / "infra" / "rabbitmq" / "definitions.json"
VHOST = "pitwall"


def pw(n: int = 24) -> str:
    return secrets.token_urlsafe(n)


def rabbit_hash(password: str) -> str:
    salt = os.urandom(4)
    return base64.b64encode(salt + hashlib.sha256(salt + password.encode()).digest()).decode()


def read_env() -> dict[str, str]:
    out = {}
    for line in ENV.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def build_env() -> dict[str, str]:
    return {
        "POSTGRES_USER": "pitwall",
        "POSTGRES_PASSWORD": pw(),
        "POSTGRES_DB": "pitwall",
        "PGADMIN_EMAIL": "admin@example.com",
        "PGADMIN_PASSWORD": pw(12),
        "INFLUXDB_USER": "pitwall",
        "INFLUXDB_PASSWORD": pw(),
        "INFLUXDB_ORG": "pitwall",
        "INFLUXDB_BUCKET": "telemetry",
        "INFLUXDB_TOKEN": pw(40),
        "MQTT_SIM_PASSWORD": pw(),
        "MQTT_GATEWAY_PASSWORD": pw(),
        "MQTT_MONITOR_PASSWORD": pw(),
        "RABBITMQ_ADMIN_USER": "pw_admin",
        "RABBITMQ_ADMIN_PASSWORD": pw(),
        "RABBITMQ_GATEWAY_USER": "pw_gateway",
        "RABBITMQ_GATEWAY_PASSWORD": pw(),
        "RABBITMQ_WRITER_USER": "pw_writer",
        "RABBITMQ_WRITER_PASSWORD": pw(),
        "RABBITMQ_RULES_USER": "pw_rules",
        "RABBITMQ_RULES_PASSWORD": pw(),
        "RABBITMQ_API_USER": "pw_api",
        "RABBITMQ_API_PASSWORD": pw(),
        "SIM_CONSUMABLE_MULT": "3",
        "SIM_TIME_SCALE": "1",
        "SIM_SEED": "42",
    }


def build_definitions(e: dict[str, str]) -> dict:
    def user(name: str, password: str, tags: list[str]) -> dict:
        return {"name": name, "password_hash": rabbit_hash(password),
                "hashing_algorithm": "rabbit_password_hashing_sha256", "tags": tags, "limits": {}}

    def perm(name: str, conf: str, write: str, read: str) -> dict:
        return {"user": name, "vhost": VHOST, "configure": conf, "write": write, "read": read}

    def queue(name: str, **args) -> dict:
        return {"name": name, "vhost": VHOST, "durable": True, "auto_delete": False, "arguments": args}

    def bind(queue_name: str, key: str, source: str = "f1") -> dict:
        return {"source": source, "vhost": VHOST, "destination": queue_name, "destination_type": "queue",
                "routing_key": key, "arguments": {}}

    dlx = {"x-dead-letter-exchange": "f1.dlx"}
    return {
        "rabbit_version": "3.13.7",
        "users": [
            user(e["RABBITMQ_ADMIN_USER"], e["RABBITMQ_ADMIN_PASSWORD"], ["administrator"]),
            user(e["RABBITMQ_GATEWAY_USER"], e["RABBITMQ_GATEWAY_PASSWORD"], []),
            user(e["RABBITMQ_WRITER_USER"], e["RABBITMQ_WRITER_PASSWORD"], []),
            user(e["RABBITMQ_RULES_USER"], e["RABBITMQ_RULES_PASSWORD"], []),
            # monitoring: o backend lê a API de gerenciamento para a página Mensageria
            user(e["RABBITMQ_API_USER"], e["RABBITMQ_API_PASSWORD"], ["monitoring"]),
        ],
        "vhosts": [{"name": VHOST}],
        "permissions": [
            perm(e["RABBITMQ_ADMIN_USER"], ".*", ".*", ".*"),
            perm(e["RABBITMQ_GATEWAY_USER"], "^$", "^f1$", r"^q\.commands$"),
            perm(e["RABBITMQ_WRITER_USER"], "^$", "^$", r"^q\.influx$"),
            perm(e["RABBITMQ_RULES_USER"], "^$", "^f1$", r"^q\.rules$"),
            perm(e["RABBITMQ_API_USER"], "^$", "^f1$", r"^q\.(ws|dead)$"),
        ],
        "exchanges": [
            {"name": "f1", "vhost": VHOST, "type": "topic", "durable": True, "auto_delete": False,
             "internal": False, "arguments": {}},
            {"name": "f1.dlx", "vhost": VHOST, "type": "fanout", "durable": True, "auto_delete": False,
             "internal": False, "arguments": {}},
        ],
        "queues": [
            queue("q.influx", **dlx, **{"x-max-length": 300000}),
            queue("q.rules", **dlx, **{"x-max-length": 100000}),
            queue("q.ws", **{"x-max-length": 2000}),
            queue("q.commands", **dlx, **{"x-message-ttl": 60000}),
            queue("q.inference", **{"x-max-length": 5000}),
            queue("q.jobs.generate", **dlx),
            queue("q.jobs.train", **dlx),
            queue("q.dead", **{"x-max-length": 10000}),
        ],
        "bindings": [
            bind("q.influx", "telemetry.#"), bind("q.influx", "event.#"),
            bind("q.rules", "telemetry.#"),
            bind("q.ws", "telemetry.#"), bind("q.ws", "event.#"), bind("q.ws", "alert.#"), bind("q.ws", "command.#"),
            bind("q.commands", "command.#"),
            bind("q.inference", "telemetry.#"),
            bind("q.jobs.generate", "job.generate"), bind("q.jobs.train", "job.train"),
            bind("q.dead", "", source="f1.dlx"),
        ],
    }


def main() -> None:
    force = "--force" in sys.argv
    if ENV.exists() and not force:
        print(f".env já existe — reaproveitando ({ENV}). Use --force para recriar.")
        e = read_env()
    else:
        e = build_env()
        ENV.write_text("# Gerado por scripts/gen_secrets.py — NÃO versionar\n"
                       + "\n".join(f"{k}={v}" for k, v in e.items()) + "\n", encoding="utf-8")
        print(f"Criado {ENV}")
    DEFS.write_text(json.dumps(build_definitions(e), indent=2), encoding="utf-8")
    print(f"Criado {DEFS}")
    print("\nPronto. Agora: docker compose up --build")


if __name__ == "__main__":
    main()
