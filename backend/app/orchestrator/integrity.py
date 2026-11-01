"""Data Integrity Gate (SPEC §6 A0). Combines the stream watchdog, the cross-source check and macro
freshness into one ``IntegrityReport``. Gaps and live-vs-provider reconciliation run as periodic
reports (``app.data.gaps``, ``app.data.reconcile``) and are summarised here when present.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal

from pydantic import BaseModel

from app.core.time import ensure_utc
from app.data.adapters.prices.twelvedata import ReferencePrice
from app.data.market_config import MarketConfig
from app.data.models import Quote
from app.orchestrator.integrity_model import IntegrityReport, Issue, Status
from app.orchestrator.market_hours import is_open
from app.stream.watchdog import StreamStatus

MAX_PRIMARY_AGE = timedelta(seconds=60)


class CrossCheckResult(BaseModel):
    instrument: str
    checked_at: datetime
    primary_mid: Decimal | None
    primary_time: datetime | None
    reference_price: Decimal
    reference_source: str
    diff: Decimal | None
    tolerance: Decimal | None
    ok: bool
    note: str = ""


def cross_source_check(
    primary: Quote | None, ref: ReferencePrice, typical_spread: Decimal | None, tolerance_spreads: Decimal
) -> CrossCheckResult:
    base = {
        "instrument": ref.instrument,
        "checked_at": ref.observed_at,
        "reference_price": ref.price,
        "reference_source": ref.source,
    }
    if primary is None or ref.observed_at - primary.time > MAX_PRIMARY_AGE:
        return CrossCheckResult(
            **base,
            primary_mid=primary.mid if primary else None,
            primary_time=primary.time if primary else None,
            diff=None,
            tolerance=None,
            ok=False,
            note="no fresh primary quote to compare",
        )
    spread = typical_spread or primary.spread
    tol = tolerance_spreads * spread
    diff = abs(primary.mid - ref.price)
    return CrossCheckResult(
        **base,
        primary_mid=primary.mid,
        primary_time=primary.time,
        diff=diff,
        tolerance=tol,
        ok=diff <= tol,
        note="" if diff <= tol else "sources disagree beyond tolerance",
    )


def assemble_live_report(
    now: datetime,
    cfg: MarketConfig,
    stream: StreamStatus | None,
    cross_checks: dict[str, CrossCheckResult],
    macro_latest: dict[str, datetime],
) -> IntegrityReport:
    now = ensure_utc(now)
    ic = cfg.integrity
    issues: list[Issue] = []
    stale: list[str] = []

    # 1. stream (seconds)
    if stream is None or now - stream.as_of > timedelta(seconds=ic.stream_heartbeat_critical_seconds):
        issues.append(
            Issue(
                check="stream",
                severity=Status.CRITICAL,
                source=cfg.primary_price_source,
                message="stream service is not reporting",
            )
        )
        stale.append(cfg.primary_price_source)
    else:
        issues.extend(stream.issues)
        if any(i.check == "stream" for i in stream.issues):
            stale.append(cfg.primary_price_source)

    # 2. cross-source (minutes)
    for sym in cfg.sources.twelvedata.cross_check.symbols:
        if not is_open(cfg.hours_for(sym), now):
            continue
        r = cross_checks.get(sym)
        if r is None or now - r.checked_at > timedelta(seconds=ic.cross_check_max_age_seconds):
            issues.append(
                Issue(
                    check="cross_source",
                    severity=Status.DEGRADED,
                    instrument=sym,
                    source="twelvedata",
                    message="no recent cross-source check",
                )
            )
            stale.append("twelvedata")
        elif not r.ok:
            issues.append(
                Issue(
                    check="cross_source",
                    severity=Status.DEGRADED,
                    instrument=sym,
                    source="twelvedata",
                    message=r.note,
                    data=r.model_dump(mode="json"),
                )
            )

    # 3. macro (days)
    for series in cfg.sources.fred.series:
        published = macro_latest.get(series)
        if published is None:
            issues.append(
                Issue(
                    check="macro_freshness", severity=Status.DEGRADED, source="fred", message=f"{series} never fetched"
                )
            )
            stale.append("fred")
        elif now - published > timedelta(days=ic.macro_stale_days):
            issues.append(
                Issue(
                    check="macro_freshness",
                    severity=Status.DEGRADED,
                    source="fred",
                    message=f"{series} last published {published.date().isoformat()}",
                )
            )
            stale.append("fred")
    return IntegrityReport.from_issues(now, issues, stale)
