"""Rule-based calendar of days with closures or early closes (CME/US, UK, global).

Used to *explain* gaps in the gap report, not to close markets: closures differ by venue and
year, and the provider's own data is the authority on whether prices printed.
"""

from __future__ import annotations

from datetime import date, timedelta
from functools import lru_cache


def _easter(year: int) -> date:  # anonymous Gregorian algorithm
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    m = (32 + 2 * e + 2 * i - h - k) % 7
    n = (a + 11 * h + 22 * m) // 451
    month = (h + m - 7 * n + 114) // 31
    day = (h + m - 7 * n + 114) % 31 + 1
    return date(year, month, day)


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    d = date(year, month, 1)
    d += timedelta(days=(weekday - d.weekday()) % 7)
    return d + timedelta(weeks=n - 1)


def _last_weekday(year: int, month: int, weekday: int) -> date:
    d = date(year + (month == 12), month % 12 + 1, 1) - timedelta(days=1)
    return d - timedelta(days=(d.weekday() - weekday) % 7)


def _observed(d: date) -> date:
    if d.weekday() == 5:
        return d - timedelta(days=1)
    if d.weekday() == 6:
        return d + timedelta(days=1)
    return d


@lru_cache
def holidays(year: int) -> dict[date, str]:
    easter = _easter(year)
    out = {
        _observed(date(year, 1, 1)): "New Year's Day",
        _nth_weekday(year, 1, 0, 3): "US Martin Luther King Jr. Day",
        _nth_weekday(year, 2, 0, 3): "US Presidents' Day",
        easter - timedelta(days=2): "Good Friday",
        easter + timedelta(days=1): "Easter Monday (UK)",
        _last_weekday(year, 5, 0): "US Memorial Day",
        _observed(date(year, 7, 4)): "US Independence Day",
        _nth_weekday(year, 9, 0, 1): "US Labor Day",
        _nth_weekday(year, 11, 3, 4): "US Thanksgiving",
        _nth_weekday(year, 11, 3, 4) + timedelta(days=1): "US day after Thanksgiving (early close)",
        date(year, 12, 24): "Christmas Eve (early close)",
        _observed(date(year, 12, 25)): "Christmas Day",
        date(year, 12, 26): "Boxing Day (UK)",
        date(year, 12, 31): "New Year's Eve (early close)",
    }
    if year >= 2022:
        out[_observed(date(year, 6, 19))] = "US Juneteenth"
    return out


def holiday_name(d: date) -> str | None:
    return holidays(d.year).get(d)
