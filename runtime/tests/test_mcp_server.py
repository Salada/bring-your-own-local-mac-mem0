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
    def test_pinned_oss_rejects_invalid_expiration_before_mutation(self):
        from mem0 import Memory

        uninitialized = Memory.__new__(Memory)
        with self.assertRaisesRegex(ValueError, "expiration_date must be a valid date"):
            uninitialized.add("temporary", user_id="u", expiration_date="not-a-date")
        with self.assertRaisesRegex(ValueError, "expiration_date must be a valid date"):
            uninitialized.update("one", expiration_date="2026-02-30")

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

    def test_search_exposes_reference_date_and_temporal_explanation(self):
        class MemoryStub:
            def search(self, **_kwargs):
                return {"results": []}

        class TemporalReasonerStub:
            def search(self, **kwargs):
                self.kwargs = kwargs
                return {
                    "results": [
                        {
                            "id": "m1",
                            "score": 0.8,
                            "temporal_explanation": {"temporal_match": True},
                        }
                    ]
                }

        reasoner = TemporalReasonerStub()
        mcp = create_mcp_server(MemoryStub(), temporal_reasoner=reasoner)
        tools = asyncio.run(mcp.list_tools())
        search = next(tool for tool in tools if tool.name == "search_memories")

        self.assertIn("reference_date", search.inputSchema["properties"])
        self.assertIn("explain", search.inputSchema["properties"])
        _, result = asyncio.run(
            mcp.call_tool(
                "search_memories",
                {
                    "query": "What happened yesterday?",
                    "reference_date": "2026-09-11T09:00:00+09:00",
                    "explain": True,
                },
            )
        )

        payload = json.loads(result["result"])
        self.assertTrue(payload["results"][0]["temporal_explanation"]["temporal_match"])
        self.assertEqual(reasoner.kwargs["reference_date"], "2026-09-11T09:00:00+09:00")
        self.assertTrue(reasoner.kwargs["explain"])

    def test_add_timestamp_sets_import_time_and_enrichment_anchor(self):
        class MemoryStub:
            def add(self, *_args, **kwargs):
                self.kwargs = kwargs
                return {"results": [{"id": "m1", "memory": "Met yesterday", "event": "ADD"}]}

        class CategorizerStub:
            def catalog(self, categories):
                self.categories = categories
                return [{"work": "Work facts"}]

        class WorkerStub:
            def submit(self, result, categories, **kwargs):
                self.call = (result, categories, kwargs)

        memory = MemoryStub()
        categorizer = CategorizerStub()
        worker = WorkerStub()
        mcp = create_mcp_server(memory, categorizer=categorizer, category_worker=worker)
        tools = asyncio.run(mcp.list_tools())
        add = next(tool for tool in tools if tool.name == "add_memory")
        self.assertIn("timestamp", add.inputSchema["properties"])

        _, result = asyncio.run(
            mcp.call_tool(
                "add_memory",
                {"text": "Met yesterday", "timestamp": "2026-09-11T09:00:00+09:00"},
            )
        )

        self.assertIn("results", json.loads(result["result"]))
        self.assertEqual(memory.kwargs["metadata"]["created_at"], "2026-09-11T09:00:00+09:00")
        self.assertIn("observed at 2026-09-11T09:00:00+09:00", memory.kwargs["prompt"])
        self.assertEqual(worker.call[2]["observation_time"], "2026-09-11T09:00:00+09:00")
        self.assertTrue(worker.call[2]["classify_categories"])

    def test_ordinary_add_still_schedules_temporal_enrichment(self):
        class MemoryStub:
            def add(self, *_args, **_kwargs):
                return {"results": [{"id": "m1", "memory": "Meeting next week", "event": "ADD"}]}

        class CategorizerStub:
            def catalog(self, _categories):
                return [{"work": "Work facts"}]

        class WorkerStub:
            def submit(self, _result, _categories, **kwargs):
                self.kwargs = kwargs

        worker = WorkerStub()
        mcp = create_mcp_server(MemoryStub(), categorizer=CategorizerStub(), category_worker=worker)

        asyncio.run(mcp.call_tool("add_memory", {"text": "Meeting next week"}))

        self.assertRegex(worker.kwargs["observation_time"], r"\+00:00$")
        self.assertTrue(worker.kwargs["classify_categories"])

    def test_expiration_add_update_clear_and_search_pass_through(self):
        class MemoryStub:
            def get(self, _memory_id):
                return {
                    "id": "one",
                    "hash": "hash-one",
                    "updated_at": "2026-09-13T00:00:00+00:00",
                    "user_id": DEFAULT_USER_ID,
                }

            def add(self, *_args, **kwargs):
                self.add_kwargs = kwargs
                return {"results": []}

            def update(self, _memory_id, **kwargs):
                self.update_kwargs = kwargs
                return {"message": "ok"}

            def search(self, **kwargs):
                self.search_kwargs = kwargs
                return {"results": []}

        class CategorizerStub:
            def catalog(self, _categories):
                return []

        class WorkerStub:
            def submit(self, *_args, **_kwargs):
                pass

        memory = MemoryStub()
        mcp = create_mcp_server(memory, categorizer=CategorizerStub(), category_worker=WorkerStub())
        preconditions = {
            "memory_id": "one",
            "expected_hash": "hash-one",
            "expected_revision": "2026-09-13T00:00:00+00:00",
        }
        asyncio.run(mcp.call_tool("add_memory", {"text": "temporary", "expiration_date": "2026-09-14"}))
        self.assertEqual(memory.add_kwargs["expiration_date"], "2026-09-14")

        asyncio.run(mcp.call_tool("update_memory", {**preconditions, "expiration_date": "2026-09-15"}))
        self.assertEqual(memory.update_kwargs["expiration_date"], "2026-09-15")

        asyncio.run(mcp.call_tool("update_memory", {**preconditions, "clear_expiration_date": True}))
        self.assertIsNone(memory.update_kwargs["expiration_date"])

        memory.update_kwargs = None
        _, rejected = asyncio.run(
            mcp.call_tool("update_memory", {**preconditions, "expected_hash": "stale", "expiration_date": "2026-09-16"})
        )
        self.assertEqual(json.loads(rejected["result"]), {"error": "memory changed after review"})
        self.assertIsNone(memory.update_kwargs)

        _, empty = asyncio.run(mcp.call_tool("update_memory", {**preconditions, "metadata": {}}))
        self.assertIn("required", json.loads(empty["result"])["error"])
        self.assertIsNone(memory.update_kwargs)

        asyncio.run(mcp.call_tool("search_memories", {"query": "temporary", "show_expired": True}))
        self.assertTrue(memory.search_kwargs["show_expired"])

    def test_mcp_list_aliases_hide_expired_unless_requested(self):
        points = [
            SimpleNamespace(id=1, payload={"data": "old", "expiration_date": "2000-01-01"}),
            SimpleNamespace(id=2, payload={"data": "current"}),
        ]
        memory = SimpleNamespace(
            vector_store=SimpleNamespace(
                collection_name="mem0",
                _create_filter=lambda filters: filters,
                client=SimpleNamespace(scroll=lambda **_kwargs: (points, None)),
            )
        )
        mcp = create_mcp_server(memory)

        for name in ("get_memories", "get_all_memories", "get_all"):
            with self.subTest(tool=name):
                _, hidden = asyncio.run(mcp.call_tool(name, {}))
                _, shown = asyncio.run(mcp.call_tool(name, {"show_expired": True}))
                self.assertEqual([item["id"] for item in json.loads(hidden["result"])["results"]], ["2"])
                self.assertEqual([item["id"] for item in json.loads(shown["result"])["results"]], ["1", "2"])

    def test_mcp_invalid_dates_are_rejected_by_pinned_oss(self):
        from mem0 import Memory

        uninitialized = Memory.__new__(Memory)

        class Validator:
            def add(self, *args, **kwargs):
                return uninitialized.add(*args, **kwargs)

            def get(self, _memory_id):
                return {
                    "id": "one",
                    "hash": "hash-one",
                    "updated_at": "2026-09-13T00:00:00+00:00",
                    "user_id": DEFAULT_USER_ID,
                }

            def update(self, memory_id, **kwargs):
                return uninitialized.update(memory_id, **kwargs)

        mcp = create_mcp_server(Validator())
        _, added = asyncio.run(mcp.call_tool("add_memory", {"text": "bad", "expiration_date": "not-a-date"}))
        _, updated = asyncio.run(
            mcp.call_tool(
                "update_memory",
                {
                    "memory_id": "one",
                    "expected_hash": "hash-one",
                    "expected_revision": "2026-09-13T00:00:00+00:00",
                    "expiration_date": "2026-02-30",
                },
            )
        )

        self.assertIn("expiration_date must be a valid date", json.loads(added["result"])["error"])
        self.assertIn("expiration_date must be a valid date", json.loads(updated["result"])["error"])

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
        self.assertEqual(client.offsets, [2, 3])

    def test_numeric_page_is_a_compatibility_walk(self):
        memory, client = self.make_memory()
        result = list_memory_page(memory, filters={"user_id": "u"}, page_size=1, page=3)

        self.assertEqual([item["id"] for item in result["results"]], ["3"])
        self.assertIsNone(result["next_cursor"])
        self.assertFalse(result["has_more"])
        self.assertEqual(client.offsets, [None, 2, 2, 3, 3])

    def test_rejects_ambiguous_cursor_and_page(self):
        memory, _ = self.make_memory()
        with self.assertRaisesRegex(ValueError, "cannot be combined"):
            list_memory_page(memory, filters=None, page_size=1, cursor="2", page=2)

    def test_page_after_last_page_is_empty(self):
        memory, client = self.make_memory()
        result = list_memory_page(memory, filters=None, page_size=1, page=4)

        self.assertEqual(result["results"], [])
        self.assertEqual(client.offsets, [None, 2, 2, 3, 3])

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
            "expiration_date": "2999-01-01",
            "metadata": {"categories": ["work"]},
        }

        result = to_openmemory_item(item)

        self.assertEqual(result["content"], "one")
        self.assertEqual(result["state"], "active")
        self.assertEqual(result["categories"], ["work"])
        self.assertEqual(result["app_name"], "codex")
        self.assertEqual(result["metadata_"], {"categories": ["work"], "expiration_date": "2999-01-01"})

    def test_count_uses_same_qdrant_filter(self):
        memory, client = self.make_memory()
        client.count_calls = []

        def count(**kwargs):
            client.count_calls.append(kwargs)
            return SimpleNamespace(count=23)

        client.count = count

        result = count_memories(memory, {"user_id": "u"}, show_expired=True)

        self.assertEqual(result, 23)
        self.assertEqual(client.count_calls[0]["count_filter"], ("filter", {"user_id": "u"}))
        self.assertTrue(client.count_calls[0]["exact"])

    def test_expired_points_do_not_leave_holes_in_cursor_pages(self):
        expired = "2000-01-01"
        pages = {
            None: ([SimpleNamespace(id="1", payload={"data": "expired", "expiration_date": expired})], 2),
            2: ([SimpleNamespace(id="2", payload={"data": "visible", "expiration_date": "2999-01-01"})], 3),
            3: ([SimpleNamespace(id="3", payload={"data": "also visible"})], None),
        }
        offsets = []

        def scroll(**kwargs):
            offsets.append(kwargs["offset"])
            return pages[kwargs["offset"]]

        store = SimpleNamespace(
            client=SimpleNamespace(scroll=scroll), collection_name="mem0", _create_filter=lambda value: value
        )
        memory = SimpleNamespace(vector_store=store)
        first = list_memory_page(memory, filters={"user_id": "u"}, page_size=1)
        second = list_memory_page(memory, filters={"user_id": "u"}, page_size=1, cursor=first["next_cursor"])

        self.assertEqual([item["id"] for item in first["results"]], ["2"])
        self.assertEqual([item["id"] for item in second["results"]], ["3"])
        self.assertEqual(offsets, [None, 2, 3, 3])
        self.assertEqual(count_memories(memory, {"user_id": "u"}), 2)
        self.assertEqual(
            [item["id"] for item in list_memory_page(memory, filters=None, page_size=1, show_expired=True)["results"]],
            ["1"],
        )
        self.assertEqual(
            [item["id"] for item in list_memory_page(memory, filters=None, page_size=1, page=2)["results"]],
            ["3"],
        )

    def test_expiration_uses_inclusive_utc_date_and_fails_open(self):
        from datetime import datetime, timezone

        points = [
            SimpleNamespace(id="past", payload={"expiration_date": "2026-09-12"}),
            SimpleNamespace(id="today", payload={"expiration_date": "2026-09-13"}),
            SimpleNamespace(id="future", payload={"expiration_date": "2026-09-14"}),
            SimpleNamespace(id="invalid", payload={"expiration_date": "bad-date"}),
        ]
        store = SimpleNamespace(
            client=SimpleNamespace(scroll=lambda **_kwargs: (points, None)),
            collection_name="mem0",
            _create_filter=lambda value: value,
        )
        memory = SimpleNamespace(vector_store=store)
        with mock.patch("memory_listing.datetime") as clock:
            clock.now.return_value = datetime(2026, 9, 13, tzinfo=timezone.utc)
            self.assertEqual(
                [item["id"] for item in list_memory_page(memory, filters=None, page_size=4)["results"]],
                ["today", "future", "invalid"],
            )

    def test_filtered_pages_respect_size_and_only_advertise_visible_successors(self):
        points = [
            SimpleNamespace(id=index, payload={"expiration_date": "2000-01-01"} if expired else {"data": str(index)})
            for index, expired in enumerate([True, False, True, False, False, False, True])
        ]

        def scroll(**kwargs):
            start = kwargs["offset"] or 0
            end = min(start + kwargs["limit"], len(points))
            return points[start:end], end if end < len(points) else None

        memory = SimpleNamespace(
            vector_store=SimpleNamespace(
                collection_name="mem0", client=SimpleNamespace(scroll=scroll), _create_filter=lambda value: value
            )
        )
        first = list_memory_page(memory, filters=None, page_size=3)
        second = list_memory_page(memory, filters=None, page_size=3, cursor=first["next_cursor"])

        self.assertEqual([item["id"] for item in first["results"]], ["1", "3", "4"])
        self.assertEqual(first["next_cursor"], "5")
        self.assertTrue(first["has_more"])
        self.assertEqual([item["id"] for item in second["results"]], ["5"])
        self.assertIsNone(second["next_cursor"])
        self.assertFalse(second["has_more"])
        self.assertEqual(count_memories(memory, None), 4)

        # A full page followed only by expired raw points must not promise a page.
        tail = SimpleNamespace(
            vector_store=SimpleNamespace(
                collection_name="mem0",
                client=SimpleNamespace(
                    scroll=lambda **kwargs: (points[3:4], 6) if kwargs["offset"] is None else (points[6:], None)
                ),
                _create_filter=lambda value: value,
            )
        )
        last = list_memory_page(tail, filters=None, page_size=1)
        self.assertEqual([item["id"] for item in last["results"]], ["3"])
        self.assertFalse(last["has_more"])

    def test_cursor_lookahead_works_with_real_qdrant_scroll_offsets(self):
        from qdrant_client import QdrantClient, models

        client = QdrantClient(":memory:")
        client.create_collection("mem0", vectors_config=models.VectorParams(size=1, distance=models.Distance.COSINE))
        client.upsert(
            "mem0",
            points=[
                models.PointStruct(id=1, vector=[0.1], payload={"data": "one"}),
                models.PointStruct(id=2, vector=[0.1], payload={"data": "expired", "expiration_date": "2000-01-01"}),
                models.PointStruct(id=3, vector=[0.1], payload={"data": "three"}),
            ],
        )
        memory = SimpleNamespace(vector_store=SimpleNamespace(client=client, collection_name="mem0"))
        first = list_memory_page(memory, filters=None, page_size=1)
        second = list_memory_page(memory, filters=None, page_size=1, cursor=first["next_cursor"])

        self.assertEqual([item["id"] for item in first["results"]], ["1"])
        self.assertEqual(first["next_cursor"], "3")
        self.assertEqual([item["id"] for item in second["results"]], ["3"])
        self.assertFalse(second["has_more"])

    def test_expiration_is_visible_on_direct_id_lookup(self):
        record = {"id": "one", "expiration_date": "2000-01-01"}

        class MemoryStub:
            def get(self, memory_id):
                self.memory_id = memory_id
                return record

        memory = MemoryStub()
        mcp = create_mcp_server(memory)
        _, result = asyncio.run(mcp.call_tool("get_memory", {"memory_id": "one"}))

        self.assertEqual(json.loads(result["result"]), record)
        self.assertEqual(memory.memory_id, "one")


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
