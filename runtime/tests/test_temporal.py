import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock

from temporal import (
    TEMPORAL_BOOST,
    TemporalInterval,
    TemporalReasoner,
    aware_datetime,
    has_temporal_cue,
    rerank_temporal_results,
    temporal_add_prompt,
    validate_interval,
)


class TemporalValidationTest(unittest.TestCase):
    def test_requires_timezone_aware_timestamp(self):
        with self.assertRaisesRegex(ValueError, "timezone"):
            aware_datetime("2026-09-11T09:00:00", "timestamp")
        with self.assertRaisesRegex(ValueError, "timezone"):
            aware_datetime(datetime(2026, 9, 11, 9), "timestamp")

    def test_validates_interval_order_and_intent(self):
        with self.assertRaisesRegex(ValueError, "before"):
            validate_interval("2026-09-12T00:00:00+09:00", "2026-09-11T00:00:00+09:00")
        with self.assertRaisesRegex(ValueError, "intent"):
            validate_interval(
                "2026-09-11T00:00:00+09:00",
                "2026-09-12T00:00:00+09:00",
                "ongoing",
            )

    def test_detects_english_and_korean_cues_without_matching_plain_queries(self):
        self.assertTrue(has_temporal_cue("What happened last week?"))
        self.assertTrue(has_temporal_cue("어제 무슨 회의가 있었지?"))
        self.assertTrue(has_temporal_cue("작년에 뭘 했지?"))
        self.assertTrue(has_temporal_cue("내년 계획은 뭐였지?"))
        self.assertFalse(has_temporal_cue("Which database did we choose?"))
        self.assertFalse(has_temporal_cue("What is my last name?"))
        self.assertFalse(has_temporal_cue("Before committing, run lint."))
        self.assertFalse(has_temporal_cue("Since we changed the API, what breaks?"))

    def test_temporal_add_prompt_preserves_existing_instructions(self):
        prompt = temporal_add_prompt("2026-09-11T09:00:00+09:00", "Keep Korean text in Korean.")

        self.assertTrue(prompt.startswith("Keep Korean text in Korean."))
        self.assertIn("observed at 2026-09-11T09:00:00+09:00", prompt)


