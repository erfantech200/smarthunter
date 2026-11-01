"""Schemas for ``config/market.yaml`` and ``config/broker_profiles/*.yaml`` (strict; unknown keys fail)."""

from __future__ import annotations

from datetime import date, time
from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Literal
from zoneinfo import ZoneInfo

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.config import REPO_ROOT, get_desk_config
from app.data.timeframes import Timeframe

Weekday = Literal["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
WEEKDAYS: dict[str, int] = {d: i for i, d in enumerate(("mon", "tue", "wed", "thu", "fri", "sat", "sun"))}


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _tz(v: str) -> str:
    ZoneInfo(v)
    return v


class OandaSource(_Strict):
    symbols: dict[str, str]
    stream_reconnect_max_backoff_seconds: int = Field(default=30, gt=0)


class CrossCheck(_Strict):
    symbols: list[str]
    interval_seconds: int = Field(gt=0)


class TwelveDataSource(_Strict):
    symbols: dict[str, str]
    cross_check: CrossCheck


class DukascopySource(_Strict):
    terms_accepted: bool
    symbols: dict[str, str]
    price_divisor: dict[str, int]


class FredSource(_Strict):
    series: dict[str, str]
    backfill_start: date


class Sources(_Strict):
    oanda: OandaSource
    twelvedata: TwelveDataSource
    dukascopy: DukascopySource
    fred: FredSource


class MarketHoursGroup(_Strict):
    instruments: list[str]
    tz: str
    weekly_open: tuple[Weekday, time]
    weekly_close: tuple[Weekday, time]
    daily_breaks: list[tuple[time, time]]

    @field_validator("tz")
    @classmethod
    def _v_tz(cls, v: str) -> str:
        return _tz(v)

    @model_validator(mode="after")
    def _shape(self) -> MarketHoursGroup:
        if self.weekly_open[0] != "sun" or self.weekly_close[0] != "fri":
            raise ValueError("weekly_open must be on sun and weekly_close on fri")
        for start, end in self.daily_breaks:
            if not start < end:
                raise ValueError("daily break must not cross midnight")
        return self


class Window(_Strict):
    tz: str
    start: time
    end: time
    end_tz: str | None = None

    @field_validator("tz", "end_tz")
    @classmethod
    def _v_tz(cls, v: str | None) -> str | None:
        return v if v is None else _tz(v)


class BackfillTf(_Strict):
    start: date | None = None
    start_days_ago: int | None = None

    @model_validator(mode="after")
    def _one(self) -> BackfillTf:
        if (self.start is None) == (self.start_days_ago is None):
            raise ValueError("set exactly one of start / start_days_ago")
        return self


class Backfill(_Strict):
    timeframes: dict[Timeframe, BackfillTf]
    page_size: int = Field(gt=0, le=5000)


class Integrity(_Strict):
    stream_heartbeat_critical_seconds: int = Field(gt=0)
    quote_stale_seconds: int = Field(gt=0)
    cross_check_max_age_seconds: int = Field(gt=0)
    cross_check_tolerance_spreads: Decimal = Field(gt=0)
    outlier_k_atr: Decimal = Field(gt=0)
    spread_max_multiple: Decimal = Field(gt=1)
    gap_min_missing_m1: int = Field(gt=0)
    macro_stale_days: int = Field(gt=0)


class Reconciliation(_Strict):
    min_close_match_rate: Decimal = Field(gt=0, le=1)
    high_low_tolerance_spreads: Decimal = Field(ge=0)
    min_high_low_within_tolerance: Decimal = Field(gt=0, le=1)


class MarketConfig(_Strict):
    primary_price_source: Literal["oanda"]
    sources: Sources
    market_hours: dict[str, MarketHoursGroup]
    rollover: Window
    sessions: dict[Literal["asia", "london", "new_york"], Window]
    session_windows: dict[str, Window]
    backfill: Backfill
    integrity: Integrity
    reconciliation: Reconciliation

    def hours_for(self, symbol: str) -> MarketHoursGroup:
        for g in self.market_hours.values():
            if symbol in g.instruments:
                return g
        raise KeyError(f"no market hours configured for {symbol}")

    def check_covers(self, symbols: list[str]) -> None:
        """Every configured asset must have hours and a symbol in each price source."""
        for s in symbols:
            self.hours_for(s)
            for name, mapping in (
                ("oanda", self.sources.oanda.symbols),
                ("twelvedata", self.sources.twelvedata.symbols),
                ("dukascopy", self.sources.dukascopy.symbols),
            ):
                if s not in mapping:
                    raise ValueError(f"{s} has no {name} symbol in config/market.yaml")


class InstrumentSpec(_Strict):
    broker_symbol: str
    pip: Decimal = Field(gt=0)
    contract_size: Decimal = Field(gt=0)
    contract_unit: str
    lot_step: Decimal = Field(gt=0)
    min_lots: Decimal = Field(gt=0)
    commission_per_lot_usd: Decimal = Field(ge=0)
    confirmed: bool


class BrokerProfile(_Strict):
    id: str = Field(pattern=r"^[a-z0-9_-]+$")
    name: str
    active: bool
    instruments: dict[str, InstrumentSpec]


def load_market_config(path: Path | None = None) -> MarketConfig:
    path = path or REPO_ROOT / "config" / "market.yaml"
    cfg = MarketConfig.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    return cfg


def load_broker_profiles(directory: Path | None = None) -> list[BrokerProfile]:
    directory = directory or REPO_ROOT / "config" / "broker_profiles"
    profiles = [
        BrokerProfile.model_validate(yaml.safe_load(p.read_text(encoding="utf-8")))
        for p in sorted(directory.glob("*.yaml"))
    ]
    if sum(p.active for p in profiles) != 1:
        raise ValueError("exactly one broker profile must be active")
    return profiles


@lru_cache
def get_market_config() -> MarketConfig:
    cfg = load_market_config()
    cfg.check_covers([a.symbol for a in get_desk_config().assets])
    return cfg
