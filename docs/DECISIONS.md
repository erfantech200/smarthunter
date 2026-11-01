# Architecture Decision Records

Format: context → decision → consequences. Status is **Accepted** (in effect), **Proposed** (needs your approval) or **Superseded**.

---

## ADR-001 — Monorepo, Python toolchain and quality gates (Accepted, 2026-11-01)
**Context.** SPEC §20–21: Python 3.12 backend and a Next.js frontend in one repo, with CI on lint, typecheck and tests.
**Decision.**
- `backend/` is one Python package (`app`), managed by **uv** (lockfile committed). The same image runs every Python service with a different command.
- **ruff** handles lint and format. **mypy runs in strict mode** with the pydantic plugin. **pytest** + **hypothesis** handle tests.
- `frontend/` uses Next.js App Router + TypeScript (strict, `noUncheckedIndexedAccess`) + Tailwind 4, with ESLint (`eslint-config-next`) and `tsc --noEmit`.
- pre-commit runs ruff, mypy, gitleaks and the standard hygiene hooks. GitHub Actions runs `backend`, `frontend` and `stack` jobs. The stack job boots the full compose stack and checks the health endpoints.

**Consequences.** One `make test` runs offline with no keys. CI proves `make up`-equivalent boots on every push.

## ADR-002 — Postgres image: `timescale/timescaledb-ha:pg17` (Accepted)
**Context.** SPEC §18 needs TimescaleDB *and* pgvector.
**Decision.** Use Timescale's HA image, which ships both extensions (verified at boot: timescaledb 2.31, vector 0.8.7) on Postgres 17. Migration `0001_extensions` enables them. `/health/ready` fails if either is missing.
**Consequences.** It's a large image (about 1 GB). Backups use `pg_dump` plus Timescale-aware restore, tested in Phase 3 (the My Book drill) and Phase 11.

## ADR-003 — Job queue: Arq rather than Celery (Accepted)
**Context.** SPEC §20 asks for Arq or Celery, with the choice justified.
**Decision.** **Arq.**
- The backend is asyncio throughout (httpx, asyncpg, the Anthropic async client). Arq runs `async def` jobs natively, while Celery would need `asyncio.run` shims per task.
- Arq is small, Redis-only, and we already run Redis for streams, pub/sub and snapshots. It covers retries, timeouts, job IDs for idempotency (`_job_id`) and cron.
- Celery's strengths (multiple brokers, canvas workflows, a big ecosystem) aren't needed. The orchestrator DAG is our own thin code (SPEC §24.6).

**Risks / mitigation.** Arq's release cadence is slow. Job code calls our own `enqueue()` / job-registry interface, so swapping to Celery, SAQ or Taskiq stays local to `app/worker.py` and `app/orchestrator`. The dead-letter queue and "job keeps failing" alerts (SPEC §16) are ours, built on Arq's retry hooks.

## ADR-004 — Scheduler: our own DST-aware service, not cron (Accepted)
**Context.** Session runs happen `lead_minutes` before the Tokyo, London and New York opens. Melbourne, London and New York follow **three different DST rules**, so a fixed cron in any one zone drifts by an hour for several weeks each year (see STYLES.md §Session clock).
**Decision.** A dedicated `scheduler` process computes each next fire time in UTC with `zoneinfo` (the session open in its home zone, minus the lead), then enqueues Arq jobs with idempotent IDs such as `pre_london:2026-11-02`. A Redis lock prevents overlapping runs per asset (SPEC §6 A0). Phase 0 ships the process with a 60-second `probe` job that proves the scheduler → Redis → worker path.
**Consequences.** DST correctness is unit-testable with fixed dates. No host crontab.

## ADR-005 — Service health model: heartbeats in Redis (Accepted)
**Context.** Only `api` and `web` have HTTP ports. The worker, scheduler, stream and fast services need health checks too.
**Decision.** Each long-running service writes `desk:heartbeat:<service>` (JSON with status and detail, 30-second TTL) every 10 seconds. The Docker healthcheck runs `python -m app.core.heartbeat <service>`, and `GET /health/services` aggregates them, returning 503 if any are missing. The status vocabulary is `ok | idle | halted | degraded`. **`halted` is the correct state for the fast engine whenever it has no healthy stream or no valid snapshot** (hard rule 4).

