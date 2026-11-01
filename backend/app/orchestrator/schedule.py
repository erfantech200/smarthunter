"""Schedule rules (ADR-004): pure functions that say which slot a job belongs to at time t.

A slot id (e.g. ``integrity:2026-11-04T13:05``) doubles as the Arq job id, so a job can never be
enqueued twice for the same slot even if the scheduler restarts or two instances run.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from zoneinfo import ZoneInfo

from app.core.time import ensure_utc


@dataclass(frozen=True)
class Every:
    seconds: int

    def slot(self, t: datetime) -> str:
        ts = int(ensure_utc(t).timestamp())
        return datetime.fromtimestamp(ts - ts % self.seconds, tz=ZoneInfo("UTC")).strftime("%Y-%m-%dT%H:%M:%S")


@dataclass(frozen=True)
class DailyAt:
    at: time
    tz: str = "UTC"

    def slot(self, t: datetime) -> str | None:
        """The slot id once local time has passed ``at`` today, else None (not due yet)."""
        local = ensure_utc(t).astimezone(ZoneInfo(self.tz))
        return local.date().isoformat() if local.time() >= self.at else None


@dataclass(frozen=True)
class Job:
    name: str  # Arq function name
    rule: Every | DailyAt

    def job_id(self, t: datetime) -> str | None:
        s = self.rule.slot(t)
        return None if s is None else f"{self.name}:{s}"


def phase1_jobs(cross_check_seconds: int) -> list[Job]:
    return [
        Job("probe", Every(60)),
        Job("integrity_job", Every(60)),
        Job("cross_check_job", Every(cross_check_seconds)),
        Job("backfill_job", Every(3600)),  # resumes from the last stored bar per instrument × timeframe
        Job("reconcile_job", Every(3600)),
        Job("macro_job", DailyAt(time(13, 30))),  # after FRED's morning updates (UTC)
        Job("spreads_job", DailyAt(time(22, 30))),
        Job("gaps_job", DailyAt(time(22, 45))),
    ]
