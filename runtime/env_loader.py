"""Load simple KEY=VALUE runtime settings without executing shell code."""

from __future__ import annotations

import os
import re
from pathlib import Path

KEY_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def load_env_file(path: Path) -> None:
    if not path.is_file():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not KEY_RE.fullmatch(key):
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(key, value)


def load_runtime_env(runtime_dir: Path | None = None) -> None:
    root = runtime_dir or Path(__file__).resolve().parent
    load_env_file(root / ".env")
    if root != Path.home() / ".config" / "mem0":
        load_env_file(Path.home() / ".config" / "mem0" / ".env")
