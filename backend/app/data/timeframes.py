"""Timeframes and bucket alignment.

Alignment matches OANDA's candle defaults so our stream-built bars can be reconciled with theirs:
M1–H1 align to clock boundaries; H4 and D1 align to 17:00 America/New_York (``dailyAlignment=17``,
``alignmentTimezone=America/New_York``); W1 starts Friday 17:00 New York (``weeklyAlignment=Friday``).
Daily-aligned boundaries are computed in New York *wall time*, so DST changes move them in UTC
exactly as the provider does. Returned times are UTC.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from enum import StrEnum
from zoneinfo import ZoneInfo

from app.core.time import ensure_utc

NY = ZoneInfo("America/New_York")
DAILY_ALIGNMENT_HOUR = 17
H4_HOURS = tuple(sorted((DAILY_ALIGNMENT_HOUR + 4 * k) % 24 for k in range(6)))  # (1, 5, 9, 13, 17, 21)
FRIDAY = 4


class Timeframe(StrEnum):
    M1 = "M1"
    M5 = "M5"
    M15 = "M15"
    H1 = "H1"
    H4 = "H4"
    D1 = "D1"
    W1 = "W1"

    @property
    def oanda(self) -> str:
        return {"D1": "D", "W1": "W"}.get(self.value, self.value)

    @property
    def nominal(self) -> timedelta:
        return _NOMINAL[self]

    @property
    def clock_aligned(self) -> bool:
        return self in (Timeframe.M1, Timeframe.M5, Timeframe.M15, Timeframe.H1)


_NOMINAL = {
    Timeframe.M1: timedelta(minutes=1),
    Timeframe.M5: timedelta(minutes=5),
    Timeframe.M15: timedelta(minutes=15),
    Timeframe.H1: timedelta(hours=1),
    Timeframe.H4: timedelta(hours=4),
    Timeframe.D1: timedelta(days=1),
    Timeframe.W1: timedelta(weeks=1),
}
ORDER = list(Timeframe)


def _ny_wall(d: datetime, hour: int) -> datetime:
    """UTC instant of New York wall time ``hour``:00 on the calendar date of ``d`` (a NY-local datetime)."""
    return datetime(d.year, d.month, d.day, hour, tzinfo=NY).astimezone(UTC)


def bucket_start(t: datetime, tf: Timeframe) -> datetime:
    t = ensure_utc(t)
    if tf.clock_aligned:
        step = int(tf.nominal.total_seconds())
        epoch = int(t.timestamp())
        return datetime.fromtimestamp(epoch - epoch % step, tz=UTC)
    local = t.astimezone(NY)
    if tf is Timeframe.H4:
        candidates = [h for h in H4_HOURS if _ny_wall(local, h) <= t]
        if candidates:
            return _ny_wall(local, max(candidates))
        return _ny_wall(local - timedelta(days=1), H4_HOURS[-1])
    # D1 / W1: most recent 17:00 NY at or before t
    day_start = _ny_wall(local, DAILY_ALIGNMENT_HOUR)
    if day_start > t:
        day_start = _ny_wall(local - timedelta(days=1), DAILY_ALIGNMENT_HOUR)
    if tf is Timeframe.D1:
        return day_start
    ds_local = day_start.astimezone(NY)
    back = (ds_local.weekday() - FRIDAY) % 7
    return _ny_wall(ds_local - timedelta(days=back), DAILY_ALIGNMENT_HOUR)


def bucket_end(start: datetime, tf: Timeframe) -> datetime:
    """End of the bucket that starts at ``start`` (the next bucket's start)."""
    start = ensure_utc(start)
    if tf.clock_aligned:
        return start + tf.nominal
    local = start.astimezone(NY)
    if tf is Timeframe.H4:
        nxt = local.hour + 4
        if nxt >= 24:
            return _ny_wall(local + timedelta(days=1), nxt - 24)
        return _ny_wall(local, nxt)
    days = 1 if tf is Timeframe.D1 else 7
    return _ny_wall(local + timedelta(days=days), DAILY_ALIGNMENT_HOUR)


def bucket_bounds(t: datetime, tf: Timeframe) -> tuple[datetime, datetime]:
    s = bucket_start(t, tf)
    return s, bucket_end(s, tf)
