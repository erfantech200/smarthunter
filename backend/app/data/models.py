"""Market-data domain types. Prices are ``Decimal`` taken verbatim from the provider's strings."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from app.core.time import ensure_utc
from app.data.timeframes import Timeframe

TWO = Decimal(2)


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Quote(_Frozen):
    """One top-of-book price from a streaming or polling source."""

    instrument: str  # internal symbol, e.g. "XAUUSD"
    time: datetime  # provider timestamp of the price (event_time)
    bid: Decimal
    ask: Decimal
    source: str
    tradeable: bool = True
    received_at: datetime | None = None  # ingested_at

    @field_validator("time", "received_at")
    @classmethod
    def _utc(cls, v: datetime | None) -> datetime | None:
        return None if v is None else ensure_utc(v)

    @property
    def mid(self) -> Decimal:
        return (self.bid + self.ask) / TWO

    @property
    def spread(self) -> Decimal:
        return self.ask - self.bid


class Heartbeat(_Frozen):
    time: datetime
    source: str


class Bar(_Frozen):
    """A bid/ask OHLC bar. ``open_time`` is the bucket start (OANDA convention), ``close_time`` its end.

    Point in time: a bar is knowable only at ``close_time`` (complete) — readers filter on it.
    """

    instrument: str
    timeframe: Timeframe
    open_time: datetime
    close_time: datetime
    bid_o: Decimal
    bid_h: Decimal
    bid_l: Decimal
    bid_c: Decimal
    ask_o: Decimal
    ask_h: Decimal
    ask_l: Decimal
    ask_c: Decimal
    volume: int  # tick volume — a relative-activity proxy only (SPEC §6 A6)
    complete: bool
    source: Literal["oanda", "stream", "dukascopy", "twelvedata"] | str

    @field_validator("open_time", "close_time")
    @classmethod
    def _utc(cls, v: datetime) -> datetime:
        return ensure_utc(v)

    @model_validator(mode="after")
    def _consistent(self) -> Bar:
        if self.close_time <= self.open_time:
            raise ValueError("close_time must be after open_time")
        for side in ("bid", "ask"):
            o, h, low, c = (getattr(self, f"{side}_{k}") for k in "ohlc")
            if not (low <= o <= h and low <= c <= h):
                raise ValueError(f"{side} OHLC inconsistent: o={o} h={h} l={low} c={c}")
        return self

    @property
    def mid_c(self) -> Decimal:
        return (self.bid_c + self.ask_c) / TWO

    @property
    def mid_h(self) -> Decimal:
        return (self.bid_h + self.ask_h) / TWO

    @property
    def mid_l(self) -> Decimal:
        return (self.bid_l + self.ask_l) / TWO

    @property
    def spread_c(self) -> Decimal:
        return self.ask_c - self.bid_c
