# Trade Desk

A private, single-user research desk for FX and commodities: gold, silver, EUR/USD, GBP/USD, USD/JPY, WTI and Brent. Specialised agents turn live, timestamped data into evidence-backed trade plans and fast signals, or an explicit **NO_TRADE / WAIT**. There's no broker connection: the owner trades manually and logs fills in the internal ledger (My Book).

> Decision support only. Not financial advice.

- Spec: [`SPEC.md`](SPEC.md)
- Plan and status: [`docs/PLAN.md`](docs/PLAN.md)
- Architecture: [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md)

## Quick start
Requirements: Docker with Compose v2, `make`. For local development you also need [uv](https://docs.astral.sh/uv/) and Node 22.

```bash
make up      # creates .env from .env.example on first run, builds, starts and health-checks every service
```
```bash
make test
```
Open http://127.0.0.1:3000 for the UI, or http://127.0.0.1:8000/health/services for the API.
