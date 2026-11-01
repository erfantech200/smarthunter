"""Operator CLI for market data (also used by the Make targets).

python -m app.data.cli check-sources       # live connectivity of OANDA / Twelve Data / FRED
python -m app.data.cli seed                # instruments, broker profiles, specs, symbol maps
python -m app.data.cli backfill [--symbol EURUSD] [--tf M1]
python -m app.data.cli macro | spreads | cross-check | integrity
python -m app.data.cli gaps [--days 7]
python -m app.data.cli reconcile [--hours 6]
python -m app.data.cli coverage
python -m app.data.cli record-stream --seconds 300   # capture real OANDA lines for replay tests
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import timedelta
from pathlib import Path
from typing import Any

import orjson
from redis.asyncio import Redis

from app.core.config import REPO_ROOT, get_settings
from app.core.db import get_engine
from app.core.guards import production_guard
from app.core.logging import configure_logging
from app.core.time import utc_now
from app.data import jobs, store


async def _record(seconds: int, out: str | None) -> dict[str, Any]:
    """Write raw stream lines to tests/stream_recordings/recorded_<utc>.ndjson (real data, for replay tests)."""
    a = jobs.oanda()
    path = (
        Path(out)
        if out
        else REPO_ROOT / "tests" / "stream_recordings" / f"recorded_oanda_{utc_now():%Y%m%dT%H%M}Z.ndjson"
    )
    end = utc_now() + timedelta(seconds=seconds)
    lines: list[str] = []
    try:
        async for line in a.stream_lines(jobs.symbols()):
            if line.strip():
                lines.append(line)
            if utc_now() >= end:
                break
    finally:
        await a.aclose()
    await asyncio.to_thread(Path(path).write_text, "\n".join(lines) + "\n", encoding="utf-8")
    return {"file": str(path), "lines": len(lines)}


async def run(args: argparse.Namespace) -> Any:
    redis: Redis = Redis.from_url(get_settings().redis_url)
    try:
        match args.cmd:
            case "check-sources":
                return await jobs.check_sources()
            case "seed":
                return await jobs.seed()
            case "backfill":
                return await jobs.backfill_all(args.symbol, args.tf)
            case "macro":
                return await jobs.refresh_macro()
            case "spreads":
                return await jobs.compute_spreads()
            case "cross-check":
                return await jobs.cross_check(redis)
            case "integrity":
                return await jobs.integrity_check(redis)
            case "gaps":
                return await jobs.gap_reports(args.days)
            case "reconcile":
                return await jobs.reconcile_recent(args.hours)
            case "coverage":
                async with get_engine().connect() as conn:
                    return await store.coverage(conn)
            case "record-stream":
                return await _record(args.seconds, args.out)
    finally:
        await redis.aclose()
        await get_engine().dispose()
    return None


def main() -> None:
    p = argparse.ArgumentParser(prog="python -m app.data.cli")
    sub = p.add_subparsers(dest="cmd", required=True)
    for c in ("check-sources", "seed", "macro", "spreads", "cross-check", "integrity", "coverage"):
        sub.add_parser(c)
    b = sub.add_parser("backfill")
    b.add_argument("--symbol")
    b.add_argument("--tf")
    g = sub.add_parser("gaps")
    g.add_argument("--days", type=int, default=7)
    r = sub.add_parser("reconcile")
    r.add_argument("--hours", type=int, default=6)
    rs = sub.add_parser("record-stream")
    rs.add_argument("--seconds", type=int, default=300)
    rs.add_argument("--out")
    args = p.parse_args()
    settings = get_settings()
    configure_logging("cli", settings.log_level)
    production_guard(settings)
    out = asyncio.run(run(args))
    sys.stdout.write(orjson.dumps(out, option=orjson.OPT_INDENT_2, default=str).decode() + "\n")


if __name__ == "__main__":
    main()
