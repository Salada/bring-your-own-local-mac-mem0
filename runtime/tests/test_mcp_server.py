import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest import mock

from mcp_server import (
    DEFAULT_USER_ID,
    MCP_INSTRUCTIONS,
    create_mcp_server,
    normalize_filters,
)
from memory_guards import validate_exact_keeper
from memory_listing import count_memories, list_memory_page, to_openmemory_item


class NormalizeFiltersTest(unittest.TestCase):
    def test_promotes_scope_and_preserves_metadata_filters(self):
        filters = {
            "AND": [
                {"user_id": "local-user"},
                {"app_id": "sample-app"},
                {"metadata": {"type": "decision"}},
                {"metadata.source": "codex"},
            ]
        }

        self.assertEqual(
            normalize_filters(filters),
            {
                "user_id": "local-user",
                "AND": [
                    {"app_id": "sample-app"},
                    {"type": "decision"},
                    {"source": "codex"},
                ],
            },
        )

    def test_preserves_flattened_metadata_filter(self):
        self.assertEqual(
            normalize_filters({"type": {"eq": "task_learning"}}),
            {"type": {"eq": "task_learning"}, "user_id": DEFAULT_USER_ID},
        )

    def test_http_transport_keeps_dns_rebinding_protection(self):
        mcp = create_mcp_server(object())

        self.assertTrue(mcp.settings.transport_security.enable_dns_rebinding_protection)
        self.assertEqual(mcp.settings.streamable_http_path, "/")
        self.assertEqual(mcp._mcp_server.instructions, MCP_INSTRUCTIONS)
        self.assertIn("At task start, search_memories", MCP_INSTRUCTIONS[:512])
        self.assertIn("Never store secrets", MCP_INSTRUCTIONS[:512])

    def test_search_defaults_match_local_retrieval_benchmark(self):
        class MemoryStub:
            def search(self, **kwargs):
                self.kwargs = kwargs
                return {
                    "results": [
                        {"memory": "high", "score": 0.6},
                        {"memory": "low", "score": 0.49},
                    ]
                }

        memory = MemoryStub()
        mcp = create_mcp_server(memory)
        tools = asyncio.run(mcp.list_tools())
        search = next(tool for tool in tools if tool.name == "search_memories")
        properties = search.inputSchema["properties"]

        self.assertEqual(properties["top_k"]["default"], 3)
        self.assertEqual(properties["threshold"]["default"], 0.5)
        self.assertFalse(properties["rerank"]["default"])

        _, result = asyncio.run(mcp.call_tool("search_memories", {"query": "test"}))
        self.assertEqual(json.loads(result["result"]), {"results": [{"memory": "high", "score": 0.6}]})
        self.assertEqual(memory.kwargs["top_k"], 3)
        self.assertEqual(memory.kwargs["threshold"], 0.5)
        self.assertFalse(memory.kwargs["rerank"])

    def test_only_guarded_single_delete_is_exposed_over_mcp(self):
        mcp = create_mcp_server(object())
        names = {tool.name for tool in asyncio.run(mcp.list_tools())}

        self.assertIn("delete_memory", names)
        self.assertNotIn("delete_all_memories", names)

    def test_delete_requires_preconditions_and_backup(self):
        events = []
        item = {
            "id": "memory-1",
            "memory": "reviewed fact",
            "hash": "hash-1",
            "updated_at": "2026-09-09T00:00:00+00:00",
            "user_id": DEFAULT_USER_ID,
        }

        class MemoryStub:
            def get(self, memory_id):
                events.append(f"get:{memory_id}")
                return dict(item)

            def delete(self, memory_id):
                events.append(f"delete:{memory_id}")

        mcp = create_mcp_server(MemoryStub())
        arguments = {
            "memory_id": "memory-1",
            "expected_hash": "hash-1",
            "expected_revision": "2026-09-09T00:00:00+00:00",
        }

        with mock.patch("mcp_server._capture_backup_generation", side_effect=lambda: events.append("backup") or "/b"):
            _, deleted = asyncio.run(mcp.call_tool("delete_memory", arguments))

        self.assertEqual(json.loads(deleted["result"]), {"ok": True, "deleted": "memory-1", "backup": "/b"})
        self.assertEqual(events, ["get:memory-1", "backup", "get:memory-1", "delete:memory-1"])

    def test_delete_refuses_changed_memory_before_backup(self):
        class MemoryStub:
            def get(self, _memory_id):
                return {
                    "id": "memory-1",
                    "hash": "new-hash",
                    "updated_at": "2026-09-09T00:00:00+00:00",
                    "user_id": DEFAULT_USER_ID,
                }

        mcp = create_mcp_server(MemoryStub())
        arguments = {
            "memory_id": "memory-1",
            "expected_hash": "reviewed-hash",
            "expected_revision": "2026-09-09T00:00:00+00:00",
        }

        with mock.patch("mcp_server._capture_backup_generation") as capture:
            _, refused = asyncio.run(mcp.call_tool("delete_memory", arguments))

        self.assertEqual(json.loads(refused["result"]), {"error": "memory changed after review"})
        capture.assert_not_called()

    def test_delete_rechecks_preconditions_after_backup(self):
        deleted = []
        items = iter(
            [
                {
                    "id": "memory-1",
                    "hash": "reviewed-hash",
                    "updated_at": "2026-09-09T00:00:00+00:00",
                    "user_id": DEFAULT_USER_ID,
                },
                {
                    "id": "memory-1",
                    "hash": "changed-during-backup",
                    "updated_at": "2026-09-09T00:00:01+00:00",
                    "user_id": DEFAULT_USER_ID,
                },
            ]
        )

        class MemoryStub:
            def get(self, _memory_id):
                return next(items)

            def delete(self, _memory_id):
                deleted.append(_memory_id)

        mcp = create_mcp_server(MemoryStub())
        arguments = {
            "memory_id": "memory-1",
            "expected_hash": "reviewed-hash",
            "expected_revision": "2026-09-09T00:00:00+00:00",
        }

        with mock.patch("mcp_server._capture_backup_generation", return_value="/backup"):
            _, refused = asyncio.run(mcp.call_tool("delete_memory", arguments))

        self.assertEqual(json.loads(refused["result"]), {"error": "memory changed after review"})
        self.assertEqual(deleted, [])

    def test_delete_stops_when_backup_fails(self):
        deleted = []

        class MemoryStub:
            def get(self, _memory_id):
                return {
                    "id": "memory-1",
                    "hash": "reviewed-hash",
                    "updated_at": "2026-09-09T00:00:00+00:00",
                    "user_id": DEFAULT_USER_ID,
                }

            def delete(self, memory_id):
                deleted.append(memory_id)

        mcp = create_mcp_server(MemoryStub())
        arguments = {
            "memory_id": "memory-1",
            "expected_hash": "reviewed-hash",
            "expected_revision": "2026-09-09T00:00:00+00:00",
        }

        with mock.patch("mcp_server._capture_backup_generation", side_effect=RuntimeError("backup failed")):
            _, refused = asyncio.run(mcp.call_tool("delete_memory", arguments))

        self.assertEqual(json.loads(refused["result"]), {"error": "backup failed"})
        self.assertEqual(deleted, [])


