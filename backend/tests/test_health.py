from __future__ import annotations

from collections.abc import Iterator

import fakeredis.aioredis
import pytest
from fastapi.testclient import TestClient

from app.api import main
from app.core import heartbeat


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    fake = fakeredis.aioredis.FakeRedis()
    monkeypatch.setattr(main.Redis, "from_url", staticmethod(lambda *_a, **_k: fake))
    with TestClient(main.app) as c:
        yield c


def test_liveness(client: TestClient) -> None:
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["disclaimer"] == "Decision support only. Not financial advice."


def test_services_missing_heartbeats_is_503(client: TestClient) -> None:
    r = client.get("/health/services")
    assert r.status_code == 503
    assert r.json()["stream"]["status"] == "missing"


def test_services_with_heartbeats_is_200(client: TestClient) -> None:
    redis = main.app.state.redis
    for name in heartbeat.SERVICES:
        client.portal.call(heartbeat.beat, redis, name, "ok")  # type: ignore[union-attr]
    r = client.get("/health/services")
    assert r.status_code == 200
    assert {v["status"] for v in r.json().values()} == {"ok"}


def test_config_endpoint_never_returns_secret_values(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-should-not-leak")
    main.get_settings.cache_clear()
    r = client.get("/health/config")
    assert r.status_code == 200
    assert "should-not-leak" not in r.text
    assert r.json()["provider_keys_configured"]["anthropic_api_key"] is True
