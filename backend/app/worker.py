"""Arq worker (SPEC §20 — queue choice in docs/DECISIONS.md ADR-003).

Run with ``arq app.worker.WorkerSettings``. Jobs are thin wrappers around ``app.data.jobs``.
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
from app.data import jobs

PROBE_KEY = "desk:probe:last"


async def probe(ctx: dict[str, Any], enqueued_at: str) -> str:
    redis: Redis = ctx["redis"]
    done = datetime.now(UTC).isoformat()
    await redis.set(PROBE_KEY, f"{enqueued_at}|{done}", ex=600)
    return done


async def backfill_job(ctx: dict[str, Any], symbol: str | None = None, tf: str | None = None) -> dict[str, Any]:
    return await jobs.backfill_all(symbol, tf)


async def macro_job(ctx: dict[str, Any]) -> dict[str, Any]:
    return await jobs.refresh_macro()


async def cross_check_job(ctx: dict[str, Any], only: list[str] | None = None, outlier: bool = False) -> dict[str, Any]:
    return await jobs.cross_check(ctx["redis"], only, outlier)


async def integrity_job(ctx: dict[str, Any]) -> dict[str, Any]:
    return await jobs.integrity_check(ctx["redis"])


async def spreads_job(ctx: dict[str, Any]) -> dict[str, Any]:
    return await jobs.compute_spreads()


async def gaps_job(ctx: dict[str, Any]) -> dict[str, Any]:
    return await jobs.gap_reports()


async def reconcile_job(ctx: dict[str, Any]) -> dict[str, Any]:
    return await jobs.reconcile_recent()


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
    try:
        await jobs.seed()
    except Exception as exc:  # DB not migrated yet etc.; the scheduler retries seeding via jobs
        get_logger().error("seed_failed", error=str(exc))
    get_logger().info("worker_started")


async def shutdown(ctx: dict[str, Any]) -> None:
    task: asyncio.Task[None] | None = ctx.get("hb_task")
    if task:
        task.cancel()


class WorkerSettings:
    functions: ClassVar[list[Any]] = [
        probe,
        backfill_job,
        macro_job,
        cross_check_job,
        integrity_job,
        spreads_job,
        gaps_job,
        reconcile_job,
    ]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    max_tries = 3
    job_timeout = 3600  # long backfills
    keep_result = 3600
