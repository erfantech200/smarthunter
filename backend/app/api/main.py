"""FastAPI application. Phase 0: health endpoints only."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Response, status
from redis.asyncio import Redis

from app.core import heartbeat
from app.core.config import get_desk_config, get_settings
from app.core.db import REQUIRED_EXTENSIONS, get_engine, installed_extensions
from app.core.guards import production_guard
from app.core.logging import configure_logging, get_logger

DISCLAIMER = "Decision support only. Not financial advice."


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    configure_logging("api", settings.log_level)
    production_guard(settings)
    get_desk_config()
    app.state.redis = Redis.from_url(settings.redis_url)
    get_logger().info("api_started", env=settings.app_env.value)
    yield
    await app.state.redis.aclose()
    await get_engine().dispose()


app = FastAPI(title="Trade Desk", version="0.0.1", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    """Liveness: the process is up. No dependencies checked."""
    return {"status": "ok", "disclaimer": DISCLAIMER}


@app.get("/health/ready")
async def ready(response: Response) -> dict[str, Any]:
    """Readiness: Postgres (with TimescaleDB + pgvector) and Redis reachable."""
    checks: dict[str, Any] = {}
    try:
        exts = await installed_extensions(get_engine())
        missing = [e for e in REQUIRED_EXTENSIONS if e not in exts]
        checks["postgres"] = "ok" if not missing else f"missing extensions: {missing}"
    except Exception as exc:
        checks["postgres"] = f"error: {type(exc).__name__}"
    try:
        await app.state.redis.ping()
        checks["redis"] = "ok"
    except Exception as exc:
        checks["redis"] = f"error: {type(exc).__name__}"
    ok = all(v == "ok" for v in checks.values())
    if not ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": "ok" if ok else "unavailable", "checks": checks}


@app.get("/health/services")
async def services(response: Response) -> dict[str, Any]:
    """Heartbeats of the background services (worker, scheduler, stream, fast)."""
    out: dict[str, Any] = {}
    for name in heartbeat.SERVICES:
        hb = await heartbeat.read(app.state.redis, name)
        out[name] = hb.model_dump(mode="json") if hb else {"status": "missing"}
    if any(v["status"] == "missing" for v in out.values()):
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return out


@app.get("/health/config")
async def config_status() -> dict[str, Any]:
    """Config summary for Settings → provider key status. Never returns secret values."""
    desk = get_desk_config()
    settings = get_settings()
    return {
        "env": settings.app_env.value,
        "assets": [a.symbol for a in desk.assets],
        "market_data_provider": desk.market_data_provider,
        "open_questions": desk.open_questions(),
        "provider_keys_configured": settings.provider_key_status(),
        "mock_adapters": settings.mock_adapter_list,
    }
