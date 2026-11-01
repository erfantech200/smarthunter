"""Async SQLAlchemy engine. Tables arrive with their phases; Phase 0 only checks connectivity
and that the TimescaleDB and pgvector extensions are installed."""

from __future__ import annotations

from functools import lru_cache

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from app.core.config import get_settings

REQUIRED_EXTENSIONS = ("timescaledb", "vector")


@lru_cache
def get_engine() -> AsyncEngine:
    return create_async_engine(get_settings().database_url, pool_pre_ping=True, pool_size=5)


async def installed_extensions(engine: AsyncEngine) -> set[str]:
    async with engine.connect() as conn:
        rows = await conn.execute(text("select extname from pg_extension"))
        return {r[0] for r in rows}