## ADR-006 — Primary price feed: OANDA v20 practice account (**Proposed** — needs your approval)
**Context.** SPEC §10 needs a broker-neutral real-time bid/ask stream for all 7 instruments, history, and a second source. See PROVIDERS.md.
**Decision (proposed).** OANDA v20 practice streaming + candles as the primary feed. Twelve Data (free Basic) as the REST cross-check source. Dukascopy ticks for tick-replay backtests.
**Why.** It's free, covers all 7 instruments including both oil benchmarks, offers bid/ask in both stream and candles, and is available in Australia. Every paid alternative still needs a second vendor for oil.
**Trade-offs.**
- The stream is throttled (about 250 ms per instrument), so bar high/low can differ from OANDA's own candles. Phase 1 states a tolerance.
- There's no tick history from OANDA.
- OANDA quotes ≠ your future broker's quotes. This is handled by the basis offset (SPEC §8.4).

## ADR-007 — Partial closes use average-cost accounting (Accepted; SPEC §8.3 asks for this ADR)
**Decision.** Each My Book position carries a weighted-average entry price.
- **Scale-ins** recompute the average: `avg = Σ(lots_i × price_i) / Σ lots_i`.
- **Partial closes** realise P&L against the current average for the closed lots. The average of the remaining lots doesn't change.
- **Initial risk for the R multiple** is fixed at the first fill's stop and size. Adds record their own incremental risk.

**Why.** It's what most retail CFD/FX brokers display, so My Book reconciles with your broker statement. FIFO lots would only matter for tax, which is out of scope.

## ADR-008 — Money and risk values are `Decimal` end to end (Accepted)
Prices, sizes, P&L, percentages and multipliers in config are parsed straight into `Decimal` (`DeskConfig` fields are typed `Decimal`). Floats are allowed only inside indicator math (numpy/pandas) and must be converted at the boundary before any sizing or P&L code. A Phase 3 property test covers this boundary.

## ADR-009 — Default pillar weights per style (Accepted as starting point; SPEC §14 asks for this ADR)
Composite = Σ(wᵢ · relᵢ · scoreᵢ) / Σ(wᵢ · relᵢ). Changes are proposed by A11 and need your approval.

| Pillar | Scalp | Intraday | Swing | Position |
|---|---:|---:|---:|---:|
| Technical (A6) | 0.45 | 0.40 | 0.30 | 0.15 |
| Fundamental / news (A1, by horizon) | 0.05 | 0.15 | 0.20 | 0.20 |
| Macro / regime (A2) | 0.05 | 0.10 | 0.20 | 0.30 |
| Positioning / sentiment (A3) | 0.00 | 0.05 | 0.10 | 0.20 |
| Strategy edge (A5) | 0.45 | 0.30 | 0.20 | 0.15 |

Scalps lean on technical structure and proven edge, and fundamentals act mainly through blackouts and snapshot revocation rather than through the composite. Position trades lean on macro and positioning (SPEC §14 and A3 notes).

## ADR-010 — Secrets and exposure (Accepted)
- Secrets come only from `.env` and are typed `SecretStr`, so they never appear in reprs or JSON. The JSON log processor also redacts any key containing key, token, secret, password or authorization.
- `/health/config` reports only *whether* each key is set.
- Compose binds every published port to `127.0.0.1`. Public exposure goes through Caddy + Tailscale/Cloudflare Access + TOTP in Phase 11 only.
- The production guard refuses to start any service with `MOCK_ADAPTERS` set when `APP_ENV=production` (SPEC §3.2; tested).

## ADR-011 — Statically enforced hard rules (Accepted)
`backend/tests/test_architecture.py` fails CI if `app/fast` imports an LLM client or agent code (hard rule 3), or if order or trade endpoint names appear anywhere in `app/` (hard rule 6). Further structural checks are added as the code grows. For example: no `float` in `app/books`, and `app/agents` gets no write access to My Book.
