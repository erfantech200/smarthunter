"""Startup guards.

SPEC §3.2: "A production guard refuses to start if any adapter is in mock mode."
Every service entrypoint calls :func:`production_guard` before doing anything else.
"""

from __future__ import annotations

from app.core.config import AppEnv, Settings


class ProductionGuardError(RuntimeError):
    """Raised when the process would run in production with an unsafe configuration."""


def production_guard(settings: Settings) -> None:
    if settings.app_env is not AppEnv.production:
        return
    mocks = settings.mock_adapter_list
    if mocks:
        raise ProductionGuardError(
            f"Refusing to start in production with mock adapters enabled: {', '.join(mocks)}. "
            "Mocks and fixtures exist only in tests (SPEC §3.2)."
        )
