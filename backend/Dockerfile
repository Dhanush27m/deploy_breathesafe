# ── BreatheSafe Backend Dockerfile ───────────────────────────────────────────
FROM python:3.11-slim

# Ensure Python output (print/logging) is flushed immediately to Render logs
ENV PYTHONUNBUFFERED=1

RUN apt-get update && apt-get install -y gcc libpq-dev curl && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy entire backend source
COPY . .

# ml/models/ — XGBoost .joblib files are committed to git (trained locally
#              on the full 944k-row CSV via train_models.py at the repo root).
#              Render copies them via "COPY . ." — no training happens at deploy time.
# data/       — CSV is NOT included in the image (gitignored).
RUN mkdir -p /app/data /app/ml/models

RUN adduser --disabled-password --gecos "" appuser && chown -R appuser /app
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
  CMD curl -f http://localhost:8000/health || exit 1

# ── Startup sequence ──────────────────────────────────────────────────────────
# 1. alembic upgrade head  — run DB migrations (idempotent)
# 2. seed_cities.py        — insert 29 city + station rows (idempotent)
# 3. uvicorn               — start the API server
#
# Models are pre-trained locally via train_models.py and committed to git.
# No training step is needed at deploy time — models load instantly from disk.
CMD ["sh", "-c", \
  "python -m alembic upgrade head && \
   python seed_cities.py && \
   uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
