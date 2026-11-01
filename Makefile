# Trade Desk — developer entrypoints. Run from the repo root.
COMPOSE := docker compose -f infra/docker-compose.yml --env-file .env
BACKEND := cd backend && uv run

.PHONY: help setup up down restart logs ps health migrate test test-backend test-frontend lint fmt typecheck clean \
	check-sources seed backfill macro spreads gaps reconcile coverage integrity record-stream disconnect-drill

help:            ## list targets
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | sed 's/:.*##/\t/'

.env:
	cp .env.example .env
	@echo "Created .env from .env.example — fill in keys as each phase needs them."

setup: .env      ## install backend + frontend deps locally and the pre-commit hooks
	cd backend && uv sync
	cd frontend && npm ci
	uvx pre-commit install

up: .env         ## build and start every service; waits until all are healthy
	$(COMPOSE) up -d --build --wait --wait-timeout 180
	@$(MAKE) --no-print-directory health

down:            ## stop the stack (data volumes are kept)
	$(COMPOSE) down

restart: down up ## restart the stack

logs:            ## follow logs (SERVICE=api to filter)
	$(COMPOSE) logs -f $(SERVICE)

ps:              ## container status
	$(COMPOSE) ps

health:          ## query every health endpoint
	@curl -fsS http://127.0.0.1:8000/health && echo
	@curl -fsS http://127.0.0.1:8000/health/ready && echo
	@curl -fsS http://127.0.0.1:8000/health/services && echo
	@curl -fsS http://127.0.0.1:3000/api/health && echo

migrate:         ## apply DB migrations
	$(COMPOSE) run --rm migrate

# --- market data (Phase 1) — run inside the stack; needs keys in .env --------------------------------
DESKCLI := $(COMPOSE) exec -T worker python -m app.data.cli

check-sources:   ## live connectivity check of OANDA, Twelve Data, FRED
	$(DESKCLI) check-sources

seed:            ## load instruments, broker profiles, specs, symbol maps from config/
	$(DESKCLI) seed

backfill:        ## provider candle history (SYMBOL=EURUSD TF=M1 to narrow); resumable
	$(DESKCLI) backfill $(if $(SYMBOL),--symbol $(SYMBOL)) $(if $(TF),--tf $(TF))

macro:           ## FRED macro reference series
	$(DESKCLI) macro

spreads:         ## spreads by session from the last 30 days of M1 bid/ask
	$(DESKCLI) spreads

gaps:            ## gap report (DAYS=7)
	$(DESKCLI) gaps --days $(or $(DAYS),7)

reconcile:       ## live-built bars vs provider bars (HOURS=6)
	$(DESKCLI) reconcile --hours $(or $(HOURS),6)

coverage:        ## history coverage per instrument × timeframe
	$(DESKCLI) coverage

integrity:       ## current integrity report
	@curl -fsS http://127.0.0.1:8000/market/status && echo

record-stream:   ## record SECONDS (default 300) of the real OANDA stream into tests/stream_recordings/
	$(DESKCLI) record-stream --seconds $(or $(SECONDS),300) --out /tmp/recording.ndjson
	$(COMPOSE) cp worker:/tmp/recording.ndjson tests/stream_recordings/recorded_oanda_$$(date -u +%Y%m%dT%H%MZ).ndjson

disconnect-drill: ## cut the stream container's network for 20 s and show detection time
	infra/scripts/disconnect_drill.sh

test: test-backend test-frontend ## all tests (offline; no keys needed; DB tests use the compose db if up)

test-backend:
	$(BACKEND) pytest

test-frontend:
	cd frontend && npm test

lint:            ## ruff + eslint
	$(BACKEND) ruff check .
	$(BACKEND) ruff format --check .
	cd frontend && npm run lint

fmt:             ## auto-format
	$(BACKEND) ruff check --fix .
	$(BACKEND) ruff format .

typecheck:       ## mypy (strict) + tsc
	$(BACKEND) mypy app
	cd frontend && npm run typecheck

clean:           ## stop the stack AND delete its data volumes (asks first)
	@read -p "Delete the Postgres and Redis volumes? This destroys My Book data. [y/N] " a; [ "$$a" = y ] && $(COMPOSE) down -v || echo aborted
