import importlib
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from fastapi.testclient import TestClient


class ExpirationApiTest(unittest.TestCase):
    def test_rest_add_update_search_list_and_direct_get(self):
        class MemoryStub:
            def __init__(self):
                self.records = {}
                self.vector_store = SimpleNamespace(
                    collection_name="mem0",
                    _create_filter=lambda filters: filters,
                    client=SimpleNamespace(scroll=self.scroll, count=self.count),
                )

            def add(self, **kwargs):
                self.records["one"] = {
                    "data": kwargs["messages"],
                    "user_id": kwargs["user_id"],
                    "expiration_date": kwargs["expiration_date"],
                }
                return {"results": [{"id": "one", "event": "ADD"}]}

            def update(self, memory_id, **kwargs):
                self.records[memory_id]["expiration_date"] = kwargs["expiration_date"]
                return {"message": "ok"}

            def get(self, memory_id):
                return {"id": memory_id, "memory": self.records[memory_id]["data"], **self.records[memory_id]}

            def search(self, **kwargs):
                self.search_kwargs = kwargs
                return {"results": [{"id": "one"}] if kwargs.get("show_expired") or not self.is_expired() else []}

            def is_expired(self):
                return self.records["one"].get("expiration_date") == "2000-01-01"

            def scroll(self, **_kwargs):
                return [SimpleNamespace(id=key, payload=value) for key, value in self.records.items()], None

            def count(self, **_kwargs):
                return SimpleNamespace(count=len(self.records))

        memory = MemoryStub()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            config = root / "config.json"
            config.write_text(json.dumps({"version": "v1.1"}), encoding="utf-8")
            with (
                mock.patch.dict("os.environ", {"MEM0_CONFIG_PATH": str(config)}),
                mock.patch("pathlib.Path.home", return_value=root),
                mock.patch("env_loader.load_runtime_env"),
                mock.patch("mem0.Memory.from_config", return_value=memory),
                mock.patch("backup_lock.restore_marker", return_value=root / "restore.marker"),
            ):
                server = importlib.import_module("server")

            client = TestClient(server.app)
            with mock.patch.object(server.category_worker, "submit"):
                response = client.post("/v1/memories", json={"messages": "trial", "expiration_date": "2000-01-01"})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(memory.records["one"]["expiration_date"], "2000-01-01")
            self.assertEqual(client.post("/v1/memories/search", json={"query": "trial"}).json()["results"], [])
            self.assertEqual(client.get("/v1/memories", params={"user_id": "local-user"}).json()["results"], [])
            self.assertEqual(client.post("/api/v1/memories/filter", json={}).json()["total"], 0)
            self.assertEqual(client.get("/v1/memories/one").json()["expiration_date"], "2000-01-01")
            self.assertEqual(
                [item["id"] for item in client.get("/v1/memories", params={"show_expired": True}).json()["results"]],
                ["one"],
            )
            self.assertEqual(
                [item["id"] for item in client.post("/v1/memories/search", json={"query": "trial", "show_expired": True}).json()["results"]],
                ["one"],
            )
            self.assertTrue(memory.search_kwargs["show_expired"])
            self.assertEqual(client.put("/v1/memories/one", json={"expiration_date": None}).status_code, 200)
            self.assertIsNone(memory.records["one"]["expiration_date"])
            self.assertEqual([item["id"] for item in client.get("/v1/memories").json()["results"]], ["one"])
            self.assertEqual(client.put("/v1/memories/one", json={}).status_code, 400)
