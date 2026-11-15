# Imagem única para os serviços Python (simulator, gateway, workers, api).
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

RUN useradd --create-home --uid 10001 pitwall
USER pitwall
