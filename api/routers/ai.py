"""IA: Laboratório de Dados, Treino, Insights e Assistente (LLM local via Ollama).

* Os jobs demorados (gerar dados, treinar) só são enfileirados aqui: a API grava
  o job no PostgreSQL, publica em job.generate/job.train e responde na hora.
* O assistente recebe um resumo pronto dos dados (o LLM nunca acessa os bancos)
  e responde em streaming. A saída é texto não confiável: o frontend renderiza
  Markdown sem HTML e sem imagens.
"""
from __future__ import annotations

import json
import time
from collections import defaultdict, deque
from pathlib import Path

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

import db
from bus import hub
from pitwall_common import envelope, topics
from pitwall_common.config import env

router = APIRouter(prefix="/api", tags=["IA"])

LAB_DIR = Path(env("LAB_DIR", "/data/lab"))
MODELS_DIR = Path(env("MODELS_DIR", "/data/models"))
OLLAMA = env("OLLAMA_URL", "http://ollama:11434")
MODEL = env("OLLAMA_MODEL", "qwen2.5:1.5b")
RATE_PER_MIN = 6
_asked: dict[str, deque] = defaultdict(lambda: deque(maxlen=RATE_PER_MIN))


def _read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def current_model() -> dict | None:
    cur = _read_json(MODELS_DIR / "current.json")
    return _read_json(MODELS_DIR / f"v{cur['version']}" / "meta.json") if cur else None


# ------------------------------------------------------------------ Laboratório / Treino
class GenerateParams(BaseModel):
    equipments: int = Field(100, ge=2, le=2000, description="número de Power Units simuladas")
    days: float = Field(14, ge=1, le=365, description="período simulado em dias")
    sample_min: float = Field(1, ge=0.25, le=60, description="minutos entre leituras")
    fail_pct: float = Field(40, ge=0, le=100, description="% de equipamentos que falham")
    modes: list[str] = Field(default_factory=lambda: ["bearing", "overheat", "oil_leak", "sensor_drift"])
    noise: float = Field(1.0, ge=0, le=5, description="multiplicador do ruído")
    missing_pct: float = Field(1.0, ge=0, le=30)
    outlier_pct: float = Field(0.5, ge=0, le=10)
    seed: int = 42


class TrainParams(BaseModel):
    seed: int = 42


async def _enqueue(kind: str, params: dict) -> dict:
    busy = await run_in_threadpool(db.one, "select id from jobs where status in ('queued','running') limit 1")
    if busy:
        raise HTTPException(409, f"Já existe um job em andamento (#{busy['id']}).")
    row = await run_in_threadpool(db.one, "insert into jobs (kind, params) values (%s, %s) returning id",
                                  (kind, json.dumps(params)))
    await hub.publish(topics.RK_JOB_GENERATE if kind == "generate" else topics.RK_JOB_TRAIN,
                      envelope.make("job", "lab", {"job_id": row["id"], "params": params}, "api"))
    await run_in_threadpool(db.audit, "web", f"job.{kind}", f"job:{row['id']}", params)
    return {"job_id": row["id"], "status": "queued"}


@router.post("/lab/generate", status_code=202)
async def lab_generate(p: GenerateParams):
    """Enfileira a geração de dados sintéticos (q.jobs.generate)."""
    est = p.equipments * p.days * 24 * 60 / p.sample_min
    params = p.model_dump()
    params["estimated_readings"] = int(est)
    return await _enqueue("generate", params)


@router.post("/lab/train", status_code=202)
async def lab_train(p: TrainParams):
    """Enfileira o treino dos 2 modelos de regressão (q.jobs.train)."""
    if not (LAB_DIR / "dataset.npz").exists():
        raise HTTPException(400, "Nenhum dataset. Gere os dados no Laboratório primeiro.")
    return await _enqueue("train", p.model_dump())


@router.get("/lab/jobs")
def lab_jobs(limit: int = 10):
    return db.query("select * from jobs order by id desc limit %s", (min(limit, 50),))


