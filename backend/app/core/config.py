"""Configuration.

Two sources, deliberately separate:

* ``Settings`` — process environment / ``.env``: secrets, URLs, the runtime environment.
  Secrets are ``SecretStr`` so they never appear in logs or reprs.
* ``DeskConfig`` — ``config/desk.yaml``: the USER CONFIG from SPEC §2 (assets, styles, risk,
  schedules, models). Validated strictly; unknown keys are rejected so typos fail loudly.
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from functools import lru_cache
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import yaml
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]


class AppEnv(StrEnum):
    development = "development"
    test = "test"
    production = "production"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=(REPO_ROOT / ".env"), extra="ignore")

    app_env: AppEnv = AppEnv.development
    desk_config_path: Path = REPO_ROOT / "config" / "desk.yaml"
    log_level: str = "INFO"

    database_url: str = "postgresql+asyncpg://desk:desk@localhost:5432/desk"
    redis_url: str = "redis://localhost:6379/0"

    # Adapters explicitly running in mock mode (comma-separated). Must be empty in production
    # (SPEC §3.2 — enforced by app.core.guards.production_guard).
    mock_adapters: str = ""

    # Provider credentials — all optional until the phase that needs them.
    anthropic_api_key: SecretStr | None = None
    oanda_api_token: SecretStr | None = None
    oanda_account_id: str | None = None
    oanda_environment: Literal["practice", "live"] = "practice"
    twelve_data_api_key: SecretStr | None = None
    fred_api_key: SecretStr | None = None
    eia_api_key: SecretStr | None = None
    fmp_api_key: SecretStr | None = None
    finnhub_api_key: SecretStr | None = None
    cftc_socrata_app_token: SecretStr | None = None
    telegram_bot_token: SecretStr | None = None
    telegram_chat_id: str | None = None
    app_secret_key: SecretStr | None = None  # signs expiring "I took it" deep links (Phase 3)

    @property
    def mock_adapter_list(self) -> list[str]:
        return [a.strip() for a in self.mock_adapters.split(",") if a.strip()]

    def provider_key_status(self) -> dict[str, bool]:
        """Which provider keys are configured. Never exposes the values (SPEC §19.10)."""
        keys = (
            "anthropic_api_key",
            "oanda_api_token",
            "twelve_data_api_key",
            "fred_api_key",
            "eia_api_key",
            "fmp_api_key",
            "finnhub_api_key",
            "cftc_socrata_app_token",
            "telegram_bot_token",
            "app_secret_key",
        )
        return {k: getattr(self, k) is not None for k in keys}


# --------------------------------------------------------------------------- desk.yaml schema

Timeframe = Literal["M1", "M5", "M15", "H1", "H4", "D1", "W1"]
StyleName = Literal["scalp", "intraday", "swing", "position"]
SessionTag = Literal["tokyo_open", "london_open", "london_ny_overlap", "new_york_open"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Asset(_Strict):
    symbol: str
    name: str
    asset_class: Literal["fx", "metal", "energy"]
    quote_ccy: str = Field(pattern=r"^[A-Z]{3}$")


class TimeframeTriplet(_Strict):
    higher: Timeframe
    middle: Timeframe
    lower: Timeframe

    @model_validator(mode="after")
    def _ordered(self) -> TimeframeTriplet:
        order = ["M1", "M5", "M15", "H1", "H4", "D1", "W1"]
        if not order.index(self.higher) > order.index(self.middle) > order.index(self.lower):
            raise ValueError("timeframes must satisfy higher > middle > lower")
        return self


class StyleProfile(_Strict):
    enabled: bool
    mode: Literal["shadow", "live_alerts"]
    timeframes: TimeframeTriplet
    risk_multiplier: Decimal = Field(gt=0, le=1)
    sessions: list[SessionTag] | None = None
    max_trades_per_session: int | None = None
    max_consecutive_losses_per_session: int | None = None
    max_cost_to_tp1: Decimal | None = Field(default=None, gt=0, lt=1)
    signal_validity_minutes: int | None = None
    max_hold_minutes: int | None = None
    max_hold_hours: int | None = None
    max_hold_days: int | None = None
    max_hold_weeks: int | None = None


class Styles(_Strict):
    scalp: StyleProfile
    intraday: StyleProfile
    swing: StyleProfile
    position: StyleProfile


class Leverage(_Strict):
    fx_major: int = Field(gt=0)
    gold: int = Field(gt=0)
    other_commodities: int = Field(gt=0)


class MinRewardRisk(_Strict):
    scalp: Decimal
    intraday: Decimal
    swing: Decimal
    position: Decimal


class Account(_Strict):
    base_currency: str = Field(pattern=r"^[A-Z]{3}$")
    starting_balance: Decimal | None = None
    risk_per_trade_pct: Decimal = Field(gt=0, le=5)
    max_open_risk_pct: Decimal = Field(gt=0)
    max_daily_loss_pct: Decimal = Field(gt=0)
    max_daily_scalp_loss_pct: Decimal = Field(gt=0)
    max_weekly_drawdown_pct: Decimal = Field(gt=0)
    max_consecutive_losses: int = Field(gt=0)
    cooldown_hours: int = Field(ge=0)
    leverage: Leverage
    min_reward_risk: MinRewardRisk


class Execution(_Strict):
    delay_seconds_default: int = Field(ge=0)


class Schedule(_Strict):
    news_cycle: str
    full_pipeline_runs: list[Literal["weekly_open", "pre_tokyo", "pre_london", "pre_new_york"]]
    lead_minutes: int = Field(ge=0, le=240)
    quiet_hours: str = Field(pattern=r"^\d{2}:\d{2}-\d{2}:\d{2}$")
    reconcile_prompt: Literal["daily", "weekly", "off"]


class Notifications(_Strict):
    telegram: bool
    web_push: bool
    email_digest: Literal["daily", "weekly", "off"]


class LlmModels(_Strict):
    triage: str
    analysis: str
    synthesis: str


class Llm(_Strict):
    provider: Literal["anthropic"]
    models: LlmModels
    monthly_budget_usd: Decimal | None = None


class DeskConfig(_Strict):
    project_name: str
    owner_timezone: str
    report_language: Literal["en", "fa"]
    assets: list[Asset]
    broker: str
    market_data_provider: str
    styles: Styles
    execution: Execution
    account: Account
    schedule: Schedule
    notifications: Notifications
    llm: Llm
    data_budget_usd_month: Decimal | None = None
    hosting: Literal["vps_docker"]

    @field_validator("owner_timezone")
    @classmethod
    def _valid_tz(cls, v: str) -> str:
        try:
            ZoneInfo(v)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(f"unknown timezone {v!r}") from exc
        return v

    @field_validator("assets")
    @classmethod
    def _unique_symbols(cls, v: list[Asset]) -> list[Asset]:
        symbols = [a.symbol for a in v]
        if len(symbols) != len(set(symbols)):
            raise ValueError("asset symbols must be unique")
        return v

    def open_questions(self) -> list[str]:
        """Config values the owner still has to decide (surfaced in /health/config)."""
        missing = []
        if self.account.starting_balance is None:
            missing.append("account.starting_balance")
        if self.llm.monthly_budget_usd is None:
            missing.append("llm.monthly_budget_usd")
        if self.data_budget_usd_month is None:
            missing.append("data_budget_usd_month")
        if self.market_data_provider == "tbd":
            missing.append("market_data_provider")
        return missing


def load_desk_config(path: Path) -> DeskConfig:
    with path.open(encoding="utf-8") as fh:
        raw = yaml.safe_load(fh)
    return DeskConfig.model_validate(raw)


@lru_cache
def get_settings() -> Settings:
    return Settings()


@lru_cache
def get_desk_config() -> DeskConfig:
    return load_desk_config(get_settings().desk_config_path)
