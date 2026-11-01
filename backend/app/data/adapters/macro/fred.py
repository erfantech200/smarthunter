"""FRED (St. Louis Fed) macro series with point-in-time timestamps (SPEC §3.5, §6 A2).

``GET https://api.stlouisfed.org/fred/series/observations`` with ``output_type=4`` (initial release
only) and a full real-time window returns each observation with ``realtime_start`` = the date it
was first published. ``published_at`` is set to the END of that date in America/Chicago (FRED's
home zone), which is conservative: a feature at time t only sees values FRED had certainly
published by t. Missing values (".") are skipped, never filled.
"""

from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo

import httpx
from pydantic import BaseModel

from app.core.time import utc_now
from app.data.adapters.base import AdapterError, AdapterHealth, AdapterNotConfigured
from app.data.adapters.http import get, raise_for_status

SOURCE = "fred"
BASE = "https://api.stlouisfed.org/fred"
CHICAGO = ZoneInfo("America/Chicago")
NEW_YORK = ZoneInfo("America/New_York")


class MacroObservation(BaseModel):
    series_id: str
    obs_date: date
    value: Decimal
    event_time: datetime  # end of the observation day (New York close)
    published_at: datetime  # end of the first-release date, America/Chicago
    source: str = SOURCE


def parse_observations(series_id: str, payload: dict) -> list[MacroObservation]:  # type: ignore[type-arg]
    out = []
    for o in payload.get("observations", []):
        if o.get("value") in (None, ".", ""):
            continue
        d = date.fromisoformat(o["date"])
        rt = date.fromisoformat(o["realtime_start"])
        out.append(
            MacroObservation(
                series_id=series_id,
                obs_date=d,
                value=Decimal(o["value"]),
                event_time=datetime.combine(d, time(17, 0), tzinfo=NEW_YORK).astimezone(ZoneInfo("UTC")),
                published_at=datetime.combine(rt, time(23, 59, 59), tzinfo=CHICAGO).astimezone(ZoneInfo("UTC")),
            )
        )
    return out


class FredAdapter:
    name = SOURCE

    def __init__(self, api_key: str | None, transport: httpx.AsyncBaseTransport | None = None) -> None:
        if not api_key:
            raise AdapterNotConfigured("FRED_API_KEY is required")
        self._key = api_key
        self._client = httpx.AsyncClient(base_url=BASE, timeout=30, transport=transport)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def observations(self, series_id: str, start: date) -> list[MacroObservation]:
        resp = await get(
            self._client,
            "/series/observations",
            SOURCE,
            params={
                "series_id": series_id,
                "api_key": self._key,
                "file_type": "json",
                "observation_start": start.isoformat(),
                "realtime_start": "1776-07-04",
                "realtime_end": "9999-12-31",
                "output_type": "4",
            },
        )
        raise_for_status(resp, SOURCE)
        return parse_observations(series_id, resp.json())

    async def health(self) -> AdapterHealth:
        try:
            await self.observations("DGS10", utc_now().date().replace(day=1))
            return AdapterHealth(source=SOURCE, ok=True, detail="observations endpoint ok", checked_at=utc_now())
        except AdapterError as exc:
            return AdapterHealth(source=SOURCE, ok=False, detail=str(exc), checked_at=utc_now())
