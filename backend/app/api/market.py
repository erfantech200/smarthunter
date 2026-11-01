"""Market-data API (Phase 1). Read-only; every value comes from the live feed or the store."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

import orjson
from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import select

from app.core import keys
from app.core.config import get_desk_config
from app.core.db import get_engine
from app.core.time import ensure_utc, utc_now
from app.data import jobs, store
from app.data import tables as t
from app.data.models import Quote
from app.data.timeframes import Timeframe

router = APIRouter(prefix="/market", tags=["market"])
settings_router = APIRouter(prefix="/settings", tags=["settings"])


def _fmt(v: object) -> object:
    """Decimals from NUMERIC columns carry trailing zeros; show them plainly (1.08012, not 1.0801200000)."""
    if isinstance(v, Decimal):
        return format(v.normalize(), "f")
    if isinstance(v, datetime):
        return v.isoformat()
    return v


def _symbols() -> list[str]:
    return [a.symbol for a in get_desk_config().assets]


def _check_symbol(symbol: str) -> None:
    if symbol not in _symbols():
        raise HTTPException(404, f"unknown instrument {symbol}")


@router.get("/status")
async def market_status(request: Request) -> dict[str, Any]:
    """Live integrity report computed now from the stream status, cross-checks and macro freshness."""
    redis = request.app.state.redis
    sources = {s: (await redis.get(keys.source_state(s)) or b"unknown").decode() for s in ("oanda", "twelvedata")}
    report = await jobs.live_report(redis)
    raw = await redis.get(keys.STREAM_STATUS)
    return {"integrity": report, "stream": orjson.loads(raw) if raw else None, "sources": sources}


@router.get("/quotes")
async def quotes(request: Request) -> dict[str, Any]:
    redis = request.app.state.redis
    now = utc_now()
    out: dict[str, Any] = {}
    for sym in _symbols():
        raw = await redis.get(keys.quote(sym))
        if raw is None:
            out[sym] = None
            continue
        q = Quote.model_validate_json(raw)
        out[sym] = {
            "bid": str(q.bid),
            "ask": str(q.ask),
            "mid": str(q.mid),
            "spread": str(q.spread),
            "time": q.time.isoformat(),
            "age_seconds": round((now - q.time).total_seconds(), 1),
            "source": q.source,
        }
    return out


@router.get("/bars/{symbol}/{tf}")
async def bars(
    symbol: str, tf: Timeframe, source: str = "oanda", limit: int = Query(300, le=5000), as_of: datetime | None = None
) -> list[dict[str, Any]]:
    _check_symbol(symbol)
    async with get_engine().connect() as conn:
        rows = await store.closed_bars(conn, symbol, tf, ensure_utc(as_of) if as_of else utc_now(), limit, source)
    return [{k: _fmt(v) for k, v in b.model_dump().items()} for b in rows]


@router.get("/coverage")
async def coverage() -> list[dict[str, Any]]:
    async with get_engine().connect() as conn:
        return [
            {**r, "first": r["first"].isoformat(), "last": r["last"].isoformat()} for r in await store.coverage(conn)
        ]


@router.get("/spreads")
async def spreads() -> dict[str, dict[str, str]]:
    async with get_engine().connect() as conn:
        return {k: {b: str(_fmt(v)) for b, v in by.items()} for k, by in (await store.typical_spreads(conn)).items()}


@router.get("/reports/{kind}")
async def reports(kind: str, limit: int = Query(20, le=200)) -> list[dict[str, Any]]:
    c = t.integrity_reports.c
    q = select(c.as_of, c.status, c.report).where(c.kind == kind).order_by(c.as_of.desc()).limit(limit)
    async with get_engine().connect() as conn:
        rows = (await conn.execute(q)).all()
    return [{"as_of": r.as_of.isoformat(), "status": r.status, "report": r.report} for r in rows]


@settings_router.get("/broker-profiles")
async def broker_profiles() -> list[dict[str, Any]]:
    async with get_engine().connect() as conn:
        profiles = (await conn.execute(select(t.broker_profiles))).mappings().all()
        specs = (await conn.execute(select(t.instrument_specs))).mappings().all()
        maps = (await conn.execute(select(t.symbol_map))).mappings().all()
    out = []
    for p in profiles:
        out.append(
            {
                **{k: _fmt(v) for k, v in p.items()},
                "instruments": {
                    s["symbol"]: {k: _fmt(v) for k, v in s.items() if k not in ("broker_profile_id", "symbol")}
                    for s in specs
                    if s["broker_profile_id"] == p["id"]
                },
                "symbol_map": {
                    m["symbol"]: m["external_symbol"] for m in maps if m["namespace"] == f"broker:{p['id']}"
                },
            }
        )
    return out
