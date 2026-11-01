"""A12 Fast Signal Engine process (SPEC §6 A12, §7.3).

Code only — no LLM is ever imported here (hard rule 3). Phase 0 scaffold: there is no live
stream and no Context Snapshot yet, so the engine is ``halted`` by design: it may act only
inside a valid snapshot with a healthy stream (hard rule 4). Phase 8 adds the snapshot reader,
detectors and templated alerts.
"""

from __future__ import annotations

import asyncio

from app.core.service import run_service


async def status() -> tuple[str, str]:
    return "halted", "no healthy stream and no valid Context Snapshot (expected until Phase 8)"


def main() -> None:
    asyncio.run(run_service("fast", status))


if __name__ == "__main__":
    main()
