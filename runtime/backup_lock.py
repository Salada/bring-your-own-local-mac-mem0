"""Advisory lock shared by Mem0 mutations and consistent backups."""

from __future__ import annotations

import fcntl
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

LOCK_PATH = Path(
    os.environ.get(
        "MEM0_WRITE_LOCK_PATH",
        Path.home() / ".local" / "state" / "mem0-backup" / "write.lock",
    )
)


@contextmanager
def memory_lock(*, exclusive: bool) -> Iterator[None]:
    """Hold the process-wide Mem0 data lock in shared or exclusive mode."""
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_CREAT | os.O_RDWR
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(LOCK_PATH, flags, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def mutation_lock() -> Iterator[None]:
    """Serialize writers and exclude consistent backup/maintenance snapshots."""
    return memory_lock(exclusive=True)


def maintenance_lock() -> Iterator[None]:
    """Exclude backups and all ordinary writers during guarded maintenance."""
    return memory_lock(exclusive=True)


def backup_lock() -> Iterator[None]:
    return memory_lock(exclusive=True)
