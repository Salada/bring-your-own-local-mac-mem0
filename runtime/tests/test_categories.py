import json
import unittest
from contextlib import nullcontext
from threading import Event
from types import SimpleNamespace
from unittest import mock

from categories import (
    DEFAULT_CATEGORIES,
    CategoryRecommendationError,
    CategoryWorker,
    MemoryCategorizer,
    category_catalog,
    category_diff,
    pop_project_categories,
    validate_categories,
)


class LLMStub:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def generate_response(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


class VectorStoreStub:
    def __init__(self):
        self.updates = []

    def update(self, **kwargs):
        self.updates.append(kwargs)


def make_memory(response):
    return SimpleNamespace(llm=LLMStub(response), vector_store=VectorStoreStub())


class CategoryConfigTest(unittest.TestCase):
    def test_default_catalog_matches_platform_category_names(self):
        names = [next(iter(entry)) for entry in DEFAULT_CATEGORIES]

        self.assertEqual(len(names), 15)
        self.assertIn("professional_details", names)
        self.assertIn("user_preferences", names)
        self.assertIn("misc", names)

    def test_project_categories_are_removed_before_mem0_config_validation(self):
        config = {"version": "v1.1", "custom_categories": [{"work": "Work facts"}]}

        categories = pop_project_categories(config)

        self.assertEqual(categories, [{"work": "Work facts"}])
        self.assertEqual(config, {"version": "v1.1"})

    def test_rejects_invalid_or_duplicate_custom_categories(self):
        with self.assertRaisesRegex(ValueError, "one-key"):
            validate_categories([{"work": "Work", "home": "Home"}])
        with self.assertRaisesRegex(ValueError, "duplicate"):
            validate_categories([{"work": "Work"}, {"work": "Again"}])

    def test_openmemory_catalog_uses_names_as_filter_ids(self):
        self.assertEqual(
            category_catalog([{"work": "Work facts"}]),
            [{"id": "work", "name": "work", "description": "Work facts"}],
        )

    def test_category_diff_describes_complete_replacement(self):
        self.assertEqual(
            category_diff(
                [{"work": "Old work"}, {"home": "Home facts"}],
                [{"work": "New work"}, {"travel": "Travel facts"}],
            ),
            {
                "added": [{"travel": "Travel facts"}],
                "removed": [{"home": "Home facts"}],
                "changed": [{"name": "work", "from": "Old work", "to": "New work"}],
            },
        )


class CategoryInferenceTest(unittest.TestCase):
    def test_catalog_recommendation_uses_only_supplied_context_and_never_applies(self):
        memory = make_memory('{"custom_categories":[{"technology":"Technical decisions"}]}')
        categorizer = MemoryCategorizer(memory, [{"personal": "Personal facts"}])

        result = categorizer.recommend_catalog("A software engineering assistant", max_categories=3)

        self.assertEqual(result, [{"technology": "Technical decisions"}])
        self.assertEqual(memory.vector_store.updates, [])
        prompt = memory.llm.calls[0]["messages"][1]["content"]
        self.assertEqual(json.loads(prompt), {"use_case": "A software engineering assistant"})

    def test_catalog_recommendation_rejects_oversized_result(self):
        memory = make_memory('{"custom_categories":[{"work":"Work"},{"home":"Home"}]}')

        with self.assertRaisesRegex(CategoryRecommendationError, "exceeds max_categories"):
            MemoryCategorizer(memory).recommend_catalog("Personal assistant", max_categories=1)

    def test_catalog_recommendation_requires_explicit_catalog_output(self):
        with self.assertRaisesRegex(CategoryRecommendationError, "must include custom_categories"):
            MemoryCategorizer(make_memory("{}")).recommend_catalog("Personal assistant")

    def test_per_call_categories_replace_project_catalog_and_apply_payload_only(self):
        memory = make_memory('{"memories":[{"id":"m1","categories":["work"]}]}')
        categorizer = MemoryCategorizer(memory, [{"personal": "Personal facts"}])
        result = {"results": [{"id": "m1", "memory": "Uses Python", "event": "ADD"}]}

        assignments = categorizer.classify_add_result(result, [{"work": "Technical work"}])
        applied = categorizer.apply(assignments)

        self.assertEqual(applied, 1)
        self.assertEqual(assignments[0].categories, ["work"])
        self.assertEqual(
            memory.vector_store.updates,
            [{"vector_id": "m1", "vector": None, "payload": {"categories": ["work"]}}],
        )
        prompt = memory.llm.calls[0]["messages"][1]["content"]
        self.assertIn('"work"', prompt)
        self.assertNotIn('"personal"', prompt)

    def test_category_and_temporal_enrichment_share_one_llm_call(self):
        memory = make_memory(
            '{"memories":[{"id":"m1","categories":["work"],'
            '"event_start":"2026-09-10T14:00:00+09:00",'
            '"event_end":"2026-09-10T15:00:00+09:00","temporal_kind":"occurrence"}]}'
        )
        categorizer = MemoryCategorizer(memory, [{"work": "Work facts"}])

        assignments = categorizer.classify_add_result(
            {"results": [{"id": "m1", "memory": "Met the team yesterday", "event": "ADD"}]},
            observation_time="2026-09-11T09:00:00+09:00",
        )
        applied = categorizer.apply(assignments)

        self.assertEqual(len(memory.llm.calls), 1)
        self.assertEqual(applied, 1)
        self.assertEqual(
            memory.vector_store.updates[0]["payload"],
            {
                "categories": ["work"],
                "event_start": "2026-09-10T14:00:00+09:00",
                "event_end": "2026-09-10T15:00:00+09:00",
                "temporal_kind": "occurrence",
            },
        )
        prompt = json.loads(memory.llm.calls[0]["messages"][1]["content"])
        self.assertEqual(prompt["observation_time"], "2026-09-11T09:00:00+09:00")

    def test_timestamp_can_enrich_time_without_overwriting_explicit_categories(self):
        memory = make_memory(
            '{"memories":[{"id":"m1","event_start":"2026-09-12T10:00:00+09:00",'
            '"event_end":"2026-09-12T11:00:00+09:00","temporal_kind":"plan"}]}'
        )
        categorizer = MemoryCategorizer(memory, [{"work": "Work facts"}])

        assignments = categorizer.classify_add_result(
            {"results": [{"id": "m1", "memory": "Meet tomorrow", "event": "ADD"}]},
            observation_time="2026-09-11T09:00:00+09:00",
            classify_categories=False,
        )
        categorizer.apply(assignments)

        self.assertEqual(
            memory.vector_store.updates[0]["payload"],
            {
                "event_start": "2026-09-12T10:00:00+09:00",
                "event_end": "2026-09-12T11:00:00+09:00",
                "temporal_kind": "plan",
            },
        )
        self.assertNotIn("categories", json.loads(memory.llm.calls[0]["messages"][1]["content"]))

    def test_invalid_temporal_fields_are_ignored_but_category_is_kept(self):
        memory = make_memory(
            '{"memories":[{"id":"m1","categories":["work"],'
            '"event_start":"2026-09-10T14:00:00","event_end":"bad","temporal_kind":"occurrence"}]}'
        )
        categorizer = MemoryCategorizer(memory, [{"work": "Work facts"}])

        assignments = categorizer.classify_add_result(
            {"results": [{"id": "m1", "memory": "Met yesterday", "event": "ADD"}]},
            observation_time="2026-09-11T09:00:00+09:00",
        )
        categorizer.apply(assignments)

        self.assertEqual(memory.vector_store.updates[0]["payload"], {"categories": ["work"]})

    def test_unknown_category_and_hallucinated_id_are_ignored(self):
        memory = make_memory(
            '{"memories":[{"id":"m1","categories":["not_allowed"]},{"id":"made-up","categories":["work"]}]}'
        )
        categorizer = MemoryCategorizer(memory, [{"work": "Work facts"}])

        assignments = categorizer.classify([{"id": "m1", "memory": "A fact"}])

        self.assertEqual(assignments, [])

    def test_delete_events_are_not_classified(self):
        memory = make_memory('{"memories":[]}')
        categorizer = MemoryCategorizer(memory)

        assignments = categorizer.classify_add_result(
            {"results": [{"id": "m1", "memory": "removed", "event": "DELETE"}]}
        )

        self.assertEqual(assignments, [])
        self.assertEqual(memory.llm.calls, [])

    def test_inference_failure_does_not_fail_successful_memory_write(self):
        memory = make_memory(RuntimeError("provider unavailable"))
        categorizer = MemoryCategorizer(memory)
        result = {"results": [{"id": "m1", "memory": "saved", "event": "ADD"}]}

        assignments = categorizer.safely_classify_add_result(result)

        self.assertEqual(assignments, [])
        self.assertEqual(memory.vector_store.updates, [])

    def test_background_worker_returns_before_classification_finishes(self):
        release = Event()

        class BlockingLLM(LLMStub):
            def generate_response(self, **kwargs):
                release.wait(timeout=2)
                return super().generate_response(**kwargs)

        memory = SimpleNamespace(
            llm=BlockingLLM('{"memories":[{"id":"m1","categories":["work"]}]}'),
            vector_store=VectorStoreStub(),
        )
        worker = CategoryWorker(MemoryCategorizer(memory, [{"work": "Work facts"}]), nullcontext)

        future = worker.submit({"results": [{"id": "m1", "memory": "Uses Python", "event": "ADD"}]})

        self.assertFalse(future.done())
        self.assertEqual(memory.vector_store.updates, [])
        release.set()
        self.assertEqual(future.result(timeout=2), 1)
        worker.shutdown()
        self.assertEqual(memory.vector_store.updates[0]["payload"], {"categories": ["work"]})

    def test_background_payload_failure_is_logged_and_contained(self):
        memory = make_memory('{"memories":[{"id":"m1","categories":["work"]}]}')
        memory.vector_store.update = mock.Mock(side_effect=RuntimeError("qdrant unavailable"))
        worker = CategoryWorker(MemoryCategorizer(memory, [{"work": "Work facts"}]), nullcontext)

        with self.assertLogs("mem0-server.categories", level="ERROR") as logs:
            result = worker.submit({"results": [{"id": "m1", "memory": "Uses Python", "event": "ADD"}]}).result(
                timeout=2
            )

        worker.shutdown()
        self.assertEqual(result, 0)
        self.assertIn("memory remains available for backfill", logs.output[0])


if __name__ == "__main__":
    unittest.main()
