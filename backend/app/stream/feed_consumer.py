"""Streaming service: price-feed consumer + bar builder (SPEC §4, §20).

Phase 0 scaffold: no price adapter is wired yet, so the service reports ``idle`` and does
nothing else. It never generates or replays prices outside tests (SPEC §3.2).
Phase 1 adds the adapter interface (fetch/stream/backfill/health), the M1→W1 bar builder and
the stream watchdog.
"""

from __future__ import annotations

import asyncio

from app.core.config import get_desk_config
from app.core.service import run_service


async def status() -> tuple[str, str]:
    provider = get_desk_config().market_data_provider
    return "idle", f"no price adapter wired yet (market_data_provider={provider}; Phase 1)"


def main() -> None:
    asyncio.run(run_service("stream", status))


if __name__ == "__main__":
    main()