class TemporalRerankTest(unittest.TestCase):
    interval = TemporalInterval(
        "2026-09-01T00:00:00+09:00",
        "2026-09-07T23:59:59+09:00",
        "occurrence",
    )

    def test_matching_event_overtakes_higher_semantic_candidate(self):
        items = [
            {"id": "other", "score": 0.72},
            {
                "id": "conference",
                "score": 0.65,
                "event_start": "2026-09-03T09:00:00+09:00",
                "event_end": "2026-09-03T18:00:00+09:00",
                "temporal_kind": "occurrence",
            },
        ]

        result = rerank_temporal_results(items, self.interval, limit=2, threshold=0.5, explain=True)

        self.assertEqual([item["id"] for item in result], ["conference", "other"])
        self.assertEqual(result[0]["score"], 0.65 + TEMPORAL_BOOST)
        self.assertEqual(
            result[0]["temporal_explanation"],
            {
                "base_score": 0.65,
                "temporal_match": True,
                "boost": TEMPORAL_BOOST,
                "final_score": 0.65 + TEMPORAL_BOOST,
            },
        )

    def test_date_match_cannot_rescue_semantically_irrelevant_memory(self):
        items = [
            {
                "id": "irrelevant",
                "score": 0.2,
                "event_start": "2026-09-03T09:00:00+09:00",
                "event_end": "2026-09-03T10:00:00+09:00",
                "temporal_kind": "occurrence",
            }
        ]

        self.assertEqual(rerank_temporal_results(items, self.interval, limit=3, threshold=0.5), [])

    def test_missing_metadata_and_wrong_intent_keep_base_score(self):
        items = [
            {"id": "undated", "score": 0.7},
            {
                "id": "future-plan",
                "score": 0.68,
                "metadata": {
                    "event_start": "2026-09-03T09:00:00+09:00",
                    "event_end": "2026-09-03T10:00:00+09:00",
                    "temporal_kind": "plan",
                },
            },
        ]

        result = rerank_temporal_results(items, self.interval, limit=3, threshold=0.5)

        self.assertEqual([item["id"] for item in result], ["undated", "future-plan"])
        self.assertEqual([item["score"] for item in result], [0.7, 0.68])

    def test_opt_in_neural_rank_preserves_vector_score_and_temporal_boost(self):
        items = [
            {"id": "vector-first", "score": 0.9, "rerank_score": 0.2},
            {
                "id": "neural-first",
                "score": 0.6,
                "rerank_score": 0.8,
                "event_start": "2026-09-03T09:00:00+09:00",
                "event_end": "2026-09-03T10:00:00+09:00",
                "temporal_kind": "occurrence",
            },
        ]

        result = rerank_temporal_results(items, self.interval, limit=2, threshold=0.5, use_rerank_score=True)

        self.assertEqual([item["id"] for item in result], ["neural-first", "vector-first"])
        self.assertEqual(result[0]["score"], 0.6 + TEMPORAL_BOOST)
        self.assertEqual(result[0]["rerank_score"], 0.8)

    def test_opt_in_normalizes_raw_model_logit_for_temporal_combination(self):
        items = [
            {"id": "lower-logit", "score": 0.6, "rerank_score": 1.0},
            {"id": "higher-logit", "score": 0.7, "rerank_score": 1.01},
        ]

        result = rerank_temporal_results(
            items, self.interval, limit=2, threshold=0.5, use_rerank_score=True, rerank_scores_normalized=False
        )

        self.assertEqual([item["id"] for item in result], ["higher-logit", "lower-logit"])
        self.assertEqual(result[0]["rerank_score"], 1.01)

    def test_official_huggingface_zero_score_fallback_uses_vector_temporal_order(self):
        from mem0.configs.base import MemoryConfig
        from mem0.configs.rerankers.huggingface import HuggingFaceRerankerConfig
        from mem0.reranker.huggingface_reranker import HuggingFaceReranker

        configured = MemoryConfig.model_validate(
            {"reranker": {"provider": "huggingface", "config": {"model": "BAAI/bge-reranker-v2-m3"}}}
        )
        self.assertEqual(configured.reranker.provider, "huggingface")
        reranker = HuggingFaceReranker.__new__(HuggingFaceReranker)
        reranker.config = HuggingFaceRerankerConfig()
        reranker.tokenizer = Mock(side_effect=RuntimeError("synthetic scoring failure"))
        reranker.device = "cpu"
        items = [
            {"id": "vector-first", "memory": "vector-first", "score": 0.9},
            {
                "id": "dated-second",
                "memory": "dated-second",
                "score": 0.6,
                "event_start": "2026-09-03T09:00:00+09:00",
                "event_end": "2026-09-03T10:00:00+09:00",
                "temporal_kind": "occurrence",
            },
        ]

        fallback = reranker.rerank("When did we meet?", items, top_k=2)
        self.assertEqual([item["rerank_score"] for item in fallback], [0.0, 0.0])
        result = rerank_temporal_results(fallback, self.interval, limit=2, threshold=0.5, use_rerank_score=True)

        self.assertEqual([item["id"] for item in result], ["vector-first", "dated-second"])


