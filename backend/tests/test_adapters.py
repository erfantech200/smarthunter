from __future__ import annotations

import lzma
import struct
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import httpx
import orjson
import pytest

from app.core.config import REPO_ROOT
from app.data.adapters.base import AdapterAuthError, AdapterNotConfigured, AdapterRateLimited
from app.data.adapters.macro.fred import FredAdapter, parse_observations
from app.data.adapters.prices.dukascopy import DukascopyAdapter, decode_bi5, hour_url
from app.data.adapters.prices.oanda import CandleAlignmentError, OandaAdapter
from app.data.adapters.prices.twelvedata import TwelveDataAdapter
from app.data.market_config import get_market_config
from app.data.models import Heartbeat, Quote
from app.data.timeframes import Timeframe

RECORDING = REPO_ROOT / "tests" / "stream_recordings" / "synthetic_oanda_pricing.ndjson"


def utc(*a: int) -> datetime:
    return datetime(*a, tzinfo=UTC)


def _oanda(handler: Any, page_size: int = 5000) -> OandaAdapter:
    return OandaAdapter(
        "tok",
        "101-001-1",
        get_market_config().sources.oanda.symbols,
        transport=httpx.MockTransport(handler),
        page_size=page_size,
    )


async def test_oanda_stream_parses_recording_and_skips_unusable_lines() -> None:
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, content=RECORDING.read_bytes())

    a = _oanda(handler)
    items = [x async for x in a.stream(["EURUSD", "XAUUSD"])]
    await a.aclose()
    assert seen[0].url.host == "stream-fxpractice.oanda.com"
    assert seen[0].url.params["instruments"] == "EUR_USD,XAU_USD"
    assert seen[0].headers["Authorization"] == "Bearer tok"
    kinds = [type(x).__name__ for x in items]
    assert kinds == ["Quote", "Quote", "Heartbeat", "Quote", "Heartbeat"]  # empty book + unknown instrument dropped
    q0 = items[0]
    assert isinstance(q0, Quote)
    assert q0.instrument == "EURUSD" and q0.bid == Decimal("1.08012") and q0.ask == Decimal("1.08020")
    assert q0.time == utc(2026, 11, 4, 13, 0, 0, 123456)
    assert isinstance(items[2], Heartbeat)


async def test_oanda_auth_failure_is_typed() -> None:
    a = _oanda(lambda req: httpx.Response(401, json={"errorMessage": "Insufficient authorization"}))
    with pytest.raises(AdapterAuthError):
        _ = [x async for x in a.stream(["EURUSD"])]
    await a.aclose()


def test_oanda_requires_credentials() -> None:
    with pytest.raises(AdapterNotConfigured):
        OandaAdapter(None, None, {})


def _candle(t: datetime, px: str, complete: bool = True) -> dict[str, Any]:
    ohlc = {"o": px, "h": px, "l": px, "c": px}
    return {
        "time": t.isoformat().replace("+00:00", ".000000000Z"),
        "volume": 3,
        "complete": complete,
        "bid": ohlc,
        "ask": ohlc,
    }


async def test_oanda_candles_page_and_drop_incomplete() -> None:
    t0 = utc(2026, 11, 4, 13, 0)
    all_c = [_candle(t0 + timedelta(minutes=i), f"1.08{i:03d}") for i in range(5)]
    all_c[-1]["complete"] = False
    calls: list[dict[str, str]] = []

    def handler(req: httpx.Request) -> httpx.Response:
        p = dict(req.url.params)
        calls.append(p)
        frm = datetime.fromisoformat(p["from"].replace("Z", "+00:00"))
        rows = [c for c in all_c if datetime.fromisoformat(c["time"][:19] + "+00:00") >= frm]
        if p.get("includeFirst") == "false":
            rows = rows[1:]
        return httpx.Response(200, content=orjson.dumps({"candles": rows[: int(p["count"])]}))

    a = _oanda(handler, page_size=3)
    pages = [p async for p in a.candles("EURUSD", Timeframe.M1, t0, t0 + timedelta(hours=1))]
    await a.aclose()
    bars = [b for p in pages for b in p]
    assert [b.open_time for b in bars] == [t0 + timedelta(minutes=i) for i in range(4)]
    assert calls[0]["price"] == "BA" and calls[0]["dailyAlignment"] == "17" and "includeFirst" not in calls[0]
    assert calls[1]["includeFirst"] == "false"
    assert bars[0].close_time == t0 + timedelta(minutes=1)


