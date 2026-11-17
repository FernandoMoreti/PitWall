"""ml-worker: jobs demorados da IA (consome q.jobs.generate e q.jobs.train).

* Gerar: simula a vida inteira de N Power Units (numpy, um bloco por equipamento)
  com as MESMAS fórmulas do simulador ao vivo, ruído, ciclo diário/sazonal,
  leituras faltantes e outliers. Cada leitura leva os rótulos de verdade
  (health e rul_h) — eles ficam só no dataset, nunca nas mensagens ao vivo.
* Treinar: features (pitwall_common.features, o mesmo código da inferência),
  divisão por equipamento, 2 regressões RandomForest (índice de saúde e vida
  útil restante), métricas contra uma base que prevê sempre a média.

O job roda numa thread; o laço principal continua atendendo o RabbitMQ
(heartbeat) e o healthcheck. O progresso fica na tabela jobs do PostgreSQL.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
from pathlib import Path

import joblib
import numpy as np
import psycopg
from psycopg.rows import dict_row
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

from pitwall_common import amqp, envelope, features, topics
from pitwall_common.config import env

logging.basicConfig(level=logging.INFO, format="%(asctime)s [ml-worker] %(message)s")
log = logging.getLogger("ml-worker")

LAB_DIR = Path(env("LAB_DIR", "/data/lab"))
MODELS_DIR = Path(env("MODELS_DIR", "/data/models"))
MAX_READINGS = 5_000_000          # teto para não travar a máquina
RUL_CAP_H = 200.0              # acima disso a PU é tratada como "sem falha prevista"
MODES = ("bearing", "overheat", "oil_leak", "sensor_drift")
DEFAULTS = {"equipments": 100, "days": 14, "sample_min": 1, "fail_pct": 40, "modes": list(MODES),
            "noise": 1.0, "missing_pct": 1.0, "outlier_pct": 0.5, "seed": 42}


# ------------------------------------------------------------------ PostgreSQL
def pg():
    for attempt in range(60):
        try:
            return psycopg.connect(env("POSTGRES_DSN"), autocommit=True, row_factory=dict_row)
        except Exception as exc:  # noqa: BLE001
            log.warning("Postgres indisponível (%s) %d/60", exc, attempt + 1)
            time.sleep(2)
    raise RuntimeError("Postgres indisponível")


class Job:
    def __init__(self, db, job_id: int, kind: str) -> None:
        self.db, self.id, self.kind = db, job_id, kind
        self._last = 0.0

    def progress(self, value: float, note: str = "", force: bool = False) -> None:
        if not force and time.time() - self._last < 0.5:
            return
        self._last = time.time()
        self.db.execute("update jobs set status='running', progress=%s, note=%s where id=%s",
                        (round(min(100.0, value), 1), note, self.id))

    def done(self, result: dict) -> None:
        self.db.execute("update jobs set status='done', progress=100, note='concluído', result=%s, finished_at=now() where id=%s",
                        (json.dumps(result), self.id))
        self.db.execute("insert into audit_log (actor, action, target, details) values (%s,%s,%s,%s)",
                        ("ml-worker", f"{self.kind}.done", f"job:{self.id}", json.dumps({k: result.get(k) for k in ("readings", "version")})))

    def fail(self, exc: Exception) -> None:
        self.db.execute("update jobs set status='error', note=%s, finished_at=now() where id=%s", (str(exc)[:400], self.id))


# ------------------------------------------------------------------ geração
def simulate_equipment(rng: np.random.Generator, p: dict, failing: bool, mode: str | None):
    """Vida de uma PU. Retorna (X (n,5), health, rul_h)."""
    dt_h = p["sample_min"] / 60
    total_h = p["days"] * 24
    noise = p["noise"]
    w0 = rng.uniform(0.02, 0.25)
    if failing:
        # mesma lei do simulador ao vivo: dw/dt = k·(0,4 + w) — o desgaste acelera sozinho até quebrar
        fail_at = rng.uniform(0.35, 1.0) * total_h               # quando a PU quebra
        k = np.log(1.4 / (0.4 + w0)) / fail_at
        n = max(features.WINDOW + 5, int(fail_at / dt_h))
        t = np.arange(n) * dt_h
        wear = (0.4 + w0) * np.exp(k * t) - 0.4
        rul = np.minimum(fail_at - t, RUL_CAP_H)
    else:
        n = int(total_h / dt_h)
        t = np.arange(n) * dt_h
        rate = rng.uniform(0.0002, 0.0012)                         # desgaste lento, por hora
        wear = w0 + rate * t
        rul = np.minimum((1 - wear) / rate, RUL_CAP_H)
    wear = np.clip(wear, 0, 1)
    deg = wear ** 2

    # condições de uso: rotação, acelerador e modo do motor (em blocos de ~1 h)
    rpm = rng.uniform(6500, 12000, n)
    thr = np.clip((rpm - 6000) / 6000 + rng.normal(0, 0.1, n), 0, 1)
    mode_off = np.repeat(rng.choice([-4.0, 0.0, 6.0], size=n // 60 + 1), 60)[:n]
    # ciclo diário (24 h) e sazonal (90 dias) da temperatura ambiente
    ambient = 3 * np.sin(2 * np.pi * t / 24) + 2 * np.sin(2 * np.pi * t / (24 * 90) + rng.uniform(0, 6.28))
    # cada máquina é um pouco diferente: sobreposição entre saudáveis e doentes
    off = rng.normal(0, [0.05, 1.5, 0.12, 1.5])

    engine = 94 + 16 * thr + mode_off + 14 * deg + ambient + off[3] + rng.normal(0, 0.6 * noise, n)
    oil = engine - 4 + 25 * deg + off[1] + rng.normal(0, 0.6 * noise, n)
    press = 5.2 + 0.9 * rpm / 12000 - 2.6 * deg - 0.01 * (oil - 100) + off[2] + rng.normal(0, 0.05 * noise, n)
    vib = 0.6 + 0.5 * rpm / 12000 + 2.8 * deg + off[0] + rng.normal(0, 0.04 * noise, n)

    # o modo de falha muda qual variável sobe mais
    if mode == "bearing":
        vib += 1.2 * deg
    elif mode == "overheat":
        engine += 10 * deg
        oil += 10 * deg
    elif mode == "oil_leak":
        press -= 1.2 * deg
    X = np.column_stack([vib, oil, press, engine, rpm])
    if mode == "sensor_drift":                                     # um sensor deriva com o tempo
        j = rng.integers(0, 4)
        X[:, j] += np.linspace(0, rng.uniform(0.05, 0.15), n) * np.abs(X[:, j]).mean()

    # leituras faltantes e valores absurdos
    X[rng.random(X.shape) < p["missing_pct"] / 100] = np.nan
    out = rng.random(X.shape) < p["outlier_pct"] / 100
    X[out] *= rng.choice([0.3, 3.0], size=int(out.sum()))
    return X.astype(np.float32), (100 * (1 - wear)).astype(np.float32), rul.astype(np.float32)


def generate(job: Job, params: dict) -> dict:
    p = {**DEFAULTS, **{k: v for k, v in params.items() if v is not None}}
    p["equipments"] = int(np.clip(p["equipments"], 2, 2000))
    p["days"] = float(np.clip(p["days"], 1, 365))
    p["sample_min"] = float(np.clip(p["sample_min"], 0.25, 60))
    modes = [m for m in p["modes"] if m in MODES] or ["bearing"]
    per_eq = p["days"] * 24 * 60 / p["sample_min"]
    if p["equipments"] * per_eq > MAX_READINGS:
        p["equipments"] = max(2, int(MAX_READINGS / per_eq))
        log.info("Acima do teto: reduzido para %d equipamentos", p["equipments"])

    rng = np.random.default_rng(int(p["seed"]))
    n_fail = int(round(p["equipments"] * p["fail_pct"] / 100))
    failing = np.zeros(p["equipments"], bool)
    failing[rng.choice(p["equipments"], n_fail, replace=False)] = True
    eq_mode = [str(rng.choice(modes)) if f else ("sensor_drift" if "sensor_drift" in modes and rng.random() < 0.1 else None)
               for f in failing]

    Xs, hs, rs, ids = [], [], [], []
    for e in range(p["equipments"]):
        X, h, r = simulate_equipment(rng, p, bool(failing[e]), eq_mode[e])
        Xs.append(X); hs.append(h); rs.append(r); ids.append(np.full(len(X), e, np.int32))
        job.progress(90 * (e + 1) / p["equipments"], f"equipamento {e + 1}/{p['equipments']}")

    X = np.concatenate(Xs); health = np.concatenate(hs); rul = np.concatenate(rs); eq = np.concatenate(ids)
    LAB_DIR.mkdir(parents=True, exist_ok=True)
    tmp = LAB_DIR / "dataset.tmp.npz"
    np.savez(tmp, X=X, health=health, rul=rul, eq=eq, failing=failing)
    os.replace(tmp, LAB_DIR / "dataset.npz")

    job.progress(94, "gravando amostra no InfluxDB (bucket lab)", force=True)
    sample = write_lab_sample(X, health, rul, eq, failing, p)

    meta = {"params": p, "readings": int(len(X)), "equipments": p["equipments"], "failing": int(n_fail),
            "modes": {m: eq_mode.count(m) for m in MODES}, "signals": list(features.SIGNALS),
            "influx_sample_points": sample, "created_at": time.time()}
    (LAB_DIR / "dataset.json").write_text(json.dumps(meta), encoding="utf-8")
    log.info("Dataset: %d leituras de %d PUs (%d falham)", len(X), p["equipments"], n_fail)
    return meta


def write_lab_sample(X, health, rul, eq, failing, p) -> int:
    """Amostra (~5 000 pontos) no bucket separado 'lab' — nunca mistura com o ao vivo."""
    try:
        from influxdb_client import InfluxDBClient, Point, WritePrecision
        from influxdb_client.client.write_api import SYNCHRONOUS
        client = InfluxDBClient(url=env("INFLUXDB_URL", "http://influxdb:8086"), token=env("INFLUXDB_TOKEN"),
                                org=env("INFLUXDB_ORG", "pitwall"))
        buckets = client.buckets_api()
        if not buckets.find_bucket_by_name("lab"):
            org = client.organizations_api().find_organizations(org=env("INFLUXDB_ORG", "pitwall"))[0]
            buckets.create_bucket(bucket_name="lab", org_id=org.id)
        picks = list(np.where(failing)[0][:3]) + list(np.where(~failing)[0][:2])
        now_ms = int(time.time() * 1000)
        step_ms = int(p["sample_min"] * 60_000)
        points = []
        for e in picks:
            rows = np.where(eq == e)[0]
            rows = rows[:: max(1, len(rows) // 1000)]
            start = now_ms - int(len(np.where(eq == e)[0]) * step_ms)
            for k, i in enumerate(rows):
                pt = Point("lab_readings").tag("equipment", f"PU-{e:04d}").tag("failing", str(bool(failing[e])).lower())
                for j, name in enumerate(features.SIGNALS):
                    if not np.isnan(X[i, j]):
                        pt.field(name, float(X[i, j]))
                pt.field("health", float(health[i])).field("rul_h", float(rul[i]))
                points.append(pt.time(start + int((i - rows[0]) * step_ms), WritePrecision.MS))
        client.write_api(write_options=SYNCHRONOUS).write(bucket="lab", record=points)
        client.close()
        return len(points)
    except Exception as exc:  # noqa: BLE001
        log.warning("Amostra no InfluxDB falhou (o dataset em disco está ok): %s", exc)
        return 0


# ------------------------------------------------------------------ treino
def metrics(y, pred) -> dict:
    return {"mae": round(float(mean_absolute_error(y, pred)), 3),
            "rmse": round(float(np.sqrt(mean_squared_error(y, pred))), 3),
            "r2": round(float(r2_score(y, pred)), 4)}


def train(job: Job, params: dict) -> dict:
    path = LAB_DIR / "dataset.npz"
    if not path.exists():
        raise RuntimeError("Nenhum dataset. Gere os dados no Laboratório primeiro.")
    seed = int(params.get("seed") or 42)
    rng = np.random.default_rng(seed)
    job.progress(5, "carregando dataset", force=True)
    d = np.load(path)
    X, health, rul, eq = d["X"], d["health"], d["rul"], d["eq"]

    # features por equipamento (janela só do passado — mesmo código da inferência)
    job.progress(10, "calculando features", force=True)
    order = np.argsort(eq, kind="stable")
    X, health, rul, eq = X[order], health[order], rul[order], eq[order]
    bounds = np.flatnonzero(np.diff(eq)) + 1
    F = np.concatenate([features.build(chunk) for chunk in np.split(X, bounds)])

    # divisão por equipamento (nunca por linha): 70% treino, 15% validação, 15% teste
    ids = rng.permutation(np.unique(eq))
    n_tr, n_va = int(len(ids) * 0.7), int(len(ids) * 0.15)
    split = {"train": ids[:n_tr], "val": ids[n_tr:n_tr + n_va], "test": ids[n_tr + n_va:]}
    mask = {k: np.isin(eq, v) for k, v in split.items()}

    def sample(m: np.ndarray, cap: int) -> np.ndarray:
        idx = np.flatnonzero(m)
        return rng.choice(idx, cap, replace=False) if len(idx) > cap else idx

    tr, va, te = sample(mask["train"], 200_000), sample(mask["val"], 60_000), sample(mask["test"], 60_000)
    models, report = {}, {}
    targets = {"health": (health, "Índice de saúde (0–100)"), "rul": (rul, "Vida útil restante (h)")}
    for k, (name, (y, label)) in enumerate(targets.items()):
        job.progress(30 + k * 35, f"treinando {label}", force=True)
        model = RandomForestRegressor(n_estimators=60, max_depth=12, min_samples_leaf=5, n_jobs=-1, random_state=seed)
        model.fit(F[tr], y[tr])
        pred_te = model.predict(F[te])
        base = np.full(len(te), float(y[tr].mean()))               # base simples: sempre a média
        m_model, m_base = metrics(y[te], pred_te), metrics(y[te], base)
        pick = rng.choice(len(te), min(300, len(te)), replace=False)
        imp = sorted(zip(features.NAMES, model.feature_importances_), key=lambda x: -x[1])
        report[name] = {
            "label": label,
            "test": m_model, "baseline": m_base, "val": metrics(y[va], model.predict(F[va])),
            "beats_baseline": m_model["mae"] < m_base["mae"] and m_model["r2"] > m_base["r2"],
            "importance": [{"feature": f, "value": round(float(v), 4)} for f, v in imp],
            "scatter": [[round(float(a), 2), round(float(b), 2)] for a, b in zip(y[te][pick], pred_te[pick])],
        }
        models[name] = model

    job.progress(95, "salvando modelos", force=True)
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    version = 1 + max([int(p.name[1:]) for p in MODELS_DIR.glob("v*") if p.name[1:].isdigit()], default=0)
    vdir = MODELS_DIR / f"v{version}"
    vdir.mkdir()
    for name, model in models.items():
        joblib.dump(model, vdir / f"{name}.joblib", compress=3)
    ds_meta = json.loads((LAB_DIR / "dataset.json").read_text(encoding="utf-8")) if (LAB_DIR / "dataset.json").exists() else {}
    meta = {"version": version, "created_at": time.time(), "algorithm": "RandomForestRegressor(60 árvores, prof. 12)",
            "features": features.NAMES, "window": features.WINDOW, "signals": list(features.SIGNALS),
            "rows": {"train": int(len(tr)), "val": int(len(va)), "test": int(len(te)), "total": int(len(F))},
            "equipments": {k: int(len(v)) for k, v in split.items()},
            "dataset": {k: ds_meta.get(k) for k in ("readings", "equipments", "failing", "params")},
            "models": report}
    (vdir / "meta.json").write_text(json.dumps(meta), encoding="utf-8")
    tmp = MODELS_DIR / "current.tmp"
    tmp.write_text(json.dumps({"version": version}), encoding="utf-8")
    os.replace(tmp, MODELS_DIR / "current.json")                  # troca atômica: a inferência recarrega sozinha
    log.info("Modelos v%d salvos — saúde R²=%.3f, RUL R²=%.3f", version,
             report["health"]["test"]["r2"], report["rul"]["test"]["r2"])
    return {"version": version, "health": report["health"]["test"], "rul": report["rul"]["test"]}


# ------------------------------------------------------------------ laço principal
def main() -> None:
    db = pg()
    db.execute("update jobs set status='error', note='interrompido (serviço reiniciou)', finished_at=now() "
               "where status in ('queued','running')")
    pending: list[tuple[str, dict]] = []
    while True:
        conn = amqp.connect("RABBITMQ_ML_USER", "RABBITMQ_ML_PASSWORD")
        ch = conn.channel()
        ch.basic_qos(prefetch_count=1)

        def on_msg(chan, method, props, body, kind):
            try:
                msg = envelope.loads(body)
                pending.append((kind, msg["payload"]))
                chan.basic_ack(method.delivery_tag)        # o estado do job fica no PostgreSQL
            except Exception as exc:  # noqa: BLE001
                log.warning("Job inválido -> DLQ: %s", exc)
                chan.basic_nack(method.delivery_tag, requeue=False)

        ch.basic_consume(topics.Q_JOB_GENERATE, lambda c, m, p, b: on_msg(c, m, p, b, "generate"))
        ch.basic_consume(topics.Q_JOB_TRAIN, lambda c, m, p, b: on_msg(c, m, p, b, "train"))
        log.info("Aguardando jobs em %s e %s", topics.Q_JOB_GENERATE, topics.Q_JOB_TRAIN)
        worker: threading.Thread | None = None
        try:
            while True:
                conn.process_data_events(time_limit=0.5)
                amqp.beat()
                if pending and (worker is None or not worker.is_alive()):
                    kind, payload = pending.pop(0)
                    worker = threading.Thread(target=run_job, args=(kind, payload), daemon=True)
                    worker.start()
        except Exception as exc:  # noqa: BLE001
            log.error("Conexão perdida (%s), reconectando...", exc)
            time.sleep(2)


def run_job(kind: str, payload: dict) -> None:
    db = pg()
    job = Job(db, int(payload["job_id"]), f"job.{kind}")
    t0 = time.time()
    try:
        job.progress(1, "iniciando", force=True)
        result = (generate if kind == "generate" else train)(job, payload.get("params") or {})
        result["seconds"] = round(time.time() - t0, 1)
        job.done(result)
        log.info("Job %d (%s) concluído em %.1fs", job.id, kind, time.time() - t0)
    except Exception as exc:  # noqa: BLE001
        log.exception("Job %d (%s) falhou", job.id, kind)
        job.fail(exc)
    finally:
        db.close()


if __name__ == "__main__":
    main()
