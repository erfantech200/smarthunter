"""Phase 1 market-data tables, TimescaleDB hypertables, compression and retention (SPEC §18).

Revision ID: 0002_market_data
Revises: 0001_extensions
Create Date: 2026-11-01
"""

from collections.abc import Sequence

from alembic import op

from app.data.tables import metadata

revision: str = "0002_market_data"
down_revision: str | None = "0001_extensions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = (
    "instruments",
    "broker_profiles",
    "instrument_specs",
    "symbol_map",
    "ticks",
    "candles",
    "spreads_by_session",
    "macro_series",
    "integrity_reports",
)


def upgrade() -> None:
    bind = op.get_bind()
    metadata.create_all(bind, tables=[metadata.tables[t] for t in TABLES])
    # ticks: 1-day chunks, compressed after 2 days, dropped after 90 days (tick history for backtests
    # comes from Dukascopy; live ticks are kept for MFE/MAE and replay recordings).
    op.execute("SELECT create_hypertable('ticks', by_range('time', INTERVAL '1 day'), migrate_data => true)")
    op.execute("ALTER TABLE ticks SET (timescaledb.compress, timescaledb.compress_segmentby = 'instrument, source')")
    op.execute("SELECT add_compression_policy('ticks', INTERVAL '2 days')")
    op.execute("SELECT add_retention_policy('ticks', INTERVAL '90 days')")
    # candles: 30-day chunks, compressed after 60 days; kept forever (backtests need years).
    op.execute("SELECT create_hypertable('candles', by_range('open_time', INTERVAL '30 days'), migrate_data => true)")
    op.execute(
        "ALTER TABLE candles SET (timescaledb.compress, "
        "timescaledb.compress_segmentby = 'instrument, timeframe, source', timescaledb.compress_orderby = 'open_time')"
    )
    op.execute("SELECT add_compression_policy('candles', INTERVAL '60 days')")
    op.execute("CREATE INDEX IF NOT EXISTS candles_pit ON candles (instrument, timeframe, source, close_time DESC)")


def downgrade() -> None:
    for t in reversed(TABLES):
        op.execute(f"DROP TABLE IF EXISTS {t} CASCADE")