async def test_oanda_misaligned_daily_candle_is_detected() -> None:
    a = _oanda(
        lambda req: httpx.Response(200, content=orjson.dumps({"candles": [_candle(utc(2026, 11, 4, 0, 0), "1.08")]}))
    )
    with pytest.raises(CandleAlignmentError):
        _ = [p async for p in a.candles("EURUSD", Timeframe.D1, utc(2026, 11, 3), utc(2026, 11, 5))]
    await a.aclose()


async def test_twelvedata_price_and_errors() -> None:
    syms = get_market_config().sources.twelvedata.symbols
    ok = TwelveDataAdapter(
        "k", syms, transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"price": "1.08017"}))
    )
    p = await ok.price("EURUSD")
    assert p.price == Decimal("1.08017")
    await ok.aclose()
    limited = TwelveDataAdapter(
        "k",
        syms,
        transport=httpx.MockTransport(
            lambda r: httpx.Response(200, json={"code": 429, "message": "credits exhausted", "status": "error"})
        ),
    )
    with pytest.raises(AdapterRateLimited):
        await limited.price("EURUSD")
    await limited.aclose()


def test_fred_point_in_time_and_missing_values() -> None:
    obs = parse_observations(
        "DGS10",
        {
            "observations": [
                {"realtime_start": "2026-11-03", "realtime_end": "9999-12-31", "date": "2026-11-02", "value": "4.21"},
                {"realtime_start": "2026-11-04", "realtime_end": "9999-12-31", "date": "2026-11-03", "value": "."},
            ]
        },
    )
    assert len(obs) == 1 and obs[0].value == Decimal("4.21")
    # first published 2026-11-03 → visible only from the end of that day in Chicago (05:59:59 UTC next day)
    assert obs[0].published_at == utc(2026, 11, 4, 5, 59, 59)
    assert obs[0].event_time < obs[0].published_at


async def test_fred_requests_initial_release_vintage() -> None:
    seen: list[httpx.Request] = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        return httpx.Response(200, json={"observations": []})

    f = FredAdapter("k", transport=httpx.MockTransport(handler))
    await f.observations("DGS2", date(2026, 1, 1))
    await f.aclose()
    assert seen[0].url.params["output_type"] == "4"


def _bi5(records: list[tuple[int, int, int]]) -> bytes:
    raw = b"".join(struct.pack(">3I2f", ms, ask, bid, 1.0, 1.0) for ms, ask, bid in records)
    return lzma.compress(raw, format=lzma.FORMAT_ALONE)


def test_dukascopy_decode_and_url() -> None:
    hour = utc(2026, 1, 5, 9)
    ticks = decode_bi5("EURUSD", hour, _bi5([(1500, 108020, 108012), (61000, 108025, 108017)]), 100000)
    assert ticks[0].time == utc(2026, 1, 5, 9, 0, 1, 500000)
    assert ticks[0].bid == Decimal("1.08012") and ticks[1].ask == Decimal("1.08025")
    assert decode_bi5("EURUSD", hour, b"", 100000) == []
    assert hour_url("EURUSD", hour).endswith("/EURUSD/2026/00/05/09h_ticks.bi5")  # zero-based month


def test_dukascopy_download_refuses_until_terms_accepted() -> None:
    cfg = get_market_config().sources.dukascopy
    with pytest.raises(AdapterNotConfigured, match="licence"):
        DukascopyAdapter(cfg.terms_accepted, cfg.symbols, cfg.price_divisor)


async def test_network_failure_becomes_adapter_error_and_unhealthy() -> None:
    def boom(req: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Name or service not known", request=req)

    f = FredAdapter("k", transport=httpx.MockTransport(boom))
    h = await f.health()
    await f.aclose()
    assert not h.ok and "ConnectError" in h.detail
