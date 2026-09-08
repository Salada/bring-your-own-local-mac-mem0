import unittest

from codex_hook import capture_turn, search_context


class CodexHookTest(unittest.TestCase):
    def test_search_injects_only_high_scoring_safe_results(self):
        def request(path, payload, timeout):
            self.assertEqual(path, "/v1/memories/search")
            self.assertEqual(payload["user_id"], "local-user")
            return {
                "results": [
                    {"memory": "keep this decision", "score": 0.7},
                    {"memory": "drop low score", "score": 0.49},
                    {"memory": "token" + "=" + "test-value", "score": 0.9},
                ]
            }

        output = search_context({"prompt": "continue the deployment"}, request)
        context = output["hookSpecificOutput"]["additionalContext"]
        self.assertIn("keep this decision", context)
        self.assertNotIn("drop low score", context)
        self.assertNotIn("test-value", context)

    def test_capture_sends_substantive_safe_response_to_local_memory(self):
        calls = []

        def request(path, payload, timeout):
            calls.append((path, payload, timeout))
            return {"results": []}

        capture_turn(
            {
                "cwd": "/workspace/sample-project",
                "last_assistant_message": "A durable implementation result. " * 8,
                "stop_hook_active": False,
            },
            request,
        )

        self.assertEqual(len(calls), 1)
        path, payload, timeout = calls[0]
        self.assertEqual(path, "/v1/memories")
        self.assertEqual(payload["metadata"]["app_id"], "sample-project")
        self.assertEqual(payload["metadata"]["source"], "codex_hook")
        self.assertTrue(payload["infer"])
        self.assertEqual(timeout, 25)

    def test_capture_skips_sensitive_response(self):
        calls = []
        capture_turn(
            {"last_assistant_message": ("result " * 30) + "api_key" + "=" + "test-value"},
            lambda *args: calls.append(args),
        )
        self.assertEqual(calls, [])


if __name__ == "__main__":
    unittest.main()
