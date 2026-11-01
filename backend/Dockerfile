# One image for every Python service (api, worker, scheduler, stream, fast, migrate).
# Build context: repository root (the image also needs config/desk.yaml).
FROM python:3.12-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv PATH="/opt/venv/bin:$PATH"
RUN pip install --no-cache-dir "uv==0.11.*"
WORKDIR /app/backend

COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY backend/ ./
COPY config/ /app/config/
RUN uv sync --frozen --no-dev

RUN useradd --system --uid 10001 desk
USER desk
EXPOSE 8000
CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
