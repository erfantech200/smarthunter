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

## Never do
- Run `make clean` without a fresh, verified backup. It deletes the Postgres volume, which holds My Book.
- Set `MOCK_ADAPTERS` in production. The services refuse to start.
