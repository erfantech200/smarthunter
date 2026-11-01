"""Arq worker (SPEC §20 — queue choice in docs/DECISIONS.md ADR-003).

Run with ``arq app.worker.WorkerSettings``. Phase 0 has one job, ``probe``, which records the
scheduler→worker round-trip. Agent runs, backfills and research jobs are added in later phases.
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any, ClassVar

from arq.connections import RedisSettings
from redis.asyncio import Redis

from app.core import heartbeat
from app.core.config import get_desk_config, get_settings
from app.core.guards import production_guard
from app.core.logging import configure_logging, get_logger

PROBE_KEY = "desk:probe:last"


async def probe(ctx: dict[str, Any], enqueued_at: str) -> str:
    redis: Redis = ctx["redis"]
    done = datetime.now(UTC).isoformat()
    await redis.set(PROBE_KEY, f"{enqueued_at}|{done}", ex=600)
    return done


async def _heartbeat_loop(redis: Redis) -> None:
    while True:
        await heartbeat.beat(redis, "worker", "ok", "arq worker running")
        await asyncio.sleep(10)


async def startup(ctx: dict[str, Any]) -> None:
    settings = get_settings()
    configure_logging("worker", settings.log_level)
    production_guard(settings)
    get_desk_config()
    ctx["hb_task"] = asyncio.create_task(_heartbeat_loop(ctx["redis"]))
    get_logger().info("worker_started")


async def shutdown(ctx: dict[str, Any]) -> None:
    task: asyncio.Task[None] | None = ctx.get("hb_task")
    if task:
        task.cancel()


class WorkerSettings:
    functions: ClassVar[list[Any]] = [probe]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    max_tries = 3
    job_timeout = 300
