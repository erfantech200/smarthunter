"""Scheduler service (SPEC §16, ADR-004). Enqueues Arq jobs by slot id; idempotent across restarts.

Phase 1 schedule: integrity (1 min), cross-source check (config interval), backfill + reconciliation
(hourly), FRED, spreads and gap reports (daily). Outlier confirmations requested by the stream are
forwarded immediately. DST-aware session runs (weekly open, pre-Tokyo/London/NY) arrive in Phase 7.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable
from datetime import datetime
from typing import cast

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings
from redis.asyncio import Redis

from app.core import keys
from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.service import run_service
from app.core.time import utc_now
from app.data.market_config import get_market_config
from app.orchestrator.schedule import phase1_jobs

TICK_SECONDS = 5
_last: dict[str, str] = {}


async def status() -> tuple[str, str]:
    return "ok", f"{len(_last)} job types scheduled; last: " + ", ".join(sorted(_last.values()))[-200:]


async def tick(pool: ArqRedis, redis: Redis, now: datetime) -> list[str]:
    enqueued = []
    for job in phase1_jobs(get_market_config().sources.twelvedata.cross_check.interval_seconds):
        jid = job.job_id(now)
        if jid is None or _last.get(job.name) == jid:
            continue
        args = (now.isoformat(),) if job.name == "probe" else ()
        if await pool.enqueue_job(job.name, *args, _job_id=jid) is not None:
            enqueued.append(jid)
        _last[job.name] = jid
    while (sym := await cast(Awaitable[bytes | None], redis.rpop(keys.OUTLIER_REQUESTS))) is not None:
        s = sym.decode()
        await pool.enqueue_job("cross_check_job", [s], True, _job_id=f"outlier:{s}:{now:%Y%m%dT%H%M}")
        enqueued.append(f"outlier:{s}")
    return enqueued


async def work(redis: Redis) -> None:
    log = get_logger()
    pool = await create_pool(RedisSettings.from_dsn(get_settings().redis_url))
    try:
        while True:
            for jid in await tick(pool, redis, utc_now()):
                log.info("job_enqueued", job_id=jid)
            await asyncio.sleep(TICK_SECONDS)
    finally:
        await pool.aclose()


def main() -> None:
    asyncio.run(run_service("scheduler", status, work))


if __name__ == "__main__":
    main()
