from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from hypothesis import given, settings
from hypothesis import strategies as st

from app.data.models import Bar
from app.data.timeframes import Timeframe
from app.stream.bar_builder import BarBuilder
from tests.factories import q, random_walk, utc

D = Decimal


def test_m1_ohlc_from_quotes() -> None:
    b = BarBuilder([Timeframe.M1])
    t0 = utc(2026, 11, 4, 13, 0)
    for s, bid, ask in [
        (1, "1.1000", "1.1002"),
        (20, "1.1005", "1.1007"),
        (40, "1.0995", "1.0997"),
        (59, "1.1001", "1.1003"),
    ]:
        assert b.on_quote(q(t0 + timedelta(seconds=s), bid, ask)) == []
    (bar,) = b.on_quote(q(t0 + timedelta(seconds=61), "1.1002", "1.1004"))
    assert (bar.bid_o, bar.bid_h, bar.bid_l, bar.bid_c) == (D("1.1000"), D("1.1005"), D("1.0995"), D("1.1001"))
    assert (bar.ask_o, bar.ask_h, bar.ask_l, bar.ask_c) == (D("1.1002"), D("1.1007"), D("1.0997"), D("1.1003"))
    assert bar.volume == 4 and bar.complete and bar.open_time == t0 and bar.close_time == t0 + timedelta(minutes=1)


def test_clock_closes_quiet_minute_only_after_grace() -> None:
    b = BarBuilder([Timeframe.M1], grace=timedelta(seconds=2))
    t0 = utc(2026, 11, 4, 13, 0)
    b.on_quote(q(t0 + timedelta(seconds=5), "1.1", "1.1002"))
    assert b.on_clock(t0 + timedelta(seconds=61)) == []  # inside grace
    assert len(b.on_clock(t0 + timedelta(seconds=62))) == 1


def test_late_quote_for_closed_bucket_is_dropped_and_counted() -> None:
    b = BarBuilder([Timeframe.M1])
    t0 = utc(2026, 11, 4, 13, 0)
    b.on_quote(q(t0 + timedelta(seconds=5), "1.1", "1.1002"))
    b.on_clock(t0 + timedelta(seconds=63))
    assert b.on_quote(q(t0 + timedelta(seconds=59), "1.2", "1.2002")) == []
    assert b.late_quotes("EURUSD") == 1
    assert b.current("EURUSD", Timeframe.M1) is None


def test_rollups_match_m1_aggregation() -> None:
    quotes = random_walk(utc(2026, 11, 4, 12, 58), 2000, seed=7)
    b = BarBuilder()
    bars: list[Bar] = []
    for x in quotes:
        bars += b.on_quote(x)
    bars += b.on_clock(quotes[-1].time + timedelta(days=8))
    m1 = [x for x in bars if x.timeframe is Timeframe.M1]
    for m5 in (x for x in bars if x.timeframe is Timeframe.M5):
        parts = [x for x in m1 if m5.open_time <= x.open_time < m5.close_time]
        assert m5.bid_o == parts[0].bid_o and m5.bid_c == parts[-1].bid_c
        assert m5.bid_h == max(p.bid_h for p in parts) and m5.ask_l == min(p.ask_l for p in parts)
        assert m5.volume == sum(p.volume for p in parts)
    assert any(x.timeframe is Timeframe.H1 for x in bars)


def test_emission_never_precedes_close_time() -> None:
    """A bar is only emitted when the builder has observed time ≥ its close (no lookahead)."""
    b = BarBuilder()
    for x in random_walk(utc(2026, 11, 4, 12, 0), 1500, seed=3):
        for bar in b.on_quote(x):
            assert bar.close_time <= x.time


@settings(max_examples=40, deadline=None)
@given(seed=st.integers(0, 10_000), cut=st.integers(300, 1450))
def test_lookahead_bars_identical_with_or_without_future_data(seed: int, cut: int) -> None:
    """SPEC §22 lookahead test: closed bars as of t are identical whether or not data after t exists."""
    quotes = random_walk(utc(2026, 11, 4, 12, 0), 1500, seed=seed)
    t = quotes[cut].time

    def run(qs: list, until: datetime) -> list[Bar]:  # type: ignore[type-arg]
        b = BarBuilder()
        out: list[Bar] = []
        for x in qs:
            out += b.on_quote(x)
        out += b.on_clock(until)
        return out

    end = quotes[-1].time + timedelta(days=8)
    truncated = [x for x in run([x for x in quotes if x.time <= t], end) if x.close_time <= t]
    full = [x for x in run(quotes, end) if x.close_time <= t]
    assert truncated  # the property is not vacuous
    key = lambda bar: (bar.timeframe, bar.open_time)  # noqa: E731
    assert sorted(truncated, key=key) == sorted(full, key=key)


def test_replay_is_deterministic() -> None:
    quotes = random_walk(utc(2026, 11, 4, 12, 0), 800, seed=11)

    def run() -> list[Bar]:
        b = BarBuilder()
        return [bar for x in quotes for bar in b.on_quote(x)]

    assert run() == run()
