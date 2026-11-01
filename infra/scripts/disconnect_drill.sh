#!/usr/bin/env bash
# Stream-disconnect drill (Phase 1 DoD: "a stream disconnect is detected within seconds").
# Cuts the stream container off its network for 20 s and polls the API until it reports CRITICAL.
set -euo pipefail
C="docker compose -f infra/docker-compose.yml --env-file .env"
NET="trade-desk_default"
CID=$($C ps -q stream)
status() { curl -fsS http://127.0.0.1:8000/market/status | python3 -c 'import json,sys;print(json.load(sys.stdin)["integrity"]["status"])'; }
echo "before: $(status)"
start=$(date +%s.%N)
docker network disconnect "$NET" "$CID"
trap 'docker network connect "$NET" "$CID" 2>/dev/null || true' EXIT
until [ "$(status)" = "CRITICAL" ]; do sleep 0.5; done
echo "CRITICAL detected after $(python3 -c "print(round($(date +%s.%N)-$start,1))") s"
sleep 20
docker network connect "$NET" "$CID"
trap - EXIT
echo "reconnected; waiting for recovery…"
for _ in $(seq 1 60); do [ "$(status)" != "CRITICAL" ] && break; sleep 1; done
echo "after: $(status)"
