from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from app.data.adapters.prices.twelvedata import ReferencePrice
from app.data.gaps import m1_gap_report
from app.data.market_config import get_market_config
from app.data.models import Bar
from app.data.reconcile import reconcile
from app.data.spreads import spread_stats
from app.data.timeframes import Timeframe
from app.orchestrator.integrity import assemble_live_report, cross_source_check
from app.orchestrator.integrity_model import Status
from app.stream.watchdog import StreamWatchdog
from tests.factories import q, utc

D = Decimal
WED = utc(2026, 11, 4, 12, 0)


def _m1(t: datetime, bid: str = "1.1000", ask: str = "1.1001", hi: str | None = None) -> Bar:
    h = D(hi) if hi else D(bid)
    return Bar(
        instrument="EURUSD",
        timeframe=Timeframe.M1,
        open_time=t,
        close_time=t + timedelta(minutes=1),
        bid_o=D(bid),
        bid_h=h,
        bid_l=D(bid),
        bid_c=D(bid),
        ask_o=D(ask),
        ask_h=max(h, D(ask)),
        ask_l=D(ask),
        ask_c=D(ask),
        volume=1,
        complete=True,
        source="oanda",
    )


# ---------------------------------------------------------------- gaps
def test_gap_report_separates_quiet_runs_real_gaps_and_closures() -> None:
    fx = get_market_config().hours_for("EURUSD")
    start, end = utc(2026, 11, 6, 20, 0), utc(2026, 11, 9, 0, 0)  # Fri 15:00 EST → Sun 19:00 EST
    present = [start + timedelta(minutes=i) for i in range(int((end - start).total_seconds() // 60))]
    hole = {start + timedelta(minutes=10 + i) for i in range(20)}  # 20-minute unexplained hole on Friday
    quiet = {start + timedelta(minutes=40 + i) for i in range(2)}
    present = [p for p in present if p not in hole | quiet]
    r = m1_gap_report("EURUSD", fx, present, start, end, min_missing=5)
    assert r.quiet_runs == 1
    assert len(r.unexplained) == 1 and r.unexplained[0].missing_bars == 20
    assert not r.clean_or_explained
    # weekend minutes are not expected at all
    assert r.expected_bars == 120 + 120  # Fri 15:00–17:00 + Sun 17:00–19:00


def test_gap_report_clean_week() -> None:
    fx = get_market_config().hours_for("EURUSD")
    start = utc(2026, 11, 4, 0)
    present = [start + timedelta(minutes=i) for i in range(24 * 60)]
    assert m1_gap_report("EURUSD", fx, present, start, start + timedelta(days=1), 5).clean_or_explained


# ---------------------------------------------------------------- spreads
def test_spread_stats_by_session() -> None:
    cfg = get_market_config()
    bars = [_m1(utc(2026, 11, 4, 14, i), "1.1000", "1.1001") for i in range(10)]  # overlap
    bars += [_m1(utc(2026, 11, 4, 2, i), "1.1000", "1.1003") for i in range(10)]  # asia
    s = spread_stats(cfg, bars)
    assert s["overlap"]["median"] == D("0.0001") and s["asia"]["median"] == D("0.0003")
    assert s["overlap"]["samples"] == 10


# ---------------------------------------------------------------- reconciliation
def test_reconciliation_tolerance() -> None:
    tol = get_market_config().reconciliation
    prov = [_m1(WED + timedelta(minutes=i), hi="1.1004") for i in range(100)]
    live = [_m1(WED + timedelta(minutes=i), hi="1.1004" if i else "1.1003") for i in range(100)]  # 1 bar missed a high
    r = reconcile(live, prov, D("0.0001"), tol)
    assert r.passed and r.close_match_rate == 1 and r.compared == 100
    bad = [_m1(WED + timedelta(minutes=i), bid="1.1002", ask="1.1003", hi="1.1004") for i in range(100)]
    assert not reconcile(bad, prov, D("0.0001"), tol).passed


# ---------------------------------------------------------------- cross-source + report
def test_cross_source_check() -> None:
    primary = q(WED, "1.08000", "1.08010")
    ok = cross_source_check(
        primary, ReferencePrice(instrument="EURUSD", price=D("1.08020"), observed_at=WED), D("0.0001"), D(3)
    )
    assert ok.ok and ok.diff == D("0.00015")
    bad = cross_source_check(
        primary, ReferencePrice(instrument="EURUSD", price=D("1.0850"), observed_at=WED), D("0.0001"), D(3)
    )
    assert not bad.ok
    stale = cross_source_check(
        primary,
        ReferencePrice(instrument="EURUSD", price=D("1.08"), observed_at=WED + timedelta(minutes=5)),
        None,
        D(3),
    )
    assert not stale.ok and "no fresh primary" in stale.note


def test_live_report_statuses() -> None:
    cfg = get_market_config()
    fresh_macro = {s: WED - timedelta(days=1) for s in cfg.sources.fred.series}
    assert assemble_live_report(WED, cfg, None, {}, fresh_macro).status is Status.CRITICAL  # no stream service

    wd = StreamWatchdog(cfg, ["EURUSD"])
    wd.on_connect(WED)
    wd.on_quote(q(WED, "1.08000", "1.08010"))
    stream = wd.status(WED)
    check = cross_source_check(
        wd.last_quote("EURUSD"), ReferencePrice(instrument="EURUSD", price=D("1.08005"), observed_at=WED), None, D(3)
    )
    report = assemble_live_report(WED, cfg, stream, {"EURUSD": check}, fresh_macro)
    assert report.status is Status.OK, report.issues

    report = assemble_live_report(WED, cfg, stream, {}, {})
    assert report.status is Status.DEGRADED
    assert set(report.stale_sources) == {"twelvedata", "fred"}
