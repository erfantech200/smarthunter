"""Streaming service: price feed → watchdog + bar builder → Redis + Postgres (SPEC §4, §20).

* Quotes: latest per instrument in ``desk:quote:<sym>``; every quote on ``stream:ticks:<sym>``.
* Closed bars (M1…W1, source ``stream``) on ``stream:bars:<sym>:<tf>`` and in ``candles``.
* Watchdog status every second in ``desk:stream:status`` (+ pub/sub on change). A12 halts on CRITICAL.
* Reconnects with exponential backoff; a disconnect is CRITICAL immediately, silence after 15 s.

With no OANDA credentials the service stays ``idle`` — it never invents prices (SPEC §3.2).
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Awaitable
from decimal import Decimal
from typing import cast

import orjson
from redis.asyncio import Redis

from app.core import keys
from app.core.config import get_desk_config, get_settings
from app.core.db import get_engine
from app.core.logging import get_logger
from app.core.service import run_service
from app.core.time import utc_now
from app.data import store
from app.data.adapters.base import AdapterAuthError, AdapterNotConfigured
from app.data.adapters.prices.oanda import OandaAdapter
from app.data.market_config import get_market_config
from app.data.models import Bar, Quote
from app.data.timeframes import Timeframe
from app.orchestrator.integrity_model import Status
from app.orchestrator.market_hours import spread_bucket
from app.stream.bar_builder import BarBuilder
from app.stream.watchdog import StreamWatchdog

TICK_STREAM_MAXLEN = 20_000
BAR_STREAM_MAXLEN = 5_000

_state: dict[str, str] = {"status": "idle", "detail": "starting"}


async def status() -> tuple[str, str]:
    return _state["status"], _state["detail"]


class FeedConsumer:
    def __init__(self, redis: Redis, adapter: OandaAdapter, symbols: list[str]) -> None:
        self.redis, self.adapter, self.symbols = redis, adapter, symbols
        self.cfg = get_market_config()
        self.watchdog = StreamWatchdog(self.cfg, symbols)
        self.builder = BarBuilder()
        self.log = get_logger()
        self._ticks: list[Quote] = []
        self._bars: list[Bar] = []
        self._typical: dict[str, dict[str, Decimal]] = {}
        self._last_status: Status | None = None

    # ------------------------------------------------------------------ loops
    async def consume(self) -> None:
        backoff, max_backoff = 1.0, self.cfg.sources.oanda.stream_reconnect_max_backoff_seconds
        while True:
            try:
                connected = False
                async for item in self.adapter.stream(self.symbols):
                    now = utc_now()
                    if not connected:
                        self.watchdog.on_connect(now)
                        connected, backoff = True, 1.0
                        self.log.info("stream_connected")
                    self.watchdog.on_message(now)
                    if isinstance(item, Quote):
                        await self._on_quote(item)
                self.log.warning("stream_ended")
            except AdapterAuthError as exc:
                self.log.error("stream_auth_failed", error=str(exc))
                backoff = max_backoff
            except Exception as exc:  # network drop, protocol error: reconnect
                self.log.warning("stream_error", error=f"{type(exc).__name__}: {exc}")
            self.watchdog.on_disconnect()
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, max_backoff)

    async def clock(self) -> None:
        while True:
            now = utc_now()
            await self._emit(self.builder.on_clock(now))
            await self._resolve_outliers()
            st = self.watchdog.status(now)
            await self.redis.set(keys.STREAM_STATUS, st.model_dump_json(), ex=30)
            if st.status is not self._last_status:
                await self.redis.publish(keys.CHANNEL_STREAM_STATUS, st.model_dump_json())
                self.log.info("stream_status", status=st.status.value, issues=[i.message for i in st.issues][:5])
                self._last_status = st.status
            _state["status"] = {"OK": "ok", "DEGRADED": "degraded", "CRITICAL": "halted"}[st.status.value]
            _state["detail"] = (
                f"stream {st.status.value}; connected={st.connected}; disconnects={self.watchdog.disconnects}"
            )
            await asyncio.sleep(1)

    async def flush(self) -> None:
        engine = get_engine()
        while True:
            await asyncio.sleep(2)
            ticks, bars = self._ticks, self._bars
            self._ticks, self._bars = [], []
            if not ticks and not bars:
                continue
            try:
                async with engine.begin() as conn:
                    await store.insert_ticks(conn, ticks)
                    await store.upsert_candles(conn, bars)
            except Exception as exc:  # keep streaming; data stays in Redis streams
                self.log.error("persist_failed", error=str(exc), ticks=len(ticks), bars=len(bars))

    async def refresh_typical_spreads(self) -> None:
        while True:
            with contextlib.suppress(Exception):
                async with get_engine().connect() as conn:
                    self._typical = await store.typical_spreads(conn)
            bucket = spread_bucket(self.cfg, utc_now())
            for sym, by in self._typical.items():
                if bucket in by:
                    self.watchdog.typical_spread[sym] = by[bucket]
            await asyncio.sleep(600)

    # ------------------------------------------------------------------ handlers
    async def _on_quote(self, q: Quote) -> None:
        if self.watchdog.on_quote(q) is not None:
            await cast(
                Awaitable[int], self.redis.lpush(keys.OUTLIER_REQUESTS, q.instrument)
            )  # picked up by the worker's cross-check
        payload = q.model_dump_json()
        await self.redis.set(keys.quote(q.instrument), payload, ex=3600)
        await self.redis.xadd(
            keys.tick_stream(q.instrument), {"q": payload}, maxlen=TICK_STREAM_MAXLEN, approximate=True
        )
        self._ticks.append(q)
        await self._emit(self.builder.on_quote(q))

    async def _emit(self, bars: list[Bar]) -> None:
        for b in bars:
            if b.timeframe is Timeframe.M1:
                self.watchdog.on_bar(b)
            await self.redis.xadd(
                keys.bar_stream(b.instrument, b.timeframe.value),
                {"b": b.model_dump_json()},
                maxlen=BAR_STREAM_MAXLEN,
                approximate=True,
            )
            self._bars.append(b)

    async def _resolve_outliers(self) -> None:
        for sym in self.symbols:
            raw = await self.redis.getdel(keys.outlier_resolution(sym))
            if raw is not None:
                self.watchdog.resolve_outlier(sym, confirmed=orjson.loads(raw)["confirmed"])


async def work(redis: Redis) -> None:
    settings = get_settings()
    symbols = [a.symbol for a in get_desk_config().assets]
    try:
        adapter = OandaAdapter(
            settings.oanda_api_token.get_secret_value() if settings.oanda_api_token else None,
            settings.oanda_account_id,
            get_market_config().sources.oanda.symbols,
            settings.oanda_environment,
        )
    except AdapterNotConfigured as exc:
        _state.update(status="idle", detail=f"{exc} — no prices are produced")
        await redis.set(keys.source_state("oanda"), "not_configured")
        await asyncio.Event().wait()  # idle forever; nothing is fabricated
        return
    await redis.set(keys.source_state("oanda"), "configured")
    fc = FeedConsumer(redis, adapter, symbols)
    _state.update(status="degraded", detail="connecting")
    try:
        await asyncio.gather(fc.consume(), fc.clock(), fc.flush(), fc.refresh_typical_spreads())
    finally:
        await adapter.aclose()


def main() -> None:
    asyncio.run(run_service("stream", status, work))


if __name__ == "__main__":
    main()
