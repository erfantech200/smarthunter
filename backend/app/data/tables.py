"""SQLAlchemy Core tables for Phase 1 (SPEC §18). Every agent-facing time series carries
``event_time``-style timestamps plus ``ingested_at`` (UTC) for point-in-time reads (SPEC §3.5)."""

from __future__ import annotations

from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    Integer,
    MetaData,
    Numeric,
    String,
    Table,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB

metadata = MetaData()
PRICE = Numeric(24, 10)
TS = DateTime(timezone=True)

instruments = Table(
    "instruments",
    metadata,
    Column("symbol", String(16), primary_key=True),
    Column("name", Text, nullable=False),
    Column("asset_class", String(16), nullable=False),
    Column("quote_ccy", String(3), nullable=False),
    Column("updated_at", TS, nullable=False, server_default=func.now()),
)

broker_profiles = Table(
    "broker_profiles",
    metadata,
    Column("id", String(64), primary_key=True),
    Column("name", Text, nullable=False),
    Column("active", Boolean, nullable=False),
    Column("updated_at", TS, nullable=False, server_default=func.now()),
)

instrument_specs = Table(
    "instrument_specs",
    metadata,
    Column("broker_profile_id", String(64), primary_key=True),
    Column("symbol", String(16), primary_key=True),
    Column("pip", PRICE, nullable=False),
    Column("contract_size", PRICE, nullable=False),
    Column("contract_unit", String(16), nullable=False),
    Column("lot_step", PRICE, nullable=False),
    Column("min_lots", PRICE, nullable=False),
    Column("commission_per_lot_usd", PRICE, nullable=False),
    Column("confirmed", Boolean, nullable=False),
    Column("updated_at", TS, nullable=False, server_default=func.now()),
)

symbol_map = Table(
    "symbol_map",
    metadata,
    Column("namespace", String(64), primary_key=True),  # oanda | twelvedata | dukascopy | broker:<profile id>
    Column("symbol", String(16), primary_key=True),
    Column("external_symbol", String(64), nullable=False),
)

ticks = Table(  # hypertable on `time` (migration 0002)
    "ticks",
    metadata,
    Column("instrument", String(16), primary_key=True),
    Column("time", TS, primary_key=True),
    Column("source", String(16), primary_key=True),
    Column("bid", PRICE, nullable=False),
    Column("ask", PRICE, nullable=False),
    Column("received_at", TS, nullable=False),
)

candles = Table(  # hypertable on `open_time` (migration 0002)
    "candles",
    metadata,
    Column("instrument", String(16), primary_key=True),
    Column("timeframe", String(4), primary_key=True),
    Column("source", String(16), primary_key=True),  # oanda (provider candles) | stream (built live) | dukascopy
    Column("open_time", TS, primary_key=True),
    Column("close_time", TS, nullable=False),
    *(Column(f"{side}_{k}", PRICE, nullable=False) for side in ("bid", "ask") for k in "ohlc"),
    Column("volume", Integer, nullable=False),
    Column("complete", Boolean, nullable=False),
    Column("ingested_at", TS, nullable=False, server_default=func.now()),
)

spreads_by_session = Table(
    "spreads_by_session",
    metadata,
    Column("source", String(16), primary_key=True),
    Column("instrument", String(16), primary_key=True),
    Column("bucket", String(16), primary_key=True),  # asia | london | overlap | new_york | rollover | off
    Column("median", PRICE, nullable=False),
    Column("p90", PRICE, nullable=False),
    Column("mean", PRICE, nullable=False),
    Column("samples", Integer, nullable=False),
    Column("window_start", TS, nullable=False),
    Column("window_end", TS, nullable=False),
    Column("computed_at", TS, nullable=False, server_default=func.now()),
)

macro_series = Table(
    "macro_series",
    metadata,
    Column("series_id", String(64), primary_key=True),
    Column("obs_date", Date, primary_key=True),
    Column("source", String(16), primary_key=True),
    Column("value", PRICE, nullable=False),
    Column("event_time", TS, nullable=False),
    Column("published_at", TS, nullable=False),
    Column("ingested_at", TS, nullable=False, server_default=func.now()),
)

integrity_reports = Table(
    "integrity_reports",
    metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("as_of", TS, nullable=False, index=True),
    Column("kind", String(32), nullable=False),  # live | gaps | reconciliation | cross_source
    Column("status", String(16), nullable=False),
    Column("report", JSONB, nullable=False),
)
