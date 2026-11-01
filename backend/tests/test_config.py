from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from app.core.config import REPO_ROOT, DeskConfig, Settings, load_desk_config

DESK_YAML = REPO_ROOT / "config" / "desk.yaml"


def test_committed_desk_config_is_valid() -> None:
    desk = load_desk_config(DESK_YAML)
    assert [a.symbol for a in desk.assets] == ["XAUUSD", "XAGUSD", "EURUSD", "GBPUSD", "USDJPY", "WTI", "BRENT"]
    assert desk.styles.scalp.mode == "shadow"
    assert desk.styles.scalp.risk_multiplier == Decimal("0.25")
    assert isinstance(desk.account.risk_per_trade_pct, Decimal)  # money/risk values are Decimal


def test_open_questions_are_reported_until_answered() -> None:
    desk = load_desk_config(DESK_YAML)
    assert "account.starting_balance" in desk.open_questions()


def _raw() -> dict:  # type: ignore[type-arg]
    return yaml.safe_load(DESK_YAML.read_text())


def test_unknown_keys_are_rejected() -> None:
    raw = _raw()
    raw["account"]["risk_per_trade_pctt"] = 1
    with pytest.raises(ValidationError):
        DeskConfig.model_validate(raw)


def test_timeframe_triplet_must_be_ordered() -> None:
    raw = _raw()
    raw["styles"]["swing"]["timeframes"] = {"higher": "H1", "middle": "H4", "lower": "D1"}
    with pytest.raises(ValidationError):
        DeskConfig.model_validate(raw)


def test_bad_timezone_rejected() -> None:
    raw = _raw()
    raw["owner_timezone"] = "Mars/Olympus"
    with pytest.raises(ValidationError):
        DeskConfig.model_validate(raw)


def test_duplicate_assets_rejected() -> None:
    raw = _raw()
    raw["assets"].append(raw["assets"][0])
    with pytest.raises(ValidationError):
        DeskConfig.model_validate(raw)


def test_secrets_never_render(tmp_path: Path) -> None:
    s = Settings(anthropic_api_key="sk-ant-very-secret", _env_file=None)  # type: ignore[call-arg]
    assert "very-secret" not in repr(s)
    assert "very-secret" not in s.model_dump_json()
    assert s.provider_key_status()["anthropic_api_key"] is True
