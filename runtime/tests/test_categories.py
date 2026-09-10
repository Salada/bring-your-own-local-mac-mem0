import unittest
from types import SimpleNamespace

from categories import (
    DEFAULT_CATEGORIES,
    MemoryCategorizer,
    category_catalog,
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


class CategoryInferenceTest(unittest.TestCase):
    def test_per_call_categories_replace_project_catalog_and_apply_payload_only(self):
        memory = make_memory('{"memories":[{"id":"m1","categories":["work"]}]}')
        categorizer = MemoryCategorizer(memory, [{"personal": "Personal facts"}])
        result = {"results": [{"id": "m1", "memory": "Uses Python", "event": "ADD"}]}

        assignments = categorizer.classify_add_result(result, [{"work": "Technical work"}])
        applied = categorizer.apply(assignments)
        categorizer.annotate_result(result, assignments)

        self.assertEqual(applied, 1)
        self.assertEqual(result["results"][0]["categories"], ["work"])
        self.assertEqual(
            memory.vector_store.updates,
            [{"vector_id": "m1", "vector": None, "payload": {"categories": ["work"]}}],
        )
        prompt = memory.llm.calls[0]["messages"][1]["content"]
        self.assertIn('"work"', prompt)
        self.assertNotIn('"personal"', prompt)

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


if __name__ == "__main__":
    unittest.main()
