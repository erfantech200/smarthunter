from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from app.data.market_config import get_market_config, load_broker_profiles
from app.orchestrator.holidays import holiday_name
from app.orchestrator.market_hours import explain_gap, in_window, is_open, spread_bucket


def utc(*a: int) -> datetime:
    return datetime(*a, tzinfo=UTC)


def test_config_covers_every_asset() -> None:
    cfg = get_market_config()
    assert cfg.sources.oanda.symbols["BRENT"] == "BCO_USD"
    assert cfg.sources.dukascopy.terms_accepted is False


def test_broker_profile_defaults_are_unconfirmed_decimals() -> None:
    (p,) = load_broker_profiles()
    assert p.instruments["USDJPY"].pip.as_tuple().exponent == -2
    assert not any(s.confirmed for s in p.instruments.values())


@pytest.mark.parametrize(
    ("symbol", "t", "open_"),
    [
        ("EURUSD", utc(2026, 11, 7, 12), False),  # Saturday
        ("EURUSD", utc(2026, 11, 8, 21, 59), False),  # Sun 16:59 EST
        ("EURUSD", utc(2026, 11, 8, 22, 0), True),  # Sun 17:00 EST — FX week open
        ("EURUSD", utc(2026, 11, 13, 21, 59), True),  # Fri 16:59 EST
        ("EURUSD", utc(2026, 11, 13, 22, 0), False),  # Fri 17:00 EST — close
        ("XAUUSD", utc(2026, 11, 10, 22, 30), False),  # Tue 17:30 EST — metals daily break
        ("XAUUSD", utc(2026, 11, 10, 23, 10), True),  # Tue 18:10 EST
        ("BRENT", utc(2026, 7, 14, 21, 0), False),  # Tue 22:00 BST — Brent break
        ("BRENT", utc(2026, 7, 14, 21, 10), True),  # Tue 22:10 BST
    ],
)
def test_is_open(symbol: str, t: datetime, open_: bool) -> None:
    assert is_open(get_market_config().hours_for(symbol), t) is open_


def test_overlap_window_spans_two_timezones() -> None:
    w = get_market_config().session_windows["london_ny_overlap"]
    # November: NY open 08:00 EST = 13:00 UTC; London close 16:00 GMT = 16:00 UTC
    assert in_window(w, utc(2026, 11, 4, 13, 30))
    assert not in_window(w, utc(2026, 11, 4, 16, 0))
    # July: 12:00 UTC → 15:00 UTC
    assert in_window(w, utc(2026, 7, 15, 12, 0))
    assert not in_window(w, utc(2026, 7, 15, 15, 0))


def test_spread_buckets() -> None:
    cfg = get_market_config()
    assert spread_bucket(cfg, utc(2026, 11, 4, 14)) == "overlap"
    assert spread_bucket(cfg, utc(2026, 11, 4, 10)) == "london"
    assert spread_bucket(cfg, utc(2026, 11, 4, 2)) == "asia"
    assert spread_bucket(cfg, utc(2026, 11, 4, 22, 0)) == "rollover"  # 17:00 EST


def test_holidays() -> None:
    assert holiday_name(date(2026, 4, 3)) == "Good Friday"
    assert holiday_name(date(2026, 11, 26)) == "US Thanksgiving"
    assert holiday_name(date(2027, 12, 24)) is not None
    assert holiday_name(date(2026, 11, 4)) is None


def test_gap_explanations() -> None:
    fx = get_market_config().hours_for("EURUSD")
    assert explain_gap(fx, utc(2026, 11, 4, 12), utc(2026, 11, 4, 12, 20)) is None  # mid-week: real hole
    assert "Thanksgiving" in (explain_gap(fx, utc(2026, 11, 26, 18), utc(2026, 11, 26, 19)) or "")
    assert "scheduled" in (explain_gap(fx, utc(2026, 11, 8, 22, 0), utc(2026, 11, 8, 22, 10)) or "")
