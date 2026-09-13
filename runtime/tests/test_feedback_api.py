import importlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from fastapi.testclient import TestClient

from feedback_store import FeedbackStore

MEMORY_ID = "11111111-1111-4111-8111-111111111111"
OTHER_ID = "22222222-2222-4222-8222-222222222222"
MISSING_ID = "33333333-3333-4333-8333-333333333333"


class FeedbackApiTest(unittest.TestCase):
    def test_scoped_feedback_round_trip_and_history_backup(self):
        class MemoryStub:
            def __init__(self, history_db):
                self.config = SimpleNamespace(history_db_path=str(history_db))
                self.records = {
                    MEMORY_ID: {"id": MEMORY_ID, "user_id": "local-user", "memory": "private text"},
                    OTHER_ID: {"id": OTHER_ID, "user_id": "another-user", "memory": "other text"},
                }

            def get(self, memory_id):
                return self.records.get(memory_id)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            history_db = root / "history.db"
            sqlite3.connect(history_db).close()
            config = root / "config.json"
            config.write_text(json.dumps({"version": "v1.1", "history_db_path": str(history_db)}))
            memory = MemoryStub(history_db)
            with (
                mock.patch.dict("os.environ", {"MEM0_CONFIG_PATH": str(config)}),
                mock.patch("env_loader.load_runtime_env"),
                mock.patch("mem0.Memory.from_config", return_value=memory),
                mock.patch("backup_lock.restore_marker", return_value=root / "restore.marker"),
            ):
                server = importlib.import_module("server")
            # Another test may import the server with a different configured default user.
            memory.records[MEMORY_ID]["user_id"] = server.DEFAULT_USER_ID

            with (
                mock.patch.object(server, "memory", memory),
                mock.patch.object(server, "feedback_store", FeedbackStore(history_db)),
                mock.patch("backup_lock.lock_path", return_value=root / "write.lock"),
            ):
                client = TestClient(server.app)
                self.assertEqual(client.post("/v1/feedback", json={"memory_id": MEMORY_ID}).status_code, 400)
                self.assertEqual(
                    client.post("/v1/feedback", json={"memory_id": MEMORY_ID, "feedback": "INVALID"}).status_code,
                    422,
                )
                self.assertEqual(
                    client.post("/v1/feedback", json={"memory_id": "malformed", "feedback": "POSITIVE"}).status_code,
                    400,
                )
                self.assertEqual(
                    client.post("/v1/feedback", json={"memory_id": MISSING_ID, "feedback": "POSITIVE"}).status_code,
                    404,
                )
                self.assertEqual(
                    client.post("/v1/feedback", json={"memory_id": OTHER_ID, "feedback": "POSITIVE"}).status_code,
                    404,
                )
                self.assertEqual(client.get(f"/v1/feedback/{MEMORY_ID}").status_code, 404)

                first = client.post(
                    "/v1/feedback/",
                    json={"memory_id": MEMORY_ID, "feedback": "POSITIVE", "feedback_reason": "useful"},
                )
                self.assertEqual(first.status_code, 200)
                feedback_id = first.json()["id"]
                self.assertEqual(client.get(f"/v1/feedback/{MEMORY_ID}").json()["feedback"], "POSITIVE")
                updated = client.post(
                    "/v1/feedback", json={"memory_id": MEMORY_ID, "feedback": "NEGATIVE", "feedback_reason": "stale"}
                )
                self.assertEqual(updated.status_code, 200)
                self.assertEqual(updated.json()["id"], feedback_id)
                self.assertEqual(updated.json()["feedback_reason"], "stale")
                self.assertEqual(
                    client.get(f"/v1/feedback/{MEMORY_ID}", params={"user_id": "another-user"}).status_code, 404
                )
                self.assertEqual(
                    client.post(
                        "/v1/feedback", json={"memory_id": MEMORY_ID, "feedback": None, "feedback_reason": "bad"}
                    ).status_code,
                    400,
                )

                # Existing backup copies the entire history.db, including this local table.
                backup = root / "backup.db"
                with sqlite3.connect(history_db) as source, sqlite3.connect(backup) as target:
                    source.backup(target)
                with sqlite3.connect(backup) as saved:
                    self.assertEqual(saved.execute("SELECT feedback FROM local_feedback").fetchone()[0], "NEGATIVE")

                cleared = client.post("/v1/feedback", json={"memory_id": MEMORY_ID, "feedback": None})
                self.assertEqual(cleared.status_code, 200)
                self.assertEqual(cleared.json()["id"], feedback_id)
                self.assertEqual(client.get(f"/v1/feedback/{MEMORY_ID}").status_code, 404)


if __name__ == "__main__":
    unittest.main()
