"""Dukascopy historical ticks (bid/ask) for scalp/intraday backtests (SPEC §10).

Format: hourly ``.bi5`` files (LZMA "alone"), 20-byte big-endian records
``(ms_from_hour u32, ask u32, bid u32, ask_volume f32, bid_volume f32)``; prices are integers ÷ a
per-instrument divisor. URL months are zero-based.

Licence terms are not confirmed (docs/PROVIDERS.md §2.3): downloading refuses to run until
``sources.dukascopy.terms_accepted`` is true in config/market.yaml. Decoding is always allowed.
"""

from __future__ import annotations

import lzma
import struct
from datetime import datetime, timedelta
from decimal import Decimal

import httpx

from app.core.time import ensure_utc, utc_now
from app.data.adapters.base import AdapterError, AdapterNotConfigured
from app.data.adapters.http import get, raise_for_status
from app.data.models import Quote

SOURCE = "dukascopy"
BASE = "https://datafeed.dukascopy.com/datafeed"
_RECORD = struct.Struct(">3I2f")


def hour_url(symbol: str, hour: datetime) -> str:
    h = ensure_utc(hour)
    return f"{BASE}/{symbol}/{h.year:04d}/{h.month - 1:02d}/{h.day:02d}/{h.hour:02d}h_ticks.bi5"


def decode_bi5(instrument: str, hour: datetime, payload: bytes, divisor: int) -> list[Quote]:
    hour = ensure_utc(hour).replace(minute=0, second=0, microsecond=0)
    if not payload:
        return []  # no ticks in this hour (closed market) — an empty file, not an error
    try:
        raw = lzma.decompress(payload, format=lzma.FORMAT_ALONE)
    except lzma.LZMAError as exc:
        raise AdapterError(f"{SOURCE}: corrupt bi5 for {instrument} {hour.isoformat()}") from exc
    if len(raw) % _RECORD.size:
        raise AdapterError(f"{SOURCE}: truncated bi5 for {instrument} {hour.isoformat()}")
    div = Decimal(divisor)
    ingested = utc_now()
    out = []
    for ms, ask, bid, _av, _bv in _RECORD.iter_unpack(raw):
        out.append(
            Quote(
                instrument=instrument,
                time=hour + timedelta(milliseconds=ms),
                bid=Decimal(bid) / div,
                ask=Decimal(ask) / div,
                source=SOURCE,
                received_at=ingested,
            )
        )
    return out


class DukascopyAdapter:
    name = SOURCE

    def __init__(
        self,
        terms_accepted: bool,
        symbols: dict[str, str],
        divisors: dict[str, int],
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if not terms_accepted:
            raise AdapterNotConfigured(
                "Dukascopy licence terms not confirmed: set sources.dukascopy.terms_accepted after reading them"
            )
        self._symbols, self._div = symbols, divisors
        self._client = httpx.AsyncClient(timeout=30, transport=transport)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def hour(self, instrument: str, hour: datetime) -> list[Quote]:
        resp = await get(self._client, hour_url(self._symbols[instrument], hour), SOURCE)
        if resp.status_code == 404:
            return []
        raise_for_status(resp, SOURCE)
        return decode_bi5(instrument, hour, resp.content, self._div[instrument])
