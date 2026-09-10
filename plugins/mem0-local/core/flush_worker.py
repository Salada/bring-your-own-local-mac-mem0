"""Detached evidence flusher for the local Mem0 plugin."""

from __future__ import annotations

import argparse
import time
import uuid
from pathlib import Path

from local_memory import USER_ID, connect, http_json


def flush(data_dir: Path, key: str, reason: str) -> bool:
    batch_id = uuid.uuid4().hex
    with connect(data_dir) as database:
        database.execute("BEGIN IMMEDIATE")
        rows = database.execute(
            "SELECT id, role, content FROM events WHERE session_key=? AND status='pending' ORDER BY id",
            (key,),
        ).fetchall()
        if not rows:
            database.rollback()
            return False
        ids = [int(row["id"]) for row in rows]
        placeholders = ",".join("?" for _ in ids)
        database.execute(
            f"UPDATE events SET status='inflight', batch_id=?, claimed_at=? WHERE id IN ({placeholders})",
            (batch_id, time.time(), *ids),
        )
        session = database.execute(
            "SELECT app_id FROM sessions WHERE session_key=?", (key,)
        ).fetchone()
        database.commit()
    if session is None:
        with connect(data_dir) as database:
            database.execute(
                "UPDATE events SET status='pending', batch_id=NULL, claimed_at=NULL WHERE batch_id=?",
                (batch_id,),
            )
            database.commit()
        return False
    try:
        http_json(
            "/v1/memories",
            {
                "messages": [
                    {"role": row["role"], "content": row["content"]} for row in rows
                ],
                "user_id": USER_ID,
                "metadata": {
                    "app_id": session["app_id"],
                    "source": "codex_plugin",
                    "capture": reason,
                },
                "infer": True,
            },
            30.0,
        )
    except Exception:
        with connect(data_dir) as database:
            database.execute(
                "UPDATE events SET status='pending', batch_id=NULL, claimed_at=NULL WHERE batch_id=?",
                (batch_id,),
            )
            database.commit()
        raise
    with connect(data_dir) as database:
        database.execute("DELETE FROM events WHERE batch_id=?", (batch_id,))
        if reason == "session-end":
            database.execute("DELETE FROM sessions WHERE session_key=?", (key,))
        database.commit()
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plugin-data-dir", required=True)
    parser.add_argument("--session-key", required=True)
    parser.add_argument("--reason", required=True)
    args = parser.parse_args()
    try:
        flush(Path(args.plugin_data_dir), args.session_key, args.reason)
    except Exception as exc:  # noqa: BLE001 - detached worker must preserve evidence and exit cleanly
        from local_memory import log_error

        log_error(Path(args.plugin_data_dir), f"flush:{args.reason}", exc)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