@router.get("/lab/dataset")
def lab_dataset():
    return _read_json(LAB_DIR / "dataset.json") or {}


@router.get("/models/current")
def models_current():
    meta = current_model()
    versions = sorted(int(p.name[1:]) for p in MODELS_DIR.glob("v*") if p.name[1:].isdigit()) if MODELS_DIR.exists() else []
    return {"model": meta, "versions": versions}


# ------------------------------------------------------------------ Insights
@router.get("/insights")
def insights():
    meta = current_model()
    return {
        "model_version": meta["version"] if meta else None,
        "predictions": list(hub.predictions.values()),
        "alerts": db.query("select id, car_id, field, severity, message, value, raised_at from alerts "
                           "where cleared_at is null order by raised_at desc limit 50"),
    }


# ------------------------------------------------------------------ Assistente (LLM local)
ARCH = (
    "Arquitetura do PITWALL: simulador Python (6 carros de F1, 10 Hz) publica telemetria via MQTT no Mosquitto; "
    "o gateway republica no RabbitMQ (exchange topic 'f1'); filas: q.influx (grava no InfluxDB, séries temporais), "
    "q.rules (regras -> atuador automático de resfriamento, alertas e auditoria no PostgreSQL), q.ws (API FastAPI -> "
    "WebSocket -> telas Vue 3 + Three.js), q.commands (comandos da Web voltam ao carro via MQTT), q.inference "
    "(IA ao vivo), q.jobs.generate e q.jobs.train (jobs de dados e treino) e q.dead (DLQ). A IA usa 2 regressões "
    "RandomForest (scikit-learn) treinadas com dados sintéticos: índice de saúde da Power Unit (0-100) e vida útil "
    "restante em horas. Alertas preditivos usam histerese (3 previsões abaixo de 50 disparam, 10 acima de 60 limpam). "
    "O LLM roda local no Ollama, sem nuvem."
)

SYSTEM = (
    "Você é o assistente do muro dos boxes da equipe PITWALL (Fórmula 1). Responda SEMPRE em português do Brasil, "
    "de forma curta e objetiva (no máximo 8 linhas), usando APENAS os DADOS fornecidos. Se a informação não estiver "
    "nos dados, diga que não sabe. Saúde da PU: >=70 bom, 50-70 atenção, <50 crítico. Para PU com saúde baixa ou "
    "vibração alta recomende: modo CONSERVE, reduzir RPM, e planejar reparo/troca da PU; alerta de temperatura alta: "
    "o resfriamento automático liga; desgaste de pneu alto: chamar BOX. Explique métricas assim: MAE é o erro médio, "
    "RMSE penaliza erros grandes, R² perto de 1 é bom, e o modelo só vale se vencer a base (prever sempre a média)."
)


