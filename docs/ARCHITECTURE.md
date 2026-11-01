# Architecture

SPEC §4 has the full diagram. This document records how it maps onto processes, storage and code, and is updated as each phase lands.

## Processes (docker compose, one VPS)

| Service | Image / command | Role | Health |
|---|---|---|---|
| `db` | timescaledb-ha:pg17 | Postgres 17 + TimescaleDB + pgvector: evidence, features, books, runs | `pg_isready` |
| `redis` | redis:7.4 (AOF on) | Streams, pub/sub, Context Snapshots, kill flags, Arq queue, heartbeats | `redis-cli ping` |
| `migrate` | backend · `alembic upgrade head` | One-shot schema migration before anything else starts | exits 0 |
| `api` | backend · uvicorn | FastAPI: UI/API, SSE for the Live screen (Phase 8), Telegram webhook (Phase 3) | `/health/ready` |
| `worker` | backend · `arq app.worker.WorkerSettings` | Slow-loop jobs: agent runs, backfills, research, A11 | heartbeat |
| `scheduler` | backend · `python -m app.orchestrator.scheduler` | DST-aware session runs, news cycle, candle-close triggers, locks | heartbeat |
| `stream` | backend · `python -m app.stream.feed_consumer` | Price-feed consumer → bar builder (M1→W1) → Redis; stream watchdog | heartbeat |
| `fast` | backend · `python -m app.fast.engine` | A12: deterministic signals inside the current Context Snapshot | heartbeat |
| `web` | frontend · Next.js standalone | Mobile-first PWA | `/api/health` |

Phase 11 adds Caddy (TLS) and the private-access layer. Until then, every port binds to `127.0.0.1`.

**Why `stream` and `fast` are separate processes.** A12 must keep a p95 of 5 seconds or less from tick to alert, and must halt the moment the stream is unhealthy. Keeping it out of the API and worker processes means a slow LLM call, a large backfill or a GC pause elsewhere can't stall it. `app/fast` may not import any LLM or agent code, and `backend/tests/test_architecture.py` enforces that.

## Data flow and Redis naming (planned; fixed in the phases noted)

| Key / channel | Writer → reader | Phase |
|---|---|---|
| `desk:heartbeat:<service>` | every service → api / healthchecks | 0 ✅ |
| `stream:ticks:<asset>` (Redis Stream) | stream → fast, A10 | 1 |
| `stream:bars:<asset>:<tf>` (Redis Stream, closed bars) | stream → fast, scheduler (candle-close triggers) | 1 |
| `desk:stream:status` | stream watchdog → fast (halts on CRITICAL), api | 1 |
| `desk:snapshot:<asset>` (signed JSON, `valid_until`) | A9 / revocations → fast | 7 |
| `desk:kill:<asset>` / `desk:kill:all` | A1 breaking news, A0 → fast | 7–8 |
| `pub:alerts` | fast, A9, A10 → notifier, api SSE | 3, 8 |
| Arq queue `arq:queue` | scheduler, api → worker | 0 ✅ |

## Storage (SPEC §18)
- Postgres is the system of record. Time series (`ticks`, `candles`, `features`) are hypertables with compression and retention policies.
- Every agent-facing row has `event_time`, `published_at` and `ingested_at` in UTC (point-in-time correctness, SPEC §3.5).
- The evidence store gives each external datum a stable `evidence_id`. Agents cite these IDs, and the validator rejects uncited claims.
- **My Book tables are append-only.** Entries are voided with a reason, never deleted. They're backed up nightly to encrypted off-site storage, with a tested restore (Phase 3 drill).
- Redis holds only reconstructible or short-lived state. The exception is the Arq queue, which runs with AOF persistence.

## Code layout (SPEC §21)
`backend/app/` follows §21 exactly. Each subpackage's `__init__.py` docstring names the phase that fills it in. Shared modules (sizing, exits, costs, delay, P&L) live once in `risk/`, `books/` and `backtest/` and are imported by backtests, the System Book and My Book alike (hard rule 11).

## Boundaries that are never crossed
1. No broker connection or order placement (hard rule 6). Price adapters call read-only pricing and candle endpoints.
2. My Book changes only through API endpoints you trigger: a form submit, a Telegram button tap, or a reconcile tap. No background job writes to it (hard rule 7).
3. LLM agents receive inputs and return validated JSON. They have read-only tools, and no tool can write config or the ledger (SPEC §3.11).
4. Production refuses to start if any adapter is mocked (SPEC §3.2; `app/core/guards.py`).