class TemporalReasonerTest(unittest.TestCase):
    def test_show_expired_is_forwarded_to_mem0(self):
        class MemoryStub:
            def search(self, **kwargs):
                self.kwargs = kwargs
                return {"results": []}

        memory = MemoryStub()
        TemporalReasoner(memory).search(query="Which database?", filters={"user_id": "u"}, top_k=2, show_expired=True)

        self.assertTrue(memory.kwargs["show_expired"])

    def test_non_temporal_query_without_options_preserves_original_call_shape(self):
        class MemoryStub:
            def search(self, **kwargs):
                self.kwargs = kwargs
                return {"results": []}

        memory = MemoryStub()
        TemporalReasoner(memory).search(query="Which database?", filters={"user_id": "u"}, top_k=4)

        self.assertEqual(
            memory.kwargs,
            {"query": "Which database?", "filters": {"user_id": "u"}, "top_k": 4},
        )

    def test_non_temporal_query_keeps_exact_baseline_call(self):
        class MemoryStub:
            def search(self, **kwargs):
                self.kwargs = kwargs
                return {"results": []}

        memory = MemoryStub()
        result = TemporalReasoner(memory).search(
            query="Which database did we choose?",
            filters={"user_id": "u"},
            top_k=4,
            reference_date="2026-09-11T09:00:00+09:00",
            threshold=0.4,
            rerank=True,
        )

        self.assertEqual(result, {"results": []})
        self.assertEqual(
            memory.kwargs,
            {
                "query": "Which database did we choose?",
                "filters": {"user_id": "u"},
                "top_k": 4,
                "threshold": 0.4,
                "rerank": True,
            },
        )

    def test_opt_in_reranker_overfetches_then_returns_requested_count(self):
        class MemoryStub:
            reranker = object()

            def search(self, **kwargs):
                self.kwargs = kwargs
                return {"results": [{"id": str(index)} for index in range(kwargs["top_k"])]}

        memory = MemoryStub()
        result = TemporalReasoner(memory).search(
            query="Which database did we choose?", filters={"user_id": "u"}, top_k=3, rerank=True
        )

        self.assertEqual(memory.kwargs["top_k"], 6)
        self.assertTrue(memory.kwargs["rerank"])
        self.assertEqual([item["id"] for item in result["results"]], ["0", "1", "2"])

    def test_reference_date_requires_timezone_even_for_non_temporal_query(self):
        memory = SimpleNamespace(search=lambda **_kwargs: {"results": []})

        with self.assertRaisesRegex(ValueError, "timezone"):
            TemporalReasoner(memory).search(
                query="Which database did we choose?",
                filters={"user_id": "u"},
                top_k=3,
                reference_date="2026-09-11T09:00:00",
            )

    def test_temporal_query_parses_once_and_overfetches(self):
        llm = SimpleNamespace(
            calls=[],
            generate_response=lambda **kwargs: llm.calls.append(kwargs)
            or {
                "start": "2026-09-01T00:00:00+09:00",
                "end": "2026-09-07T23:59:59+09:00",
                "intent": "occurrence",
            },
        )

        class MemoryStub:
            def __init__(self):
                self.llm = llm

            def search(self, **kwargs):
                self.kwargs = kwargs
                return {"results": []}

        memory = MemoryStub()
        TemporalReasoner(memory).search(
            query="What happened last week?",
            filters={"user_id": "u"},
            top_k=3,
            reference_date="2026-09-11T09:00:00+09:00",
        )

        self.assertEqual(len(llm.calls), 1)
        self.assertEqual(memory.kwargs["top_k"], 9)
        self.assertEqual(memory.kwargs["threshold"], 0.5)

    def test_temporal_query_uses_current_time_without_reference_date(self):
        class LLMStub:
            def __init__(self):
                self.calls = []

            def generate_response(self, **kwargs):
                self.calls.append(kwargs)
                return {
                    "start": "2026-09-10T00:00:00+00:00",
                    "end": "2026-09-10T23:59:59+00:00",
                    "intent": "occurrence",
                }

        class MemoryStub:
            def __init__(self):
                self.llm = LLMStub()

            def search(self, **_kwargs):
                return {"results": []}

        memory = MemoryStub()
        TemporalReasoner(memory).search(
            query="What happened yesterday?",
            filters={"user_id": "u"},
            top_k=3,
        )

        self.assertEqual(len(memory.llm.calls), 1)
        prompt = memory.llm.calls[0]["messages"][1]["content"]
        self.assertIn('"reference_date":', prompt)
        self.assertRegex(prompt, r'"reference_date": ".*[+-]00:00"')

    def test_parser_failure_fails_open_to_single_baseline_search(self):
        class LLMStub:
            def generate_response(self, **_kwargs):
                raise RuntimeError("provider unavailable")

        class MemoryStub:
            llm = LLMStub()

            def __init__(self):
                self.calls = []

            def search(self, **kwargs):
                self.calls.append(kwargs)
                return {"results": [{"id": "baseline", "score": 0.6}]}

        memory = MemoryStub()
        result = TemporalReasoner(memory).search(
            query="What happened yesterday?",
            filters={"user_id": "u"},
            top_k=3,
            reference_date="2026-09-11T09:00:00+09:00",
        )

        self.assertEqual(result["results"][0]["id"], "baseline")
        self.assertEqual(len(memory.calls), 1)
        self.assertEqual(memory.calls[0]["top_k"], 3)


if __name__ == "__main__":
    unittest.main()
