#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$script_dir"

docker compose up -d

for _ in {1..60}; do
    if curl -fsS http://127.0.0.1:6333/healthz >/dev/null 2>&1; then
        break
    fi
    sleep 1
done
curl -fsS http://127.0.0.1:6333/healthz >/dev/null
curl -fsS http://127.0.0.1:8898/v1/models >/dev/null

exec uv run python server.py
