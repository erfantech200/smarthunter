"""OANDA v20 adapter — READ-ONLY pricing and candles (ADR-006).

Endpoints used (developer.oanda.com, checked 2026-11-01):
* ``GET {stream}/v3/accounts/{id}/pricing/stream`` — chunked JSON lines, ``PRICE`` and ``HEARTBEAT``
* ``GET {api}/v3/instruments/{instrument}/candles`` — ``price=BA``, ``count`` ≤ 5000
* ``GET {api}/v3/accounts/{id}/instruments`` — instrument metadata (pip location, precision)

Hard rule 6: this module never calls order, trade or position endpoints. The OANDA practice account
is a free data source, not the owner's broker account.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Literal

import httpx
import orjson

from app.core.time import ensure_utc, parse_rfc3339, utc_now
from app.data.adapters.base import AdapterError, AdapterHealth, AdapterNotConfigured
from app.data.adapters.http import get, raise_for_status
from app.data.models import Bar, Heartbeat, Quote
from app.data.timeframes import Timeframe, bucket_end, bucket_start

HOSTS = {
    "practice": ("https://api-fxpractice.oanda.com", "https://stream-fxpractice.oanda.com"),
    "live": ("https://api-fxtrade.oanda.com", "https://stream-fxtrade.oanda.com"),
}
SOURCE = "oanda"


class CandleAlignmentError(AdapterError):
    """A provider candle does not start on our bucket boundary — alignment assumption is wrong."""


class OandaAdapter:
    name = SOURCE

    def __init__(
        self,
        token: str | None,
        account_id: str | None,
        symbols: dict[str, str],
        environment: Literal["practice", "live"] = "practice",
        transport: httpx.AsyncBaseTransport | None = None,
        page_size: int = 5000,
    ) -> None:
        if not token or not account_id:
            raise AdapterNotConfigured("OANDA_API_TOKEN and OANDA_ACCOUNT_ID are required")
        self._account = account_id
        self._to_oanda = dict(symbols)
        self._from_oanda = {v: k for k, v in symbols.items()}
        self.page_size = page_size
        api, stream = HOSTS[environment]
        headers = {"Authorization": f"Bearer {token}", "Accept-Datetime-Format": "RFC3339"}
        self._api = httpx.AsyncClient(base_url=api, headers=headers, timeout=20, transport=transport)
        # Streaming: no read timeout on the client — the watchdog detects silence (heartbeats ~5 s).
        self._stream = httpx.AsyncClient(
            base_url=stream, headers=headers, timeout=httpx.Timeout(10, read=None), transport=transport
        )

    async def aclose(self) -> None:
        await self._api.aclose()
        await self._stream.aclose()

    # ------------------------------------------------------------------ parsing (pure)
    def parse_stream_line(self, line: bytes | str, received_at: datetime | None = None) -> Quote | Heartbeat | None:
        if not line or not line.strip():
            return None
        msg: dict[str, Any] = orjson.loads(line)
        kind = msg.get("type")
        if kind == "HEARTBEAT":
            return Heartbeat(time=parse_rfc3339(msg["time"]), source=SOURCE)
        if kind != "PRICE":
            return None
        symbol = self._from_oanda.get(msg.get("instrument", ""))
        bids, asks = msg.get("bids") or [], msg.get("asks") or []
        if symbol is None or not bids or not asks:
            return None  # unknown instrument or an empty book: no price, never a guessed one
        return Quote(
            instrument=symbol,
            time=parse_rfc3339(msg["time"]),
            bid=Decimal(bids[0]["price"]),
            ask=Decimal(asks[0]["price"]),
            tradeable=bool(msg.get("tradeable", True)),
            source=SOURCE,
            received_at=received_at or utc_now(),
        )

    def parse_candle(self, symbol: str, tf: Timeframe, c: dict[str, Any]) -> Bar:
        open_time = parse_rfc3339(c["time"])
        if bucket_start(open_time, tf) != open_time:
            raise CandleAlignmentError(f"{symbol} {tf} candle at {open_time.isoformat()} is not on a bucket boundary")
        b, a = c["bid"], c["ask"]
        return Bar(
            instrument=symbol,
            timeframe=tf,
            open_time=open_time,
            close_time=bucket_end(open_time, tf),
            bid_o=Decimal(b["o"]),
            bid_h=Decimal(b["h"]),
            bid_l=Decimal(b["l"]),
            bid_c=Decimal(b["c"]),
            ask_o=Decimal(a["o"]),
            ask_h=Decimal(a["h"]),
            ask_l=Decimal(a["l"]),
            ask_c=Decimal(a["c"]),
            volume=int(c.get("volume", 0)),
            complete=bool(c["complete"]),
            source=SOURCE,
        )

    # ------------------------------------------------------------------ network
    async def stream_lines(self, instruments: list[str]) -> AsyncIterator[str]:
        """Raw JSON lines from one streaming connection (also used to record replay fixtures)."""
        names = ",".join(self._to_oanda[s] for s in instruments)
        url = f"/v3/accounts/{self._account}/pricing/stream"
        async with self._stream.stream("GET", url, params={"instruments": names, "snapshot": "true"}) as resp:
            if not resp.is_success:
                await resp.aread()
                raise_for_status(resp, SOURCE)
            async for line in resp.aiter_lines():
                yield line

    async def stream(self, instruments: list[str]) -> AsyncIterator[Quote | Heartbeat]:
        """One streaming connection. Returns/raises when it ends; the caller reconnects."""
        async for line in self.stream_lines(instruments):
            item = self.parse_stream_line(line)
            if item is not None:
                yield item

    async def candles(
        self, instrument: str, tf: Timeframe, start: datetime, end: datetime, include_incomplete: bool = False
    ) -> AsyncIterator[list[Bar]]:
        """Pages of bid/ask candles in [start, end), oldest first."""
        start, end = ensure_utc(start), ensure_utc(end)
        name = self._to_oanda[instrument]
        cursor, first = start, True
        while cursor < end:
            params = {
                "price": "BA",
                "granularity": tf.oanda,
                "from": cursor.isoformat().replace("+00:00", "Z"),
                "count": str(self.page_size),
                "dailyAlignment": "17",
                "alignmentTimezone": "America/New_York",
                "weeklyAlignment": "Friday",
            }
            if not first:
                params["includeFirst"] = "false"
            resp = await get(self._api, f"/v3/instruments/{name}/candles", SOURCE, params=params)
            raise_for_status(resp, SOURCE)
            raw = resp.json().get("candles", [])
            bars = [self.parse_candle(instrument, tf, c) for c in raw]
            page = [b for b in bars if b.open_time < end and (b.complete or include_incomplete)]
            if page:
                yield page
            if len(raw) < self.page_size or not bars:
                return
            cursor, first = bars[-1].open_time, False
            if bars[-1].open_time >= end - timedelta(microseconds=1):
                return

    async def instruments(self) -> list[dict[str, Any]]:
        names = ",".join(self._to_oanda.values())
        resp = await get(self._api, f"/v3/accounts/{self._account}/instruments", SOURCE, params={"instruments": names})
        raise_for_status(resp, SOURCE)
        items: list[dict[str, Any]] = resp.json().get("instruments", [])
        return items

    async def health(self) -> AdapterHealth:
        try:
            found = {i["name"] for i in await self.instruments()}
        except AdapterError as exc:
            return AdapterHealth(source=SOURCE, ok=False, detail=str(exc), checked_at=utc_now())
        missing = sorted(set(self._to_oanda.values()) - found)
        return AdapterHealth(
            source=SOURCE,
            ok=not missing,
            checked_at=utc_now(),
            detail="all instruments available" if not missing else f"instruments missing from account: {missing}",
        )
