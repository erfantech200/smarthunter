"""Service heartbeats in Redis.

Long-running services (worker, scheduler, stream, fast) have no HTTP port. Each one writes a
heartbeat key with a short TTL; the API's ``/health/services`` reads them, and the Docker
healthcheck for each container runs ``python -m app.core.heartbeat <service>``.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime

import orjson
from pydantic import BaseModel
from redis.asyncio import Redis

from app.core.config import get_settings

SERVICES = ("worker", "scheduler", "stream", "fast")
HEARTBEAT_TTL_SECONDS = 30
_KEY = "desk:heartbeat:{service}"


class Heartbeat(BaseModel):
    service: str
    status: str  # ok | idle | halted | degraded
    detail: str = ""
    at: datetime


async def beat(redis: Redis, service: str, status: str, detail: str = "") -> None:
    hb = Heartbeat(service=service, status=status, detail=detail, at=datetime.now(UTC))
    await redis.set(_KEY.format(service=service), hb.model_dump_json(), ex=HEARTBEAT_TTL_SECONDS)


async def read(redis: Redis, service: str) -> Heartbeat | None:
    raw = await redis.get(_KEY.format(service=service))
    if raw is None:
        return None
    return Heartbeat.model_validate(orjson.loads(raw))


async def _check(service: str) -> int:
    redis: Redis = Redis.from_url(get_settings().redis_url)
    try:
        hb = await read(redis, service)
    finally:
        await redis.aclose()
    return 0 if hb is not None else 1


if __name__ == "__main__":  # Docker healthcheck entrypoint
    sys.exit(asyncio.run(_check(sys.argv[1])))
