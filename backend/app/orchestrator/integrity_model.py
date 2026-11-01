"""Shared integrity types (SPEC §6 A0): ``IntegrityReport {status, issues[], stale_sources[]}``."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class Status(StrEnum):
    OK = "OK"
    DEGRADED = "DEGRADED"
    CRITICAL = "CRITICAL"

    @property
    def rank(self) -> int:
        return {"OK": 0, "DEGRADED": 1, "CRITICAL": 2}[self.value]


def worst(*statuses: Status) -> Status:
    return max(statuses, key=lambda s: s.rank, default=Status.OK)


class Issue(BaseModel):
    check: str  # freshness | gap | outlier | cross_source | spread | stream | macro_freshness | reconciliation
    severity: Status
    instrument: str | None = None
    source: str | None = None
    message: str
    data: dict[str, Any] = Field(default_factory=dict)


class IntegrityReport(BaseModel):
    as_of: datetime
    status: Status
    issues: list[Issue] = Field(default_factory=list)
    stale_sources: list[str] = Field(default_factory=list)

    @classmethod
    def from_issues(
        cls, as_of: datetime, issues: list[Issue], stale_sources: list[str] | None = None
    ) -> IntegrityReport:
        return cls(
            as_of=as_of,
            status=worst(*(i.severity for i in issues)),
            issues=issues,
            stale_sources=sorted(set(stale_sources or [])),
        )

    def for_instrument(self, symbol: str) -> Status:
        """Status relevant to one instrument: its own issues plus global (instrument=None) ones."""
        return worst(*(i.severity for i in self.issues if i.instrument in (None, symbol)))
