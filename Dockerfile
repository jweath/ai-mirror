FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 MIRROR_DB_PATH=/data/mirror.db MIRROR_ASSET_ROOT=/app
WORKDIR /app
COPY pyproject.toml requirements.lock ./
RUN pip install --no-cache-dir -r requirements.lock
COPY src ./src
COPY web ./web
COPY skills ./skills
COPY docs ./docs
COPY config ./config
RUN pip install --no-cache-dir --no-deps .
# Single worker and single replica: SQLite and delivery recovery share one process owner.
CMD ["sh", "-c", "uvicorn ai_mirror.app:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
