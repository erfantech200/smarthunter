"""Adapter contracts (SPEC §10): one interface per data category — fetch / stream / backfill / health.

Every adapter returns normalised, timestamped data tagged with its ``source``. Errors are typed so
callers can tell "retry later" from "fix the configuration".
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime
from typing import Protocol

from pydantic import BaseModel

from app.data.models import Bar, Heartbeat, Quote
from app.data.timeframes import Timeframe


class AdapterError(RuntimeError):
    """Transient or unknown failure — safe to retry with backoff."""


class AdapterAuthError(AdapterError):
    """Credentials missing or rejected — retrying will not help; alert the owner."""


class AdapterRateLimited(AdapterError):
    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class AdapterNotConfigured(AdapterError):
    """A required key/setting is absent. The service reports idle instead of guessing."""


class AdapterHealth(BaseModel):
    source: str
    ok: bool
    detail: str
    checked_at: datetime


class PriceStreamAdapter(Protocol):
    name: str

    def stream(self, instruments: list[str]) -> AsyncIterator[Quote | Heartbeat]: ...

    async def health(self) -> AdapterHealth: ...


class CandleAdapter(Protocol):
    name: str

    def candles(
        self, instrument: str, tf: Timeframe, start: datetime, end: datetime, include_incomplete: bool = False
    ) -> AsyncIterator[list[Bar]]: ...
