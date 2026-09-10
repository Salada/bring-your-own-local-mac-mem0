"""Small control CLI used by the pause, resume, and status skills."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from local_memory import set_paused, status


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("pause", "resume", "status"))
    parser.add_argument("--plugin-data-dir", required=True)
    args = parser.parse_args()
    data_dir = Path(args.plugin_data_dir).expanduser()
    if args.action == "pause":
        set_paused(data_dir, True)
        print("Local Mem0 automatic recall and capture are paused.")
    elif args.action == "resume":
        set_paused(data_dir, False)
        print("Local Mem0 automatic recall and capture are active.")
    else:
        print(json.dumps(status(data_dir), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
