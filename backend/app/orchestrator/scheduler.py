"""Scheduler service (SPEC §16).

Phase 0 scaffold: enqueues a ``probe`` job on the worker queue every minute, which proves the
scheduler → Redis → worker path end to end. Phase 1+ replaces this with DST-aware session runs
(weekly open, pre-Tokyo/London/New York), the news cycle and candle-close triggers, all
computed in UTC from ``zoneinfo`` (see docs/DECISIONS.md ADR-004).
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from arq import create_pool
from arq.connections import RedisSettings
from redis.asyncio import Redis

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.service import run_service

PROBE_INTERVAL_SECONDS = 60
_last_enqueued: datetime | None = None


async def status() -> tuple[str, str]:
    when = _last_enqueued.isoformat() if _last_enqueued else "never"
    return "ok", f"probe last enqueued at {when}"


async def work(_: Redis) -> None:
    global _last_enqueued
    log = get_logger()
    pool = await create_pool(RedisSettings.from_dsn(get_settings().redis_url))
    try:
        while True:
            now = datetime.now(UTC)
            await pool.enqueue_job("probe", now.isoformat(), _job_id=f"probe:{now:%Y%m%dT%H%M}")
            _last_enqueued = now
            log.info("probe_enqueued")
            await asyncio.sleep(PROBE_INTERVAL_SECONDS)
    finally:
        await pool.aclose()


def main() -> None:
    asyncio.run(run_service("scheduler", status, work))


if __name__ == "__main__":
    main()
