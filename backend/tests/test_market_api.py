from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator, Iterator
from typing import Any

import fakeredis.aioredis
import pytest
from fastapi.testclient import TestClient

from app.api import main
from app.core import keys
from app.data import jobs
from tests.factories import q, utc


class _FakeEngine:
    @contextlib.asynccontextmanager
    async def connect(self) -> AsyncIterator[None]:
        yield None


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    fake = fakeredis.aioredis.FakeRedis()
    monkeypatch.setattr(main.Redis, "from_url", staticmethod(lambda *_a, **_k: fake))
    monkeypatch.setattr(jobs, "get_engine", lambda: _FakeEngine())

    async def no_macro(_: Any) -> dict[str, Any]:
        return {}

    monkeypatch.setattr(jobs.store, "latest_macro", no_macro)
    with TestClient(main.app) as c:
        yield c


def test_status_without_stream_is_critical_not_invented(client: TestClient) -> None:
    r = client.get("/market/status")
    assert r.status_code == 200
    body = r.json()
    assert body["integrity"]["status"] == "CRITICAL"
    assert body["stream"] is None


def test_quotes_reports_missing_as_null(client: TestClient) -> None:
    redis = main.app.state.redis
    client.portal.call(redis.set, keys.quote("EURUSD"), q(utc(2026, 11, 4, 13), "1.08000", "1.08010").model_dump_json())  # type: ignore[union-attr]
    body = client.get("/market/quotes").json()
    assert body["EURUSD"]["spread"] == "0.00010"
    assert body["XAUUSD"] is None


def test_unknown_symbol_404(client: TestClient) -> None:
    assert client.get("/market/bars/DOGEUSD/M1").status_code == 404
