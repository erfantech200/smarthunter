from __future__ import annotations

import asyncio
import contextlib
from datetime import timedelta
from typing import Any

import fakeredis.aioredis
import httpx
import orjson
import pytest

from app.core import keys
from app.core.config import REPO_ROOT
from app.data.adapters.prices.oanda import OandaAdapter
from app.data.market_config import get_market_config
from app.orchestrator import scheduler
from app.orchestrator.schedule import DailyAt, Every, phase1_jobs
from app.stream.feed_consumer import FeedConsumer
from app.stream.watchdog import StreamStatus
from tests.factories import utc

RECORDING = (REPO_ROOT / "tests" / "stream_recordings" / "synthetic_oanda_pricing.ndjson").read_bytes()


async def test_feed_consumer_replays_recording_then_flags_disconnect(monkeypatch: pytest.MonkeyPatch) -> None:
    import app.stream.feed_consumer as fc_mod

    monkeypatch.setattr(fc_mod, "utc_now", lambda: utc(2026, 11, 4, 13, 1, 6))  # Wednesday, markets open
    redis = fakeredis.aioredis.FakeRedis()
    adapter = OandaAdapter(
        "tok",
        "acct",
        get_market_config().sources.oanda.symbols,
        transport=httpx.MockTransport(lambda r: httpx.Response(200, content=RECORDING)),
    )
    fc = FeedConsumer(redis, adapter, ["EURUSD", "XAUUSD"])
    task = asyncio.create_task(fc.consume())
    await asyncio.sleep(0.3)  # stream ends after the recording → disconnect → backoff sleep
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    await adapter.aclose()

    latest = orjson.loads(await redis.get(keys.quote("EURUSD")))
    assert latest["bid"] == "1.08015"  # last EURUSD price in the recording
    assert await redis.xlen(keys.tick_stream("EURUSD")) == 2
    assert await redis.xlen(keys.bar_stream("EURUSD", "M1")) == 1  # 13:00 bar closed by the 13:01 quote
    assert len(fc._ticks) == 3 and fc.watchdog.disconnects == 1
    status = fc.watchdog.status(utc(2026, 11, 4, 13, 1, 7))
    assert status.status.value == "CRITICAL" and not status.connected


def test_schedule_slots() -> None:
    t = utc(2026, 11, 4, 13, 5, 42)
    assert Every(60).slot(t) == "2026-11-04T13:05:00"
    assert Every(180).slot(t) == "2026-11-04T13:03:00"
    assert DailyAt(__import__("datetime").time(22, 30)).slot(t) is None
    assert DailyAt(__import__("datetime").time(13, 0)).slot(t) == "2026-11-04"


class FakePool:
    def __init__(self) -> None:
        self.ids: list[str] = []

    async def enqueue_job(self, name: str, *args: Any, _job_id: str) -> object | None:
        if _job_id in self.ids:
            return None
        self.ids.append(_job_id)
        return object()


async def test_scheduler_tick_is_idempotent_and_forwards_outliers() -> None:
    scheduler._last.clear()
    pool, redis = FakePool(), fakeredis.aioredis.FakeRedis()
    t = utc(2026, 11, 4, 23, 0, 1)
    first = await scheduler.tick(pool, redis, t)  # type: ignore[arg-type]
    assert {j.split(":")[0] for j in first} == {j.name for j in phase1_jobs(180)}
    assert await scheduler.tick(pool, redis, t + timedelta(seconds=5)) == []  # type: ignore[arg-type]
    await redis.lpush(keys.OUTLIER_REQUESTS, "XAUUSD")
    again = await scheduler.tick(pool, redis, t + timedelta(seconds=10))  # type: ignore[arg-type]
    assert again == ["outlier:XAUUSD"]


def test_stream_status_round_trips_through_redis_json() -> None:
    from app.stream.watchdog import StreamWatchdog

    wd = StreamWatchdog(get_market_config(), ["EURUSD"])
    s = wd.status(utc(2026, 11, 4, 13))
    assert StreamStatus.model_validate_json(s.model_dump_json()) == s
