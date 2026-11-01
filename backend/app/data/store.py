"""Persistence for market data. Async SQLAlchemy Core over asyncpg; prices round-trip as Decimal.

Point-in-time readers (``closed_bars``) filter on ``close_time <= as_of`` and ``complete``, so a
consumer asking "what did I know at t" never sees a bar that was still forming at t.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncConnection

from app.core.config import DeskConfig
from app.core.time import ensure_utc
from app.data import tables as t
from app.data.adapters.macro.fred import MacroObservation
from app.data.market_config import BrokerProfile, MarketConfig
from app.data.models import Bar, Quote
from app.data.timeframes import Timeframe
from app.orchestrator.integrity_model import IntegrityReport

_OHLC = [f"{s}_{k}" for s in ("bid", "ask") for k in "ohlc"]


def _bar_row(b: Bar) -> dict[str, Any]:
    row: dict[str, Any] = {
        "instrument": b.instrument,
        "timeframe": b.timeframe.value,
        "source": b.source,
        "open_time": b.open_time,
        "close_time": b.close_time,
        "volume": b.volume,
        "complete": b.complete,
    }
    row.update({k: getattr(b, k) for k in _OHLC})
    return row


def _row_bar(r: Any) -> Bar:
    m = r._mapping
    return Bar(
        instrument=m["instrument"],
        timeframe=Timeframe(m["timeframe"]),
        open_time=m["open_time"],
        close_time=m["close_time"],
        volume=m["volume"],
        complete=m["complete"],
        source=m["source"],
        **{k: m[k] for k in _OHLC},
    )


async def upsert_candles(conn: AsyncConnection, bars: Sequence[Bar], chunk: int = 2000) -> int:
    """Insert or update bars. A complete bar replaces an incomplete one; complete bars are never
    overwritten by incomplete ones."""
    n = 0
    for i in range(0, len(bars), chunk):
        rows = [_bar_row(b) for b in bars[i : i + chunk]]
        stmt = insert(t.candles).values(rows)
        update: dict[str, Any] = {c: stmt.excluded[c] for c in [*_OHLC, "close_time", "volume", "complete"]}
        update["ingested_at"] = func.now()
        stmt = stmt.on_conflict_do_update(
            index_elements=["instrument", "timeframe", "source", "open_time"],
            set_=update,
            where=t.candles.c.complete.is_(False),
        )
        await conn.execute(stmt)
        n += len(rows)
    return n


async def insert_ticks(conn: AsyncConnection, quotes: Iterable[Quote]) -> int:
    rows = [
        {
            "instrument": q.instrument,
            "time": q.time,
            "source": q.source,
            "bid": q.bid,
            "ask": q.ask,
            "received_at": q.received_at or q.time,
        }
        for q in quotes
    ]
    if not rows:
        return 0
    await conn.execute(insert(t.ticks).values(rows).on_conflict_do_nothing())
    return len(rows)


async def latest_open_time(conn: AsyncConnection, instrument: str, tf: Timeframe, source: str) -> datetime | None:
    c = t.candles.c
    q = select(func.max(c.open_time)).where(
        c.instrument == instrument, c.timeframe == tf.value, c.source == source, c.complete.is_(True)
    )
    value: datetime | None = (await conn.execute(q)).scalar()
    return value


async def closed_bars(
    conn: AsyncConnection, instrument: str, tf: Timeframe, as_of: datetime, limit: int = 500, source: str = "oanda"
) -> list[Bar]:
    """The last ``limit`` complete bars knowable at ``as_of`` (oldest first)."""
    c = t.candles.c
    q = (
        select(t.candles)
        .where(
            c.instrument == instrument,
            c.timeframe == tf.value,
            c.source == source,
            c.complete.is_(True),
            c.close_time <= ensure_utc(as_of),
        )
        .order_by(c.open_time.desc())
        .limit(limit)
    )
    rows = (await conn.execute(q)).all()
    return [_row_bar(r) for r in reversed(rows)]


async def bars_between(
    conn: AsyncConnection, instrument: str, tf: Timeframe, start: datetime, end: datetime, source: str
) -> list[Bar]:
    c = t.candles.c
    q = (
        select(t.candles)
        .where(
            c.instrument == instrument,
            c.timeframe == tf.value,
            c.source == source,
            c.open_time >= ensure_utc(start),
            c.open_time < ensure_utc(end),
        )
        .order_by(c.open_time)
    )
    return [_row_bar(r) for r in (await conn.execute(q)).all()]


async def open_times(
    conn: AsyncConnection, instrument: str, tf: Timeframe, start: datetime, end: datetime, source: str
) -> list[datetime]:
    c = t.candles.c
    q = (
        select(c.open_time)
        .where(
            c.instrument == instrument,
            c.timeframe == tf.value,
            c.source == source,
            c.open_time >= ensure_utc(start),
            c.open_time < ensure_utc(end),
        )
        .order_by(c.open_time)
    )
    return list((await conn.execute(q)).scalars())


async def coverage(conn: AsyncConnection) -> list[dict[str, Any]]:
    c = t.candles.c
    q = (
        select(c.instrument, c.timeframe, c.source, func.min(c.open_time), func.max(c.open_time), func.count())
        .group_by(c.instrument, c.timeframe, c.source)
        .order_by(c.instrument, c.timeframe, c.source)
    )
    return [
        dict(zip(("instrument", "timeframe", "source", "first", "last", "bars"), r, strict=True))
        for r in (await conn.execute(q)).all()
    ]


async def upsert_macro(conn: AsyncConnection, obs: Sequence[MacroObservation]) -> int:
    if not obs:
        return 0
    rows = [o.model_dump() for o in obs]
    stmt = insert(t.macro_series).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=["series_id", "obs_date", "source"],
        set_={"value": stmt.excluded.value, "published_at": stmt.excluded.published_at, "ingested_at": func.now()},
    )
    await conn.execute(stmt)
    return len(rows)


async def latest_macro(conn: AsyncConnection) -> dict[str, datetime]:
    c = t.macro_series.c
    q = select(c.series_id, func.max(c.published_at)).group_by(c.series_id)
    return {sid: ts for sid, ts in (await conn.execute(q)).all()}


async def replace_spreads(
    conn: AsyncConnection,
    source: str,
    instrument: str,
    stats: dict[str, dict[str, Any]],
    window: tuple[datetime, datetime],
) -> None:
    await conn.execute(
        t.spreads_by_session.delete().where(
            t.spreads_by_session.c.source == source, t.spreads_by_session.c.instrument == instrument
        )
    )
    if stats:
        await conn.execute(
            insert(t.spreads_by_session).values(
                [
                    {
                        "source": source,
                        "instrument": instrument,
                        "bucket": b,
                        **s,
                        "window_start": window[0],
                        "window_end": window[1],
                    }
                    for b, s in stats.items()
                ]
            )
        )


async def typical_spreads(conn: AsyncConnection, source: str = "oanda") -> dict[str, dict[str, Decimal]]:
    c = t.spreads_by_session.c
    out: dict[str, dict[str, Decimal]] = {}
    for inst, bucket, med in (
        await conn.execute(select(c.instrument, c.bucket, c.median).where(c.source == source))
    ).all():
        out.setdefault(inst, {})[bucket] = med
    return out


async def save_report(
    conn: AsyncConnection,
    kind: str,
    report: IntegrityReport | dict[str, Any],
    status: str | None = None,
    as_of: datetime | None = None,
) -> None:
    if isinstance(report, IntegrityReport):
        payload, status, as_of = report.model_dump(mode="json"), report.status.value, report.as_of
    else:
        payload = report
    await conn.execute(insert(t.integrity_reports).values(as_of=as_of, kind=kind, status=status, report=payload))


async def seed_reference_data(
    conn: AsyncConnection, desk: DeskConfig, market: MarketConfig, profiles: list[BrokerProfile]
) -> None:
    """Idempotently load instruments, broker profiles, specs and symbol maps from config."""
    ins = insert(t.instruments).values([a.model_dump() for a in desk.assets])
    await conn.execute(
        ins.on_conflict_do_update(
            index_elements=["symbol"],
            set_={
                "name": ins.excluded.name,
                "asset_class": ins.excluded.asset_class,
                "quote_ccy": ins.excluded.quote_ccy,
                "updated_at": func.now(),
            },
        )
    )
    maps: list[dict[str, str]] = []
    for ns, mapping in (
        ("oanda", market.sources.oanda.symbols),
        ("twelvedata", market.sources.twelvedata.symbols),
        ("dukascopy", market.sources.dukascopy.symbols),
    ):
        maps += [{"namespace": ns, "symbol": s, "external_symbol": x} for s, x in mapping.items()]
    for p in profiles:
        bp = insert(t.broker_profiles).values(id=p.id, name=p.name, active=p.active)
        await conn.execute(
            bp.on_conflict_do_update(
                index_elements=["id"],
                set_={"name": bp.excluded.name, "active": bp.excluded.active, "updated_at": func.now()},
            )
        )
        for sym, spec in p.instruments.items():
            row = spec.model_dump(exclude={"broker_symbol"})
            s = insert(t.instrument_specs).values(broker_profile_id=p.id, symbol=sym, **row)
            # Never overwrite values the owner has confirmed in the UI with config defaults.
            await conn.execute(
                s.on_conflict_do_update(
                    index_elements=["broker_profile_id", "symbol"],
                    set_={k: s.excluded[k] for k in row} | {"updated_at": func.now()},
                    where=t.instrument_specs.c.confirmed.is_(False),
                )
            )
            maps.append({"namespace": f"broker:{p.id}", "symbol": sym, "external_symbol": spec.broker_symbol})
    sm = insert(t.symbol_map).values(maps)
    await conn.execute(
        sm.on_conflict_do_update(
            index_elements=["namespace", "symbol"], set_={"external_symbol": sm.excluded.external_symbol}
        )
    )
