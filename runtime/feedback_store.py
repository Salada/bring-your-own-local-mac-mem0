"""Local feedback labels stored in Mem0's already-backed-up history database."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


class FeedbackStore:
    def __init__(self, history_db: str | Path):
        self.path = Path(history_db)

    def _connect(self) -> sqlite3.Connection:
        if not self.path.is_absolute() or self.path.is_symlink():
            raise ValueError("feedback requires an absolute, non-symlink history database path")
        connection = sqlite3.connect(self.path.as_uri() + "?mode=rw", uri=True, timeout=10)
        connection.row_factory = sqlite3.Row
        return connection

    @staticmethod
    def _exists(connection: sqlite3.Connection) -> bool:
        return (
            connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'local_feedback'"
            ).fetchone()
            is not None
        )

    def get(self, memory_id: str, user_id: str) -> dict | None:
        with closing(self._connect()) as connection:
            if not self._exists(connection):
                return None
            row = connection.execute(
                "SELECT id, memory_id, user_id, feedback, feedback_reason, created_at, updated_at "
                "FROM local_feedback WHERE memory_id = ? AND user_id = ?",
                (memory_id, user_id),
            ).fetchone()
            return dict(row) if row else None

    def set(self, memory_id: str, user_id: str, feedback: str | None, reason: str | None) -> dict:
        now = datetime.now(timezone.utc).isoformat()
        with closing(self._connect()) as connection, connection:
            if feedback is None:
                if not self._exists(connection):
                    return {"id": None, "feedback": None, "feedback_reason": None}
                previous = connection.execute(
                    "SELECT id FROM local_feedback WHERE memory_id = ? AND user_id = ?", (memory_id, user_id)
                ).fetchone()
                if previous:
                    connection.execute(
                        "DELETE FROM local_feedback WHERE memory_id = ? AND user_id = ?", (memory_id, user_id)
                    )
                return {"id": previous["id"] if previous else None, "feedback": None, "feedback_reason": None}

            connection.execute(
                "CREATE TABLE IF NOT EXISTS local_feedback ("
                "id TEXT PRIMARY KEY, memory_id TEXT NOT NULL UNIQUE, user_id TEXT NOT NULL, "
                "feedback TEXT NOT NULL CHECK(feedback IN ('POSITIVE','NEGATIVE','VERY_NEGATIVE')), "
                "feedback_reason TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
            )
            connection.execute(
                "INSERT INTO local_feedback "
                "(id, memory_id, user_id, feedback, feedback_reason, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(memory_id) DO UPDATE SET feedback=excluded.feedback, "
                "feedback_reason=excluded.feedback_reason, updated_at=excluded.updated_at "
                "WHERE local_feedback.user_id=excluded.user_id",
                (str(uuid4()), memory_id, user_id, feedback, reason, now, now),
            )
            row = connection.execute(
                "SELECT id, memory_id, user_id, feedback, feedback_reason, created_at, updated_at "
                "FROM local_feedback WHERE memory_id = ? AND user_id = ?",
                (memory_id, user_id),
            ).fetchone()
            if row is None:
                raise ValueError("feedback scope conflict")
            return dict(row)
