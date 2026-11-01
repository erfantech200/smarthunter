from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from app.data.market_config import get_market_config
from app.data.models import Bar
from app.data.timeframes import Timeframe
from app.orchestrator.integrity_model import Status
from app.stream.watchdog import StreamWatchdog
from tests.factories import q, utc

T0 = utc(2026, 11, 4, 13, 0)  # Wednesday, all markets open


def _wd() -> StreamWatchdog:
    return StreamWatchdog(get_market_config(), ["EURUSD"])


def test_disconnect_is_critical_immediately() -> None:
    wd = _wd()
    wd.on_connect(T0)
    wd.on_quote(q(T0, "1.1", "1.1001"))
    assert wd.status(T0).status is Status.OK
    wd.on_disconnect()
    s = wd.status(T0 + timedelta(seconds=1))
    assert s.status is Status.CRITICAL and s.per_instrument["EURUSD"] is Status.CRITICAL


def test_silent_stream_is_critical_within_seconds() -> None:
    wd = _wd()
    wd.on_connect(T0)
    wd.on_quote(q(T0, "1.1", "1.1001"))
    wd.on_message(T0)
    assert wd.status(T0 + timedelta(seconds=14)).status is Status.OK
    assert wd.status(T0 + timedelta(seconds=16)).status is Status.CRITICAL


def test_stale_instrument_degraded_only_while_market_open() -> None:
    wd = _wd()
    sat = utc(2026, 11, 7, 12)
    wd.on_connect(sat)
    wd.on_message(sat)
    assert wd.status(sat).status is Status.OK  # weekend: no quotes expected
    wd.on_connect(T0)
    wd.on_message(T0)
    assert wd.status(T0).per_instrument["EURUSD"] is Status.DEGRADED  # open, no quote yet


def test_crossed_quote_is_critical_and_wide_spread_degraded() -> None:
    wd = _wd()
    wd.on_connect(T0)
    wd.typical_spread["EURUSD"] = Decimal("0.0001")
    wd.on_quote(q(T0, "1.1000", "1.1006"))
    assert wd.status(T0).per_instrument["EURUSD"] is Status.DEGRADED
    wd.on_quote(q(T0, "1.1001", "1.1000"))
    assert wd.status(T0).per_instrument["EURUSD"] is Status.CRITICAL


def _bar(i: int, lo: str, hi: str) -> Bar:
    s = T0 - timedelta(minutes=20 - i)
    return Bar(
        instrument="EURUSD",
        timeframe=Timeframe.M1,
        open_time=s,
        close_time=s + timedelta(minutes=1),
        bid_o=Decimal(lo),
        bid_h=Decimal(hi),
        bid_l=Decimal(lo),
        bid_c=Decimal(lo),
        ask_o=Decimal(lo),
        ask_h=Decimal(hi),
        ask_l=Decimal(lo),
        ask_c=Decimal(lo),
        volume=1,
        complete=True,
        source="test",
    )


def test_outlier_needs_second_source() -> None:
    wd = _wd()
    wd.on_connect(T0)
    for i in range(14):
        wd.on_bar(_bar(i, "1.1000", "1.1002"))  # ATR = 0.0002
    wd.on_quote(q(T0, "1.1000", "1.1001"))
    assert wd.on_quote(q(T0, "1.1010", "1.1011")) is None  # 0.0010 < 8 × 0.0002
    issue = wd.on_quote(q(T0, "1.1050", "1.1051"))  # 0.0040 > 0.0016
    assert issue is not None and wd.status(T0).per_instrument["EURUSD"] is Status.DEGRADED
    wd.resolve_outlier("EURUSD", confirmed=True)
    assert wd.status(T0).per_instrument["EURUSD"] is Status.OK
