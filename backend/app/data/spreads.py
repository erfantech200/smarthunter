"""Spreads by session (SPEC §9.3, §11.3): median / p90 / mean of the M1 close spread per session bucket."""

from __future__ import annotations

import statistics
from collections import defaultdict
from decimal import Decimal
from typing import Any

from app.data.market_config import MarketConfig
from app.data.models import Bar
from app.orchestrator.market_hours import spread_bucket


def spread_stats(cfg: MarketConfig, bars: list[Bar]) -> dict[str, dict[str, Any]]:
    by: dict[str, list[Decimal]] = defaultdict(list)
    for b in bars:
        if b.spread_c > 0:
            by[spread_bucket(cfg, b.open_time)].append(b.spread_c)
    out: dict[str, dict[str, Any]] = {}
    for bucket, xs in by.items():
        xs.sort()
        p90 = xs[min(len(xs) - 1, int(0.9 * len(xs)))]
        out[bucket] = {
            "median": Decimal(statistics.median(xs)),
            "p90": p90,
            "mean": sum(xs, Decimal(0)) / len(xs),
            "samples": len(xs),
        }
    return out
