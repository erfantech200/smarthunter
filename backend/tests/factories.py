"""Test-only synthetic data (SPEC §3.2: synthetic data exists only in tests)."""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.data.models import Quote


def utc(*a: int) -> datetime:
    return datetime(*a, tzinfo=UTC)


def q(t: datetime, bid: str, ask: str, instrument: str = "EURUSD") -> Quote:
    return Quote(instrument=instrument, time=t, bid=Decimal(bid), ask=Decimal(ask), source="test")


def random_walk(start: datetime, n: int, seed: int, instrument: str = "EURUSD", step_ms: int = 900) -> list[Quote]:
    rng = random.Random(seed)
    mid = Decimal("1.08000")
    t = start
    out = []
    for _ in range(n):
        t += timedelta(milliseconds=rng.randint(50, step_ms * 2))
        mid += Decimal(rng.randint(-3, 3)) / Decimal(100000)
        half = Decimal(rng.randint(3, 8)) / Decimal(1000000)
        out.append(Quote(instrument=instrument, time=t, bid=mid - half, ask=mid + half, source="test"))
    return out
