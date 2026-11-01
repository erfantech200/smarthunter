"""Twelve Data — second price source for the cross-source check (SPEC §6 A0, §10).

``GET https://api.twelvedata.com/price?symbol=EUR/USD&apikey=…`` → ``{"price": "1.08"}``. The response
has no timestamp, so the fetch time is recorded as the observation time and the check compares it
with the primary feed's quote at that moment. Basic plan budget is respected by the scheduler.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation

import httpx
from pydantic import BaseModel

from app.core.time import utc_now
from app.data.adapters.base import AdapterError, AdapterHealth, AdapterNotConfigured, AdapterRateLimited
from app.data.adapters.http import get, raise_for_status

SOURCE = "twelvedata"
BASE = "https://api.twelvedata.com"


class ReferencePrice(BaseModel):
    instrument: str
    price: Decimal
    observed_at: datetime
    source: str = SOURCE


class TwelveDataAdapter:
    name = SOURCE

    def __init__(self, api_key: str | None, symbols: dict[str, str], transport: httpx.AsyncBaseTransport | None = None):
        if not api_key:
            raise AdapterNotConfigured("TWELVE_DATA_API_KEY is required")
        self._key = api_key
        self._symbols = symbols
        self._client = httpx.AsyncClient(base_url=BASE, timeout=10, transport=transport)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def price(self, instrument: str) -> ReferencePrice:
        resp = await get(
            self._client, "/price", SOURCE, params={"symbol": self._symbols[instrument], "apikey": self._key}
        )
        raise_for_status(resp, SOURCE)
        body = resp.json()
        if body.get("status") == "error":  # Twelve Data reports errors with HTTP 200
            code = body.get("code")
            if code == 429:
                raise AdapterRateLimited(f"{SOURCE}: {body.get('message')}")
            raise AdapterError(f"{SOURCE}: {code} {body.get('message')}")
        try:
            return ReferencePrice(instrument=instrument, price=Decimal(str(body["price"])), observed_at=utc_now())
        except (KeyError, InvalidOperation) as exc:
            raise AdapterError(f"{SOURCE}: malformed price response") from exc

    async def health(self) -> AdapterHealth:
        try:
            await self.price(next(iter(self._symbols)))
            return AdapterHealth(source=SOURCE, ok=True, detail="price endpoint ok", checked_at=utc_now())
        except AdapterError as exc:
            return AdapterHealth(source=SOURCE, ok=False, detail=str(exc), checked_at=utc_now())
