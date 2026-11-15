"""PostgreSQL: dispositivos, regras, alertas e auditoria."""
from __future__ import annotations

import json
from contextlib import contextmanager

from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from pitwall_common.config import env

pool = ConnectionPool(env("POSTGRES_DSN"), min_size=1, max_size=8, open=False,
                      kwargs={"autocommit": True, "row_factory": dict_row})


@contextmanager
def conn():
    with pool.connection() as c:
        yield c


def query(sql: str, params: tuple | dict = ()) -> list[dict]:
    with conn() as c:
        return c.execute(sql, params).fetchall()


def one(sql: str, params: tuple | dict = ()) -> dict | None:
    with conn() as c:
        return c.execute(sql, params).fetchone()


def audit(actor: str, action: str, target: str | None, details: dict) -> None:
    with conn() as c:
        c.execute("insert into audit_log (actor, action, target, details) values (%s, %s, %s, %s)",
                  (actor, action, target, json.dumps(details, default=str)))
