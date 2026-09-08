#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$script_dir"

service="gui/$(id -u)/${MEM0_LAUNCHD_LABEL:-local.mem0-server}"
if launchctl print "$service" >/dev/null 2>&1; then
    launchctl bootout "$service"
fi

docker compose down
