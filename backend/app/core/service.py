"""A minimal runner for long-lived asyncio services (scheduler, stream, fast).

Handles: logging setup, the production guard, desk-config validation, a heartbeat loop and
graceful shutdown on SIGTERM/SIGINT. Each service provides a ``status()`` callable that says
what it is doing right now; that string is published in its heartbeat.
"""

from __future__ import annotations

import asyncio
import contextlib
import signal
from collections.abc import Awaitable, Callable, Coroutine
from typing import Any

from redis.asyncio import Redis

from app.core import heartbeat
from app.core.config import get_desk_config, get_settings
from app.core.guards import production_guard
from app.core.logging import configure_logging, get_logger

StatusFn = Callable[[], Awaitable[tuple[str, str]]]
HEARTBEAT_INTERVAL_SECONDS = 10


WorkFn = Callable[[Redis], Coroutine[Any, Any, None]]


async def run_service(name: str, status: StatusFn, work: WorkFn | None = None) -> None:
    settings = get_settings()
    configure_logging(name, settings.log_level)
    log = get_logger()
    production_guard(settings)
    desk = get_desk_config()
    log.info("service_starting", env=settings.app_env.value, assets=len(desk.assets))

    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)

    redis: Redis = Redis.from_url(settings.redis_url)

    async def _beat_forever() -> None:
        while not stop.is_set():
            state, detail = await status()
            try:
                await heartbeat.beat(redis, name, state, detail)
            except Exception as exc:  # Redis blip: log and keep going; healthcheck will flag it
                log.warning("heartbeat_failed", error=str(exc))
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(stop.wait(), timeout=HEARTBEAT_INTERVAL_SECONDS)

    tasks = [asyncio.create_task(_beat_forever())]
    if work is not None:
        tasks.append(asyncio.create_task(work(redis)))
    await stop.wait()
    log.info("service_stopping")
    for t in tasks:
        t.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)
    await redis.aclose()
