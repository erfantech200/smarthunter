"""Market-data jobs, shared by the Arq worker and the CLI (``python -m app.data.cli``).

Each job is safe to re-run (idempotent upserts) and degrades to a logged "not configured" result
when its provider key is absent — it never substitutes data.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

import orjson
from redis.asyncio import Redis

from app.core import keys
from app.core.config import get_desk_config, get_settings
from app.core.db import get_engine
from app.core.logging import get_logger
from app.core.time import utc_now
from app.data import store
from app.data.adapters.base import AdapterError, AdapterNotConfigured
from app.data.adapters.macro.fred import FredAdapter
from app.data.adapters.prices.oanda import OandaAdapter
from app.data.adapters.prices.twelvedata import TwelveDataAdapter
from app.data.backfill import backfill, configured_start
from app.data.gaps import m1_gap_report
from app.data.market_config import get_market_config, load_broker_profiles
from app.data.models import Quote
from app.data.reconcile import reconcile
from app.data.spreads import spread_stats
from app.data.timeframes import Timeframe
from app.orchestrator.integrity import CrossCheckResult, assemble_live_report, cross_source_check
from app.orchestrator.market_hours import spread_bucket
from app.stream.watchdog import StreamStatus

log = get_logger()


def _secret(name: str) -> str | None:
    v = getattr(get_settings(), name)
    return v.get_secret_value() if v else None


def symbols() -> list[str]:
    return [a.symbol for a in get_desk_config().assets]


def oanda() -> OandaAdapter:
    s = get_settings()
    return OandaAdapter(
        _secret("oanda_api_token"),
        s.oanda_account_id,
        get_market_config().sources.oanda.symbols,
        s.oanda_environment,
        page_size=get_market_config().backfill.page_size,
    )


async def seed() -> dict[str, Any]:
    async with get_engine().begin() as conn:
        await store.seed_reference_data(conn, get_desk_config(), get_market_config(), load_broker_profiles())
    return {"seeded": True}


async def backfill_all(only_symbol: str | None = None, only_tf: str | None = None) -> dict[str, Any]:
    cfg = get_market_config()
    try:
        adapter = oanda()
    except AdapterNotConfigured as exc:
        return {"skipped": str(exc)}
    out: dict[str, Any] = {}
    now = utc_now()
    try:
        for sym in symbols():
            if only_symbol and sym != only_symbol:
                continue
            for tf, spec in cfg.backfill.timeframes.items():
                if only_tf and tf.value != only_tf:
                    continue
                try:
                    out[f"{sym}:{tf.value}"] = await backfill(
                        get_engine(), adapter, sym, tf, configured_start(spec, now)
                    )
                except AdapterError as exc:
                    out[f"{sym}:{tf.value}"] = f"error: {exc}"
                    log.error("backfill_failed", instrument=sym, tf=tf.value, error=str(exc))
    finally:
        await adapter.aclose()
    return out


async def refresh_macro() -> dict[str, Any]:
    cfg = get_market_config().sources.fred
    try:
        fred = FredAdapter(_secret("fred_api_key"))
    except AdapterNotConfigured as exc:
        return {"skipped": str(exc)}
    out: dict[str, Any] = {}
    try:
        for series in cfg.series:
            try:
                obs = await fred.observations(series, cfg.backfill_start)
                async with get_engine().begin() as conn:
                    out[series] = await store.upsert_macro(conn, obs)
            except AdapterError as exc:
                out[series] = f"error: {exc}"
    finally:
        await fred.aclose()
    return out


async def _primary_quote(redis: Redis, symbol: str) -> Quote | None:
    raw = await redis.get(keys.quote(symbol))
    return Quote.model_validate_json(raw) if raw else None


async def cross_check(redis: Redis, only: list[str] | None = None, outlier: bool = False) -> dict[str, Any]:
    cfg = get_market_config()
    try:
        td = TwelveDataAdapter(_secret("twelve_data_api_key"), cfg.sources.twelvedata.symbols)
    except AdapterNotConfigured as exc:
        await redis.set(keys.source_state("twelvedata"), "not_configured")
        return {"skipped": str(exc)}
    await redis.set(keys.source_state("twelvedata"), "configured")
    async with get_engine().connect() as conn:
        typical = await store.typical_spreads(conn)
    bucket = spread_bucket(cfg, utc_now())
    out: dict[str, Any] = {}
    try:
        for sym in only or cfg.sources.twelvedata.cross_check.symbols:
            try:
                ref = await td.price(sym)
            except AdapterError as exc:
                out[sym] = f"error: {exc}"
                continue
            res = cross_source_check(
                await _primary_quote(redis, sym),
                ref,
                typical.get(sym, {}).get(bucket),
                cfg.integrity.cross_check_tolerance_spreads,
            )
            await redis.set(keys.crosscheck(sym), res.model_dump_json(), ex=86400)
            if outlier:
                await redis.set(keys.outlier_resolution(sym), orjson.dumps({"confirmed": res.ok}), ex=600)
            async with get_engine().begin() as conn:
                await store.save_report(
                    conn, "cross_source", res.model_dump(mode="json"), "OK" if res.ok else "DEGRADED", res.checked_at
                )
            out[sym] = res.model_dump(mode="json")
    finally:
        await td.aclose()
    return out


async def live_report(redis: Redis) -> dict[str, Any]:
    cfg = get_market_config()
    raw = await redis.get(keys.STREAM_STATUS)
    stream = StreamStatus.model_validate_json(raw) if raw else None
    checks: dict[str, CrossCheckResult] = {}
    for sym in cfg.sources.twelvedata.cross_check.symbols:
        r = await redis.get(keys.crosscheck(sym))
        if r:
            checks[sym] = CrossCheckResult.model_validate_json(r)
    async with get_engine().connect() as conn:
        macro = await store.latest_macro(conn)
    report = assemble_live_report(utc_now(), cfg, stream, checks, macro)
    return report.model_dump(mode="json")


async def integrity_check(redis: Redis) -> dict[str, Any]:
    report = await live_report(redis)
    previous = await redis.get(keys.INTEGRITY)
    await redis.set(keys.INTEGRITY, orjson.dumps(report), ex=600)
    prev_status = orjson.loads(previous)["status"] if previous else None
    if prev_status != report["status"] or utc_now().minute % 15 == 0:
        async with get_engine().begin() as conn:
            await store.save_report(conn, "live", report, report["status"], utc_now())
    return report


async def compute_spreads(days: int = 30, source: str = "oanda") -> dict[str, Any]:
    cfg = get_market_config()
    end = utc_now()
    start = end - timedelta(days=days)
    out: dict[str, Any] = {}
    for sym in symbols():
        async with get_engine().connect() as conn:
            bars = await store.bars_between(conn, sym, Timeframe.M1, start, end, source)
        stats = spread_stats(cfg, bars)
        async with get_engine().begin() as conn:
            await store.replace_spreads(conn, source, sym, stats, (start, end))
        out[sym] = {b: str(s["median"]) for b, s in stats.items()}
    return out


async def gap_reports(days: int = 7, source: str = "oanda") -> dict[str, Any]:
    cfg = get_market_config()
    end = utc_now().replace(second=0, microsecond=0) - timedelta(hours=1)  # leave the last hour to be completed
    start = end - timedelta(days=days)
    out: dict[str, Any] = {}
    for sym in symbols():
        async with get_engine().connect() as conn:
            present = await store.open_times(conn, sym, Timeframe.M1, start, end, source)
        r = m1_gap_report(sym, cfg.hours_for(sym), present, start, end, cfg.integrity.gap_min_missing_m1)
        payload = r.model_dump(mode="json") | {
            "clean_or_explained": r.clean_or_explained,
            "unexplained": len(r.unexplained),
        }
        async with get_engine().begin() as conn:
            await store.save_report(conn, "gaps", payload, "OK" if r.clean_or_explained else "DEGRADED", end)
        out[sym] = {
            "expected": r.expected_bars,
            "present": r.present_bars,
            "gaps": len(r.gaps),
            "unexplained": len(r.unexplained),
            "quiet_runs": r.quiet_runs,
        }
    return out


async def reconcile_recent(hours: int = 6) -> dict[str, Any]:
    cfg = get_market_config()
    end = utc_now().replace(second=0, microsecond=0) - timedelta(minutes=10)
    start = end - timedelta(hours=hours)
    out: dict[str, Any] = {}
    for sym in symbols():
        async with get_engine().connect() as conn:
            live = await store.bars_between(conn, sym, Timeframe.M1, start, end, "stream")
            prov = await store.bars_between(conn, sym, Timeframe.M1, start, end, "oanda")
            typical = (await store.typical_spreads(conn)).get(sym, {})
        if not live or not prov:
            out[sym] = {"skipped": f"need both stream ({len(live)}) and provider ({len(prov)}) bars"}
            continue
        spread = Decimal(sorted(typical.values())[len(typical) // 2]) if typical else prov[len(prov) // 2].spread_c
        r = reconcile(live, prov, spread, cfg.reconciliation)
        async with get_engine().begin() as conn:
            await store.save_report(
                conn, "reconciliation", r.model_dump(mode="json"), "OK" if r.passed else "DEGRADED", end
            )
        out[sym] = {
            "passed": r.passed,
            "compared": r.compared,
            "close_match": str(r.close_match_rate),
            "hl_within_tol": str(r.high_low_within_tolerance_rate),
        }
    return out


async def check_sources() -> dict[str, Any]:
    """Live connectivity check of every configured source (run once keys are in .env)."""
    out: dict[str, Any] = {}
    cfg = get_market_config()
    for name, factory in (
        ("oanda", oanda),
        ("twelvedata", lambda: TwelveDataAdapter(_secret("twelve_data_api_key"), cfg.sources.twelvedata.symbols)),
        ("fred", lambda: FredAdapter(_secret("fred_api_key"))),
    ):
        try:
            a = factory()
        except AdapterNotConfigured as exc:
            out[name] = {"ok": False, "detail": f"not configured: {exc}"}
            continue
        try:
            out[name] = (await a.health()).model_dump(mode="json")
        finally:
            await a.aclose()
    return out
