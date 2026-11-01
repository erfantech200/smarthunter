"""Stream watchdog (SPEC §6 A0, §3.7): detects a dead or unhealthy stream within seconds.

Pure state machine with an injected clock. The feed consumer calls ``on_message`` for every
line it reads (prices *and* heartbeats), ``on_quote`` for prices and ``on_disconnect`` when the
connection drops. ``status(now)`` is published to Redis every second; A12 halts on CRITICAL.
"""

from __future__ import annotations

import statistics
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal

from pydantic import BaseModel

from app.core.time import ensure_utc
from app.data.market_config import MarketConfig
from app.data.models import Bar, Quote
from app.orchestrator.integrity_model import Issue, Status, worst
from app.orchestrator.market_hours import is_open

ATR_PERIOD = 14
SPREAD_WINDOW = 500


class StreamStatus(BaseModel):
    as_of: datetime
    status: Status
    connected: bool
    last_message_age_seconds: float | None
    issues: list[Issue]
    per_instrument: dict[str, Status]


@dataclass
class _Inst:
    last_quote: Quote | None = None
    spreads: deque[Decimal] = field(default_factory=lambda: deque(maxlen=SPREAD_WINDOW))
    true_ranges: deque[Decimal] = field(default_factory=lambda: deque(maxlen=ATR_PERIOD))
    prev_close: Decimal | None = None
    suspect: Issue | None = None


class StreamWatchdog:
    def __init__(self, cfg: MarketConfig, instruments: list[str], source: str = "oanda") -> None:
        self.cfg = cfg
        self.source = source
        self.instruments = instruments
        self.connected = False
        self.last_message: datetime | None = None
        self.disconnects = 0
        self._inst = {s: _Inst() for s in instruments}
        self.typical_spread: dict[str, Decimal] = {}  # from spreads_by_session when available

    # ------------------------------------------------------------------ events
    def on_connect(self, now: datetime) -> None:
        self.connected = True
        self.last_message = ensure_utc(now)

    def on_disconnect(self) -> None:
        if self.connected:
            self.disconnects += 1
        self.connected = False

    def on_message(self, now: datetime) -> None:
        self.last_message = ensure_utc(now)

    def on_bar(self, bar: Bar) -> None:
        """Closed M1 bars feed a mid-price ATR(14) used for the outlier check."""
        st = self._inst.get(bar.instrument)
        if st is None:
            return
        h, low, c = bar.mid_h, bar.mid_l, bar.mid_c
        tr = h - low if st.prev_close is None else max(h - low, abs(h - st.prev_close), abs(low - st.prev_close))
        st.true_ranges.append(tr)
        st.prev_close = c

    def on_quote(self, q: Quote) -> Issue | None:
        """Record a quote; returns an outlier Issue when the move needs second-source confirmation."""
        st = self._inst.get(q.instrument)
        if st is None:
            return None
        if q.spread > 0:
            st.spreads.append(q.spread)
        issue = None
        atr = self.atr(q.instrument)
        if st.last_quote is not None and atr is not None and atr > 0:
            move = abs(q.mid - st.last_quote.mid)
            if move > self.cfg.integrity.outlier_k_atr * atr:
                issue = Issue(
                    check="outlier",
                    severity=Status.DEGRADED,
                    instrument=q.instrument,
                    source=self.source,
                    message=f"tick moved {move} (> {self.cfg.integrity.outlier_k_atr}×ATR {atr}); "
                    "awaiting second-source confirmation",
                    data={"from": str(st.last_quote.mid), "to": str(q.mid), "at": q.time.isoformat()},
                )
                st.suspect = issue
        st.last_quote = q
        return issue

    def resolve_outlier(self, instrument: str, confirmed: bool) -> None:
        st = self._inst[instrument]
        if st.suspect is None:
            return
        if confirmed:
            st.suspect = None
        else:
            st.suspect = st.suspect.model_copy(update={"message": st.suspect.message + " — second source DISAGREES"})

    # ------------------------------------------------------------------ queries
    def atr(self, instrument: str) -> Decimal | None:
        trs = self._inst[instrument].true_ranges
        return sum(trs, Decimal(0)) / len(trs) if len(trs) == ATR_PERIOD else None

    def typical(self, instrument: str) -> Decimal | None:
        if instrument in self.typical_spread:
            return self.typical_spread[instrument]
        sp = self._inst[instrument].spreads
        return Decimal(statistics.median(sp)) if len(sp) >= 20 else None

    def last_quote(self, instrument: str) -> Quote | None:
        return self._inst[instrument].last_quote

    def status(self, now: datetime) -> StreamStatus:
        now = ensure_utc(now)
        ic = self.cfg.integrity
        issues: list[Issue] = []
        age = (now - self.last_message).total_seconds() if self.last_message else None
        if not self.connected:
            issues.append(
                Issue(check="stream", severity=Status.CRITICAL, source=self.source, message="price stream disconnected")
            )
        elif age is None or age > ic.stream_heartbeat_critical_seconds:
            issues.append(
                Issue(
                    check="stream",
                    severity=Status.CRITICAL,
                    source=self.source,
                    message=f"no stream message for {age:.0f}s" if age else "no stream message yet",
                    data={"age_seconds": age},
                )
            )
        per: dict[str, Status] = {}
        for sym, st in self._inst.items():
            own: list[Issue] = []
            market_open = is_open(self.cfg.hours_for(sym), now)
            q = st.last_quote
            if market_open:
                if q is None:
                    own.append(
                        Issue(
                            check="freshness",
                            severity=Status.DEGRADED,
                            instrument=sym,
                            source=self.source,
                            message="no quote received yet",
                        )
                    )
                elif (now - q.time) > timedelta(seconds=ic.quote_stale_seconds):
                    own.append(
                        Issue(
                            check="freshness",
                            severity=Status.DEGRADED,
                            instrument=sym,
                            source=self.source,
                            message=f"last quote {(now - q.time).total_seconds():.0f}s ago",
                        )
                    )
            if q is not None:
                typ = self.typical(sym)
                if q.spread <= 0:
                    own.append(
                        Issue(
                            check="spread",
                            severity=Status.CRITICAL,
                            instrument=sym,
                            source=self.source,
                            message=f"non-positive spread {q.spread} (crossed or locked quote)",
                        )
                    )
                elif typ and q.spread > ic.spread_max_multiple * typ:
                    own.append(
                        Issue(
                            check="spread",
                            severity=Status.DEGRADED,
                            instrument=sym,
                            source=self.source,
                            message=f"spread {q.spread} > {ic.spread_max_multiple}× typical {typ}",
                        )
                    )
            if st.suspect is not None:
                own.append(st.suspect)
            issues.extend(own)
            stream_level = worst(*(i.severity for i in issues if i.instrument is None))
            per[sym] = worst(stream_level, *(i.severity for i in own))
        return StreamStatus(
            as_of=now,
            status=worst(*(i.severity for i in issues)),
            connected=self.connected,
            last_message_age_seconds=age,
            issues=issues,
            per_instrument=per,
        )
