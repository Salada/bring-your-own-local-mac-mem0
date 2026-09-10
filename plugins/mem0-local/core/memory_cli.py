"""Small control CLI used by the pause, resume, and status skills."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from local_memory import legacy_hooks_present, set_paused, status


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("pause", "resume", "status", "preflight"))
    parser.add_argument("--plugin-data-dir")
    parser.add_argument("--codex-hooks-file")
    args = parser.parse_args()
    if args.action == "preflight":
        path = (
            Path(args.codex_hooks_file).expanduser() if args.codex_hooks_file else None
        )
        if legacy_hooks_present(path):
            print(
                "Legacy Mem0 Codex hooks are still installed; run "
                "mem0-ctl codex-hooks uninstall before installing the plugin."
            )
            return 2
        print("Preflight passed: no legacy Mem0 Codex hooks detected.")
        return 0
    if not args.plugin_data_dir:
        parser.error("--plugin-data-dir is required for pause, resume, and status")
    data_dir = Path(args.plugin_data_dir).expanduser()
    if args.action == "pause":
        set_paused(data_dir, True)
        print("Local Mem0 automatic recall and capture are paused.")
    elif args.action == "resume":
        set_paused(data_dir, False)
        print("Local Mem0 automatic recall and capture are active.")
    else:
        try:
            print(json.dumps(status(data_dir), indent=2, sort_keys=True))
        except ValueError as exc:
            print(f"Local Mem0 configuration error: {exc}")
            return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
