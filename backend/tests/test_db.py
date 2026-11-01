"""Database tests against a real TimescaleDB (skipped when TEST_DATABASE_URL is unreachable).

Locally: `make up`, then `make test` uses the compose database (a separate `desk_test` database).
CI runs a TimescaleDB service container.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.core.config import REPO_ROOT, get_desk_config
from app.data import store
from app.data.backfill import backfill, resume_from
from app.data.market_config import get_market_config, load_broker_profiles
from app.data.models import Bar
from app.data.timeframes import Timeframe
from tests.factories import utc

URL = os.environ.get("TEST_DATABASE_URL", "postgresql+asyncpg://desk:change-me-locally@localhost:5432/desk_test")
pytestmark = pytest.mark.db
D = Decimal


async def _reachable() -> bool:
    admin = create_async_engine(URL.rsplit("/", 1)[0] + "/postgres", isolation_level="AUTOCOMMIT")
    try:
        async with admin.connect() as c:
            db = URL.rsplit("/", 1)[1]
            if not (await c.execute(text("select 1 from pg_database where datname=:d"), {"d": db})).scalar():
                await c.execute(text(f'create database "{db}"'))
        return True
    except Exception:
        return False
    finally:
        await admin.dispose()


@pytest.fixture
async def engine(monkeypatch: pytest.MonkeyPatch) -> AsyncIterator[AsyncEngine]:
    if not await _reachable():
        pytest.skip("TEST_DATABASE_URL not reachable (run `make up` first)")
    monkeypatch.setenv("DATABASE_URL", URL)
    from app.core import config

    config.get_settings.cache_clear()
    cfg = Config(str(REPO_ROOT / "backend" / "alembic.ini"))
    cfg.set_main_option("script_location", str(REPO_ROOT / "backend" / "migrations"))
    import asyncio

    await asyncio.to_thread(command.downgrade, cfg, "base")
    await asyncio.to_thread(command.upgrade, cfg, "head")
    eng = create_async_engine(URL)
    yield eng
    await eng.dispose()


def _bar(t: datetime, px: str, complete: bool = True, tf: Timeframe = Timeframe.M1) -> Bar:
    p = D(px)
    return Bar(
        instrument="EURUSD",
        timeframe=tf,
        open_time=t,
        close_time=t + timedelta(minutes=1),
        bid_o=p,
        bid_h=p,
        bid_l=p,
        bid_c=p,
        ask_o=p + D("0.0001"),
        ask_h=p + D("0.0001"),
        ask_l=p + D("0.0001"),
        ask_c=p + D("0.0001"),
        volume=2,
        complete=complete,
        source="oanda",
    )


async def test_hypertables_and_policies_exist(engine: AsyncEngine) -> None:
    async with engine.connect() as c:
        hts = set((await c.execute(text("select hypertable_name from timescaledb_information.hypertables"))).scalars())
        jobs = list((await c.execute(text("select proc_name from timescaledb_information.jobs"))).scalars())
    assert {"ticks", "candles"} <= hts
    assert "policy_retention" in jobs and "policy_compression" in jobs


async def test_candle_roundtrip_decimal_and_point_in_time(engine: AsyncEngine) -> None:
    t0 = utc(2026, 11, 4, 13, 0)
    async with engine.begin() as c:
        await store.upsert_candles(c, [_bar(t0, "1.08012"), _bar(t0 + timedelta(minutes=1), "1.08015", complete=False)])
    async with engine.connect() as c:
        bars = await store.closed_bars(c, "EURUSD", Timeframe.M1, as_of=t0 + timedelta(minutes=5))
        assert [b.bid_c for b in bars] == [D("1.08012")]  # incomplete bar never served
        assert await store.closed_bars(c, "EURUSD", Timeframe.M1, as_of=t0 + timedelta(seconds=59)) == []
    async with engine.begin() as c:  # provider later completes the bar → replaced
        await store.upsert_candles(c, [_bar(t0 + timedelta(minutes=1), "1.08016")])
        await store.upsert_candles(c, [_bar(t0, "9.99999", complete=False)])  # never downgrades a complete bar
    async with engine.connect() as c:
        bars = await store.closed_bars(c, "EURUSD", Timeframe.M1, as_of=t0 + timedelta(minutes=5))
    assert [b.bid_c for b in bars] == [D("1.08012"), D("1.08016")]


class FakeCandles:
    name = "oanda"

    def __init__(self, bars: list[Bar]) -> None:
        self.bars = bars
        self.requested_from: list[datetime] = []

    async def candles(self, instrument, tf, start, end, include_incomplete=False):  # type: ignore[no-untyped-def]
        self.requested_from.append(start)
        page = [b for b in self.bars if start <= b.open_time < end]
        for i in range(0, len(page), 3):
            yield page[i : i + 3]


async def test_backfill_is_resumable_and_idempotent(engine: AsyncEngine) -> None:
    t0 = utc(2026, 11, 4, 0, 0)
    bars = [_bar(t0 + timedelta(minutes=i), f"1.08{i:03d}") for i in range(10)]
    a = FakeCandles(bars)
    assert await backfill(engine, a, "EURUSD", Timeframe.M1, t0, t0 + timedelta(hours=1)) == 10
    assert await backfill(engine, a, "EURUSD", Timeframe.M1, t0, t0 + timedelta(hours=1)) == 1  # resumes at last bar
    assert a.requested_from[1] == bars[-1].open_time
    async with engine.connect() as c:
        assert (await c.execute(text("select count(*) from candles"))).scalar() == 10


def test_resume_from() -> None:
    assert resume_from(utc(2026, 1, 1), None) == utc(2026, 1, 1)
    assert resume_from(utc(2026, 1, 1), utc(2026, 5, 1)) == utc(2026, 5, 1)


async def test_seed_reference_data_keeps_confirmed_specs(engine: AsyncEngine) -> None:
    desk, market, profiles = get_desk_config(), get_market_config(), load_broker_profiles()
    async with engine.begin() as c:
        await store.seed_reference_data(c, desk, market, profiles)
        await c.execute(text("update instrument_specs set contract_size = 1000, confirmed = true where symbol = 'WTI'"))
        await store.seed_reference_data(c, desk, market, profiles)  # re-seed must not clobber the owner's value
    async with engine.connect() as c:
        size = (await c.execute(text("select contract_size from instrument_specs where symbol='WTI'"))).scalar()
        n_map = (await c.execute(text("select count(*) from symbol_map"))).scalar()
    assert size == D(1000) and n_map == 7 * 4


async def test_feed_consumer_persists_ticks_and_stream_bars(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio
    import contextlib

    import fakeredis.aioredis
    import httpx

    import app.stream.feed_consumer as fc_mod
    from app.core import db
    from app.data.adapters.prices.oanda import OandaAdapter
    from app.stream.feed_consumer import FeedConsumer

    db.get_engine.cache_clear()
    recording = (REPO_ROOT / "tests" / "stream_recordings" / "synthetic_oanda_pricing.ndjson").read_bytes()
    monkeypatch.setattr(fc_mod, "utc_now", lambda: utc(2026, 11, 4, 13, 1, 6))
    adapter = OandaAdapter(
        "tok",
        "acct",
        get_market_config().sources.oanda.symbols,
        transport=httpx.MockTransport(lambda r: httpx.Response(200, content=recording)),
    )
    fc = FeedConsumer(fakeredis.aioredis.FakeRedis(), adapter, ["EURUSD", "XAUUSD"])
    tasks = [asyncio.create_task(fc.consume()), asyncio.create_task(fc.flush())]
    await asyncio.sleep(2.5)
    for task in tasks:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
    await adapter.aclose()
    async with engine.connect() as c:
        n_ticks = (await c.execute(text("select count(*) from ticks"))).scalar()
        bars = (await c.execute(text("select instrument, timeframe, source, bid_c from candles"))).all()
    db.get_engine.cache_clear()
    assert n_ticks == 3
    assert [(b[0], b[1], b[2], b[3]) for b in bars] == [("EURUSD", "M1", "stream", D("1.08012"))]
