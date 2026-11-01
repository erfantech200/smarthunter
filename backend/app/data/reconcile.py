"""Live bars vs provider bars (Phase 1 DoD "live bars match the provider's own bars").

The OANDA stream is throttled (~4 updates/s per instrument), so intra-minute extremes can be
missed; exact equality is impossible. Tolerances live in config/market.yaml → reconciliation.
"""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel

from app.data.market_config import Reconciliation
from app.data.models import Bar


class Mismatch(BaseModel):
    open_time: str
    field: str
    stream: Decimal
    provider: Decimal


class ReconciliationReport(BaseModel):
    instrument: str
    timeframe: str
    compared: int
    only_in_stream: int
    only_in_provider: int
    close_match_rate: Decimal
    high_low_within_tolerance_rate: Decimal
    tolerance: Decimal
    worst: list[Mismatch]
    passed: bool


def reconcile(
    stream: list[Bar], provider: list[Bar], typical_spread: Decimal, tol: Reconciliation
) -> ReconciliationReport:
    s = {b.open_time: b for b in stream}
    p = {b.open_time: b for b in provider}
    common = sorted(s.keys() & p.keys())
    tolerance = tol.high_low_tolerance_spreads * typical_spread
    close_ok = hl_ok = 0
    mismatches: list[tuple[Decimal, Mismatch]] = []
    for t in common:
        a, b = s[t], p[t]
        if a.bid_c == b.bid_c and a.ask_c == b.ask_c:
            close_ok += 1
        diffs = {f: abs(getattr(a, f) - getattr(b, f)) for f in ("bid_h", "bid_l", "ask_h", "ask_l")}
        if all(d <= tolerance for d in diffs.values()):
            hl_ok += 1
        for f, d in diffs.items():
            if d > tolerance:
                mismatches.append(
                    (d, Mismatch(open_time=t.isoformat(), field=f, stream=getattr(a, f), provider=getattr(b, f)))
                )
    n = len(common)
    cr = Decimal(close_ok) / n if n else Decimal(0)
    hr = Decimal(hl_ok) / n if n else Decimal(0)
    instrument = (stream or provider)[0].instrument if (stream or provider) else ""
    return ReconciliationReport(
        instrument=instrument,
        timeframe=(stream or provider)[0].timeframe.value if (stream or provider) else "",
        compared=n,
        only_in_stream=len(s.keys() - p.keys()),
        only_in_provider=len(p.keys() - s.keys()),
        close_match_rate=cr.quantize(Decimal("0.0001")),
        high_low_within_tolerance_rate=hr.quantize(Decimal("0.0001")),
        tolerance=tolerance,
        worst=[m for _, m in sorted(mismatches, key=lambda x: -x[0])[:10]],
        passed=n > 0 and cr >= tol.min_close_match_rate and hr >= tol.min_high_low_within_tolerance,
    )
