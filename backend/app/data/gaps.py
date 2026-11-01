"""Gap report (SPEC §6 A0 "candle gaps, session- and holiday-aware"; Phase 1 DoD "gap report clean or explained").

Expected bars are the minutes inside configured market hours. Missing runs shorter than
``gap_min_missing_m1`` are reported as "quiet" (no ticks printed — normal in thin hours), longer
runs as gaps, each either explained (holiday / edge of hours) or unexplained.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from pydantic import BaseModel

from app.core.time import ensure_utc
from app.data.market_config import MarketHoursGroup
from app.orchestrator.market_hours import explain_gap, is_open

MINUTE = timedelta(minutes=1)


class Gap(BaseModel):
    start: datetime
    end: datetime
    missing_bars: int
    explanation: str | None


class GapReport(BaseModel):
    instrument: str
    timeframe: str
    window_start: datetime
    window_end: datetime
    expected_bars: int
    present_bars: int
    quiet_runs: int
    gaps: list[Gap]

    @property
    def unexplained(self) -> list[Gap]:
        return [g for g in self.gaps if g.explanation is None]

    @property
    def clean_or_explained(self) -> bool:
        return not self.unexplained


def m1_gap_report(
    instrument: str, group: MarketHoursGroup, present: list[datetime], start: datetime, end: datetime, min_missing: int
) -> GapReport:
    start, end = ensure_utc(start), ensure_utc(end)
    have = {ensure_utc(p) for p in present}
    gaps: list[Gap] = []
    expected = quiet = 0
    run_start: datetime | None = None
    run_len = 0

    def flush(run_end: datetime) -> None:
        nonlocal quiet
        if run_start is None:
            return
        if run_len < min_missing:
            quiet += 1
        else:
            gaps.append(
                Gap(
                    start=run_start,
                    end=run_end,
                    missing_bars=run_len,
                    explanation=explain_gap(group, run_start, run_end),
                )
            )

    t = start.replace(second=0, microsecond=0)
    while t < end:
        if is_open(group, t):
            expected += 1
            if t in have:
                flush(t)
                run_start, run_len = None, 0
            else:
                if run_start is None:
                    run_start = t
                run_len += 1
        else:
            flush(t)
            run_start, run_len = None, 0
        t += MINUTE
    flush(end)
    return GapReport(
        instrument=instrument,
        timeframe="M1",
        window_start=start,
        window_end=end,
        expected_bars=expected,
        present_bars=len(have),
        quiet_runs=quiet,
        gaps=gaps,
    )
