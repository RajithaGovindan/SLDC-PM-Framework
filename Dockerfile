# SDLC Orchestrator - Cloud Run image
FROM python:3.11-slim

# git: code-aware revisions clone the project repository (read-only)
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY alembic ./alembic
COPY alembic.ini .

ENV PYTHONUNBUFFERED=1 \
    AUTO_CREATE_TABLES=false \
    DB_FALLBACK_TO_SQLITE=false \
    REPO_CACHE_DIR=/tmp/repos \
    PORT=8080

# Migrate, then serve. One worker: the database pool is deliberately small (shared Cloud SQL instance).
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --workers 1 --proxy-headers --forwarded-allow-ips='*'"]
