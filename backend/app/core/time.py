"""Time helpers. Everything is stored and compared in UTC (SPEC §3.5); naive datetimes are bugs."""

from __future__ import annotations

import re
from datetime import UTC, datetime

_FRACTION = re.compile(r"\.(\d+)")


def utc_now() -> datetime:
    return datetime.now(UTC)


def ensure_utc(dt: datetime) -> datetime:
    """Return ``dt`` in UTC. Refuses naive datetimes instead of guessing their timezone."""
    if dt.tzinfo is None or dt.utcoffset() is None:
        raise ValueError(f"naive datetime not allowed: {dt!r}")
    return dt.astimezone(UTC)


def parse_rfc3339(value: str) -> datetime:
    """Parse provider timestamps such as OANDA's ``2026-11-02T13:00:00.123456789Z``.

    Python keeps microseconds; extra fractional digits (nanoseconds) are truncated, never rounded,
    so a timestamp can never move forward in time (no lookahead).
    """
    s = value.strip().replace("Z", "+00:00")
    m = _FRACTION.search(s)
    if m:
        s = s[: m.start()] + "." + m.group(1)[:6].ljust(6, "0") + s[m.end() :]
    return ensure_utc(datetime.fromisoformat(s))


def parse_unix(value: str | float | int) -> datetime:
    """Parse a Unix timestamp in seconds (OANDA can be asked for UNIX format; FRED/Twelve Data use it)."""
    return datetime.fromtimestamp(float(value), tz=UTC)
