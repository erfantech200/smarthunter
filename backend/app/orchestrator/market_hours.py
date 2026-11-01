"""Market hours and session clock (SPEC §6 A0 "market-hours aware", §16 sessions).

All inputs and outputs are UTC; each rule is evaluated in its own home timezone with ``zoneinfo``,
so DST in New York, London, Tokyo and Melbourne is handled independently.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.core.time import ensure_utc
from app.data.market_config import WEEKDAYS, MarketConfig, MarketHoursGroup, Window
from app.orchestrator.holidays import holiday_name

SPREAD_BUCKETS = ("rollover", "overlap", "london", "new_york", "asia", "off")


def _in_range(t: time, start: time, end: time) -> bool:
    """Half-open [start, end), allowing ranges that wrap midnight."""
    return start <= t < end if start < end else t >= start or t < end


def is_open(group: MarketHoursGroup, t: datetime) -> bool:
    local = ensure_utc(t).astimezone(ZoneInfo(group.tz))
    wd, tt = local.weekday(), local.time()
    open_day, open_t = WEEKDAYS[group.weekly_open[0]], group.weekly_open[1]
    close_day, close_t = WEEKDAYS[group.weekly_close[0]], group.weekly_close[1]
    if wd == 5:  # Saturday
        return False
    if wd == open_day and tt < open_t:
        return False
    if wd == close_day and tt >= close_t:
        return False
    return not any(_in_range(tt, s, e) for s, e in group.daily_breaks)


def in_window(w: Window, t: datetime) -> bool:
    t = ensure_utc(t)
    if w.end_tz is None or w.end_tz == w.tz:
        return _in_range(t.astimezone(ZoneInfo(w.tz)).time(), w.start, w.end)
    # cross-timezone window (e.g. NY open → London close): start and end are measured in their own zones
    start_local = t.astimezone(ZoneInfo(w.tz))
    end_local = t.astimezone(ZoneInfo(w.end_tz))
    return start_local.time() >= w.start and end_local.time() < w.end


def spread_bucket(cfg: MarketConfig, t: datetime) -> str:
    """Single label per instant, used for spreads_by_session (priority order in SPREAD_BUCKETS)."""
    if in_window(cfg.rollover, t):
        return "rollover"
    s = cfg.sessions
    london, ny = in_window(s["london"], t), in_window(s["new_york"], t)
    if london and ny:
        return "overlap"
    if london:
        return "london"
    if ny:
        return "new_york"
    if in_window(s["asia"], t):
        return "asia"
    return "off"


def active_session_windows(cfg: MarketConfig, t: datetime) -> list[str]:
    return [name for name, w in cfg.session_windows.items() if in_window(w, t)]


def explain_gap(group: MarketHoursGroup, start: datetime, end: datetime) -> str | None:
    """Why prices could legitimately be missing in the open-hours run [start, end).

    Returns ``None`` when nothing explains it (a real data hole).
    """
    tz = ZoneInfo(group.tz)
    local = start.astimezone(tz)
    # The trading day that starts in the evening (NY/London) belongs to the next calendar date.
    for d in {local.date(), (local + timedelta(hours=7)).date()}:
        name = holiday_name(d)
        if name:
            return f"holiday or early close: {name}"
    edge = timedelta(minutes=30)
    if not is_open(group, start - edge) or not is_open(group, end + edge - timedelta(minutes=1)):
        return "within 30 min of scheduled open/close/break — provider hours may differ from config"
    return None
