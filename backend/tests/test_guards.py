from __future__ import annotations

import pytest

from app.core.config import AppEnv, Settings
from app.core.guards import ProductionGuardError, production_guard


def _settings(env: AppEnv, mocks: str) -> Settings:
    return Settings(app_env=env, mock_adapters=mocks, _env_file=None)  # type: ignore[call-arg]


def test_production_refuses_mock_adapters() -> None:
    with pytest.raises(ProductionGuardError, match="prices_oanda"):
        production_guard(_settings(AppEnv.production, "prices_oanda, news"))


def test_production_without_mocks_starts() -> None:
    production_guard(_settings(AppEnv.production, ""))


@pytest.mark.parametrize("env", [AppEnv.development, AppEnv.test])
def test_mocks_allowed_outside_production(env: AppEnv) -> None:
    production_guard(_settings(env, "prices_oanda"))