class MemoryPaginationTest(unittest.TestCase):
    def make_memory(self):
        pages = {
            None: ([SimpleNamespace(id="1", payload={"data": "one", "user_id": "u"})], 2),
            2: ([SimpleNamespace(id="2", payload={"data": "two", "user_id": "u"})], 3),
            3: ([SimpleNamespace(id="3", payload={"data": "three", "user_id": "u"})], None),
        }

        class Client:
            def __init__(self):
                self.offsets = []

            def scroll(self, **kwargs):
                self.offsets.append(kwargs["offset"])
                return pages[kwargs["offset"]]

        client = Client()
        store = SimpleNamespace(
            client=client,
            collection_name="mem0",
            _create_filter=lambda filters: ("filter", filters),
        )
        return SimpleNamespace(vector_store=store), client

    def test_cursor_continues_without_rewalking_prior_pages(self):
        memory, client = self.make_memory()
        result = list_memory_page(memory, filters={"user_id": "u"}, page_size=1, cursor="2")

        self.assertEqual([item["id"] for item in result["results"]], ["2"])
        self.assertEqual(result["next_cursor"], "3")
        self.assertTrue(result["has_more"])
        self.assertEqual(client.offsets, [2])

    def test_numeric_page_is_a_compatibility_walk(self):
        memory, client = self.make_memory()
        result = list_memory_page(memory, filters={"user_id": "u"}, page_size=1, page=3)

        self.assertEqual([item["id"] for item in result["results"]], ["3"])
        self.assertIsNone(result["next_cursor"])
        self.assertFalse(result["has_more"])
        self.assertEqual(client.offsets, [None, 2, 3])

    def test_rejects_ambiguous_cursor_and_page(self):
        memory, _ = self.make_memory()
        with self.assertRaisesRegex(ValueError, "cannot be combined"):
            list_memory_page(memory, filters=None, page_size=1, cursor="2", page=2)

    def test_page_after_last_page_is_empty(self):
        memory, client = self.make_memory()
        result = list_memory_page(memory, filters=None, page_size=1, page=4)

        self.assertEqual(result["results"], [])
        self.assertEqual(client.offsets, [None, 2, 3])

    def test_nested_metadata_is_flattened(self):
        memory, _ = self.make_memory()
        memory.vector_store.client.scroll = lambda **_kwargs: (
            [SimpleNamespace(id="1", payload={"data": "one", "metadata": {"type": "decision"}})],
            None,
        )

        result = list_memory_page(memory, filters=None, page_size=1)

        self.assertEqual(result["results"][0]["metadata"], {"type": "decision"})

    def test_openmemory_contract_maps_content_and_defaults(self):
        item = {
            "id": "1",
            "memory": "one",
            "created_at": "2026-09-10T00:00:00Z",
            "agent_id": "codex",
            "metadata": {"categories": ["work"]},
        }

        result = to_openmemory_item(item)

        self.assertEqual(result["content"], "one")
        self.assertEqual(result["state"], "active")
        self.assertEqual(result["categories"], ["work"])
        self.assertEqual(result["app_name"], "codex")
        self.assertEqual(result["metadata_"], {"categories": ["work"]})

    def test_count_uses_same_qdrant_filter(self):
        memory, client = self.make_memory()
        client.count_calls = []

        def count(**kwargs):
            client.count_calls.append(kwargs)
            return SimpleNamespace(count=23)

        client.count = count

        result = count_memories(memory, {"user_id": "u"})

        self.assertEqual(result, 23)
        self.assertEqual(client.count_calls[0]["count_filter"], ("filter", {"user_id": "u"}))
        self.assertTrue(client.count_calls[0]["exact"])


class MemoryGuardTest(unittest.TestCase):
    def item(self, memory_id, text):
        return {
            "id": memory_id,
            "memory": text,
            "hash": f"hash-{memory_id}",
            "created_at": "2026-09-01T00:00:00+00:00",
            "user_id": "u",
            "metadata": {"type": "decision", "app_id": "project"},
        }

    def test_keeper_must_still_be_the_same_exact_duplicate(self):
        target = self.item("old", "Use SQLite!")
        keeper = self.item("new", "use sqlite")
        validate_exact_keeper(
            target,
            keeper,
            expected_hash="hash-new",
            expected_revision="2026-09-01T00:00:00+00:00",
            expected_user_id="u",
            expected_app_id="project",
        )

        keeper["memory"] = "Use PostgreSQL"
        with self.assertRaisesRegex(ValueError, "no longer an exact duplicate"):
            validate_exact_keeper(
                target,
                keeper,
                expected_hash="hash-new",
                expected_revision="2026-09-01T00:00:00+00:00",
                expected_user_id="u",
                expected_app_id="project",
            )


if __name__ == "__main__":
    unittest.main()
