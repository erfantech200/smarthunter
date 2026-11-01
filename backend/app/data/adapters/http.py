"""Shared httpx helpers: status → typed adapter errors, never logging credentials."""

from __future__ import annotations

from typing import Any

import httpx

from app.data.adapters.base import AdapterAuthError, AdapterError, AdapterRateLimited


def raise_for_status(resp: httpx.Response, source: str) -> None:
    if resp.is_success:
        return
    code = resp.status_code
    body = resp.text[:300]
    if code in (401, 403):
        raise AdapterAuthError(f"{source}: HTTP {code} — credentials rejected")
    if code == 429:
        ra = resp.headers.get("Retry-After")
        raise AdapterRateLimited(f"{source}: rate limited", float(ra) if ra and ra.isdigit() else None)
    raise AdapterError(f"{source}: HTTP {code}: {body}")


async def get(client: httpx.AsyncClient, url: str, source: str, **kwargs: Any) -> httpx.Response:
    """GET that turns transport failures (DNS, connect, timeout) into AdapterError."""
    try:
        return await client.get(url, **kwargs)
    except httpx.TransportError as exc:
        raise AdapterError(f"{source}: {type(exc).__name__}: {exc}") from exc
