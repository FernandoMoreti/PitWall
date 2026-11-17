# Imagem única para os serviços Python (simulator, gateway, workers, IA, api).
# Cada serviço escolhe o seu comando no docker-compose.yml.
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app/shared

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY shared ./shared
COPY simulator ./simulator
COPY gateway ./gateway
COPY workers ./workers
COPY api ./api

# /data: volumes da IA (dataset e modelos) — criados aqui para herdarem o dono não-root
RUN useradd --create-home --uid 10001 pitwall \
 && mkdir -p /data/lab /data/models && chown -R pitwall /data
USER pitwall
