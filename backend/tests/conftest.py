from __future__ import annotations

from collections.abc import Iterator

import pytest

from app.core import config


@pytest.fixture(autouse=True)
def _clear_config_caches() -> Iterator[None]:
    config.get_settings.cache_clear()
    config.get_desk_config.cache_clear()
    yield
    config.get_settings.cache_clear()
    config.get_desk_config.cache_clear()
