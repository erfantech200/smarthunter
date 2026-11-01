# Runbook

Grows with each phase. Phase 11 completes it: rotate keys, restore, add a broker profile, switch the price feed, promote a style.

## Start / stop
```bash
make up                  # build, start, wait for health, print health endpoints
make ps                  # container status
make logs SERVICE=api    # follow one service's logs
make down                # stop (data volumes kept)
```

## Health
- `GET http://127.0.0.1:8000/health`: API process alive.
- `GET /health/ready`: Postgres (with TimescaleDB + pgvector) and Redis reachable.
- `GET /health/services`: heartbeats from worker, scheduler, stream and fast. Returns 503 if any is missing.
- `GET /health/config`: config summary, open decisions, and which provider keys are set (never their values).

Expected Phase 0 states: `stream: idle` (no adapter yet) and `fast: halted` (no stream or snapshot). Both are correct.

## Market data (Phase 1)
| Task | Command |
|---|---|
| Are the providers reachable with my keys? | `make check-sources` |
| Load or refresh instruments, broker profiles and symbol maps from `config/` | `make seed` (keeps specs you confirmed) |
| Backfill history (resumable; narrow with `SYMBOL=EURUSD TF=M1`) | `make backfill` |
| What history do I have? | `make coverage` |
| Integrity right now | `make integrity`, or the overview page |
| Gap report | `make gaps DAYS=7` |
| Live vs provider bars | `make reconcile HOURS=6` |
| Disconnect drill | `make disconnect-drill` |
| Record real stream data for tests | `make record-stream SECONDS=600` |

**Reading the integrity status**
- **CRITICAL:** the stream is down or silent for more than 15 s, or a quote is crossed. The fast engine halts, and nothing downstream may act on prices.
- **DEGRADED:** an instrument is stale while its market is open, a spread is over 5× typical, an outlier is unconfirmed, the cross-check is missing or disagrees, or a macro series is more than 5 days old. That pillar's reliability is lowered, and the gap is shown.

**An unexplained gap or an "edge of hours" note** usually means the trading hours in `config/market.yaml` differ from your provider's real hours. Fix the config, re-run `make gaps`, and record the change in docs/PROVIDERS.md.

## Never do
- Run `make clean` without a fresh, verified backup. It deletes the Postgres volume, which holds My Book.
- Set `MOCK_ADAPTERS` in production. The services refuse to start.
