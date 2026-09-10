"""Fail-open Codex lifecycle adapter for the local Mem0 plugin."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN_ROOT / "core"))

from local_memory import log_error, process_hook


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "action",
        choices=(
            "session-start",
            "user-prompt",
            "post-tool",
            "sidekick-start",
            "sidekick-stop",
            "stop",
            "flush",
        ),
    )
    parser.add_argument("--reason", default="manual")
    parser.add_argument("--plugin-data-dir", required=True)
    args = parser.parse_args()
    data_dir = Path(args.plugin_data_dir).expanduser()
    try:
        event = json.load(sys.stdin)
        if not isinstance(event, dict):
            return 0
        output = process_hook(args.action, event, data_dir, reason=args.reason)
        if output:
            print(json.dumps(output, ensure_ascii=False))
    except Exception as exc:  # noqa: BLE001 - a memory failure must never block Codex
        log_error(data_dir, args.action, exc)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