def build_context() -> str:
    lines = [f"Horário: {time.strftime('%H:%M:%S')}", ""]
    lines.append("CARROS (última leitura | previsão da IA):")
    for car, t in sorted(hub.latest.items(), key=lambda kv: kv[1].get("position", 99)):
        wear = max((t.get(f"tyre_wear_{w}", 0) for w in ("FL", "FR", "RL", "RR")), default=0)
        pr = hub.predictions.get(car)
        ia = (f"saúde {pr['health']:.0f}/100, vida útil {pr['rul_h']:.1f} h, tendência {pr['trend_per_min']:+.1f}/min"
              if pr else "sem previsão (modelo não treinado)")
        lines.append(
            f"- {car} ({t.get('driver')}, {t.get('team')}{', NOSSA EQUIPE' if t.get('team_car') else ''}): P{t.get('position')} "
            f"volta {t.get('lap')}, status {t.get('status')}, motor {t.get('engine_temp')}°C, óleo {t.get('oil_temp')}°C / "
            f"{t.get('oil_pressure')} bar, vibração {t.get('pu_vibration')} g, modo {t.get('engine_mode')}, "
            f"resfriamento {'ON' if t.get('cooling') else 'OFF'}, pneu {t.get('tyre_compound')} desgaste máx {wear:.0f}%, "
            f"combustível {t.get('fuel_kg')} kg | IA: {ia}")
    if hub.predictions:
        worst = min(hub.predictions.values(), key=lambda p: p["health"])
        lines.append(f"PIOR SAÚDE: {worst['car_id']} com {worst['health']:.0f}/100 (vida útil {worst['rul_h']:.1f} h)")
    alerts = db.query("select car_id, severity, message from alerts where cleared_at is null order by raised_at desc limit 10")
    lines += ["", "ALERTAS ABERTOS:"] + ([f"- [{a['severity']}] {a['message']}" for a in alerts] or ["- nenhum"])
    meta = current_model()
    lines += ["", "MODELOS:"]
    if meta:
        lines.append(f"versão v{meta['version']}, treinado com {meta['dataset'].get('readings')} leituras sintéticas "
                     f"de {meta['dataset'].get('equipments')} PUs; divisão por equipamento {meta['equipments']}")
        for m in meta["models"].values():
            lines.append(f"- {m['label']}: MAE {m['test']['mae']}, RMSE {m['test']['rmse']}, R² {m['test']['r2']} "
                         f"(base: MAE {m['baseline']['mae']}, R² {m['baseline']['r2']}); vence a base: "
                         f"{'sim' if m['beats_baseline'] else 'não'}; atributo mais importante: {m['importance'][0]['feature']}")
    else:
        lines.append("- nenhum modelo treinado ainda")
    lines += ["", "CONTEXTO:", ARCH]
    return "\n".join(lines)


class Question(BaseModel):
    question: str = Field(..., min_length=2, max_length=500)


@router.get("/assistant/status")
async def assistant_status():
    async with httpx.AsyncClient(base_url=OLLAMA, timeout=3) as c:
        try:
            tags = (await c.get("/api/tags")).json().get("models", [])
            ps = (await c.get("/api/ps")).json().get("models", [])
        except (httpx.HTTPError, ValueError):
            return {"online": False, "pulled": False, "loaded": False, "model": MODEL}
    names = lambda ms: {m.get("name") for m in ms} | {m.get("model") for m in ms}  # noqa: E731
    return {"online": True, "pulled": MODEL in names(tags), "loaded": MODEL in names(ps), "model": MODEL}


@router.post("/assistant/chat")
async def assistant_chat(q: Question, request: Request):
    who = request.headers.get("x-client-id") or (request.client.host if request.client else "anon")
    now = time.time()
    hist = _asked[who]
    if len(hist) == RATE_PER_MIN and now - hist[0] < 60:
        raise HTTPException(429, f"Limite de {RATE_PER_MIN} perguntas por minuto. Aguarde {int(60 - (now - hist[0]))} s.")
    hist.append(now)
    context = await run_in_threadpool(build_context)
    await run_in_threadpool(db.audit, "web", "assistant.question", who[:64], {"question": q.question})

    body = {
        "model": MODEL, "stream": True, "keep_alive": -1,
        "options": {"temperature": 0.3, "num_ctx": 4096, "num_predict": 400},
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": f"DADOS ATUAIS:\n{context}\n\nPERGUNTA: {q.question}"},
        ],
    }

    async def stream():
        try:
            async with httpx.AsyncClient(base_url=OLLAMA, timeout=httpx.Timeout(300, connect=5)) as c:
                async with c.stream("POST", "/api/chat", json=body) as r:
                    if r.status_code != 200:
                        yield f"\n[erro do modelo local: HTTP {r.status_code}]"
                        return
                    async for line in r.aiter_lines():
                        if not line:
                            continue
                        chunk = json.loads(line)
                        text = (chunk.get("message") or {}).get("content", "")
                        if text:
                            yield text
                        if chunk.get("done"):
                            break
        except httpx.HTTPError as exc:
            yield f"\n[o modelo local está indisponível ou carregando: {exc.__class__.__name__}]"

    return StreamingResponse(stream(), media_type="text/plain; charset=utf-8",
                             headers={"X-Accel-Buffering": "no", "Cache-Control": "no-cache"})
