"""Bar builder: quotes → M1 bid/ask bars → M5 … W1 roll-ups (SPEC §4 ingestion, §12).

Deterministic and clock-injected so it is replayable: the same quotes and clock ticks always
produce the same bars. A bar is emitted only once the builder has *seen* time pass its
``close_time`` (via a later quote or ``on_clock``) — never earlier, so consumers cannot see a
bar before it was complete (no lookahead, SPEC §3.5).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal

from app.core.time import ensure_utc
from app.data.models import Bar, Quote
from app.data.timeframes import ORDER, Timeframe, bucket_bounds

DEFAULT_GRACE = timedelta(seconds=2)  # wait this long after a bucket ends for late-stamped quotes


@dataclass
class _Working:
    open_time: datetime
    close_time: datetime
    bid: list[Decimal]  # o, h, l, c
    ask: list[Decimal]
    volume: int

    @classmethod
    def from_quote(cls, q: Quote, bounds: tuple[datetime, datetime]) -> _Working:
        return cls(bounds[0], bounds[1], [q.bid] * 4, [q.ask] * 4, 1)

    @classmethod
    def from_bar(cls, b: Bar, bounds: tuple[datetime, datetime]) -> _Working:
        return cls(
            bounds[0], bounds[1], [b.bid_o, b.bid_h, b.bid_l, b.bid_c], [b.ask_o, b.ask_h, b.ask_l, b.ask_c], b.volume
        )

    def add_quote(self, q: Quote) -> None:
        for side, px in ((self.bid, q.bid), (self.ask, q.ask)):
            side[1], side[2], side[3] = max(side[1], px), min(side[2], px), px
        self.volume += 1

    def add_bar(self, b: Bar) -> None:
        for side, (h, low, c) in ((self.bid, (b.bid_h, b.bid_l, b.bid_c)), (self.ask, (b.ask_h, b.ask_l, b.ask_c))):
            side[1], side[2], side[3] = max(side[1], h), min(side[2], low), c
        self.volume += b.volume

    def to_bar(self, instrument: str, tf: Timeframe, complete: bool) -> Bar:
        bo, bh, bl, bc = self.bid
        ao, ah, al, ac = self.ask
        return Bar(
            instrument=instrument,
            timeframe=tf,
            open_time=self.open_time,
            close_time=self.close_time,
            bid_o=bo,
            bid_h=bh,
            bid_l=bl,
            bid_c=bc,
            ask_o=ao,
            ask_h=ah,
            ask_l=al,
            ask_c=ac,
            volume=self.volume,
            complete=complete,
            source="stream",
        )


@dataclass
class _InstrumentState:
    working: dict[Timeframe, _Working] = field(default_factory=dict)
    last_quote_time: datetime | None = None
    closed_until: datetime | None = None  # end of the last emitted M1 bar
    late_quotes: int = 0


class BarBuilder:
    def __init__(self, timeframes: list[Timeframe] | None = None, grace: timedelta = DEFAULT_GRACE) -> None:
        tfs = sorted(set(timeframes or ORDER) | {Timeframe.M1}, key=ORDER.index)
        self.timeframes = tfs
        self.higher = [tf for tf in tfs if tf is not Timeframe.M1]
        self.grace = grace
        self._state: dict[str, _InstrumentState] = {}

    def _st(self, instrument: str) -> _InstrumentState:
        return self._state.setdefault(instrument, _InstrumentState())

    def late_quotes(self, instrument: str) -> int:
        return self._st(instrument).late_quotes

    # ------------------------------------------------------------------ inputs
    def on_quote(self, q: Quote) -> list[Bar]:
        st = self._st(q.instrument)
        out = self._close_due(q.instrument, q.time, grace=timedelta(0))
        m1 = st.working.get(Timeframe.M1)
        late = (st.closed_until is not None and q.time < st.closed_until) or (
            st.last_quote_time is not None and q.time < st.last_quote_time
        )
        if late:
            st.late_quotes += 1  # out of order or for an already-closed bucket: dropped, counted
            return out
        if m1 is None:
            st.working[Timeframe.M1] = _Working.from_quote(q, bucket_bounds(q.time, Timeframe.M1))
        else:
            m1.add_quote(q)
        st.last_quote_time = q.time
        return out

    def on_clock(self, now: datetime) -> list[Bar]:
        """Close every bucket that ended at least ``grace`` ago. Call about once a second."""
        now = ensure_utc(now)
        out: list[Bar] = []
        for instrument in sorted(self._state):
            out.extend(self._close_due(instrument, now, grace=self.grace))
        return out

    # ------------------------------------------------------------------ outputs
    def current(self, instrument: str, tf: Timeframe) -> Bar | None:
        """The in-progress (incomplete) bar, for display only — never fed to decisions."""
        w = self._st(instrument).working.get(tf)
        return None if w is None else w.to_bar(instrument, tf, complete=False)

    # ------------------------------------------------------------------ internals
    def _close_due(self, instrument: str, now: datetime, grace: timedelta) -> list[Bar]:
        st = self._st(instrument)
        out: list[Bar] = []
        m1 = st.working.get(Timeframe.M1)
        if m1 is not None and now >= m1.close_time + grace:
            bar = m1.to_bar(instrument, Timeframe.M1, complete=True)
            del st.working[Timeframe.M1]
            st.closed_until = bar.close_time
            out.append(bar)
            out.extend(self._roll_up(instrument, bar))
        for tf in self.higher:  # quiet periods: close higher buckets whose end has passed
            w = st.working.get(tf)
            if w is not None and now >= w.close_time + grace:
                out.append(w.to_bar(instrument, tf, complete=True))
                del st.working[tf]
        return out

    def _roll_up(self, instrument: str, m1: Bar) -> list[Bar]:
        st = self._st(instrument)
        out: list[Bar] = []
        for tf in self.higher:
            bounds = bucket_bounds(m1.open_time, tf)
            w = st.working.get(tf)
            if w is not None and w.open_time != bounds[0]:  # a new bucket began without the old one closing
                out.append(w.to_bar(instrument, tf, complete=True))
                w = None
            if w is None:
                w = st.working[tf] = _Working.from_bar(m1, bounds)
            else:
                w.add_bar(m1)
            if m1.close_time >= w.close_time:
                out.append(w.to_bar(instrument, tf, complete=True))
                del st.working[tf]
        return out
