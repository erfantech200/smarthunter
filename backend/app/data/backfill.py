"""History backfill (Phase 1): provider candles per instrument × timeframe, resumable and idempotent."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncEngine

from app.core.logging import get_logger
from app.core.time import ensure_utc, utc_now
from app.data import store
from app.data.adapters.base import CandleAdapter
from app.data.market_config import BackfillTf
from app.data.timeframes import Timeframe


def configured_start(spec: BackfillTf, now: datetime) -> datetime:
    if spec.start is not None:
        return datetime(spec.start.year, spec.start.month, spec.start.day, tzinfo=UTC)
    assert spec.start_days_ago is not None
    return (now - timedelta(days=spec.start_days_ago)).replace(hour=0, minute=0, second=0, microsecond=0)


def resume_from(configured: datetime, latest_stored: datetime | None) -> datetime:
    """Start at the configured date, or at the last stored bar (re-fetched so it can be completed)."""
    return configured if latest_stored is None else max(configured, ensure_utc(latest_stored))


async def backfill(
    engine: AsyncEngine,
    adapter: CandleAdapter,
    instrument: str,
    tf: Timeframe,
    start: datetime,
    end: datetime | None = None,
) -> int:
    log = get_logger()
    end = end or utc_now()
    async with engine.connect() as conn:
        latest = await store.latest_open_time(conn, instrument, tf, adapter.name)
    cursor = resume_from(start, latest)
    total = 0
    async for page in adapter.candles(instrument, tf, cursor, end):
        async with engine.begin() as conn:
            total += await store.upsert_candles(conn, page)
        log.info(
            "backfill_page", instrument=instrument, tf=tf.value, bars=len(page), last=page[-1].open_time.isoformat()
        )
    log.info("backfill_done", instrument=instrument, tf=tf.value, bars=total, since=cursor.isoformat())
    return total
