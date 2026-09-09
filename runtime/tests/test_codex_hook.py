import json
import shlex
import sys
import tempfile
import unittest
from pathlib import Path

from codex_hook import (
    USER_ID,
    capture_turn,
    configure_hooks,
    hooks_installed,
    search_context,
)


class CodexHookTest(unittest.TestCase):
    def test_search_injects_only_high_scoring_safe_results(self):
        def request(path, payload, timeout):
            self.assertEqual(path, "/v1/memories/search")
            self.assertEqual(payload["user_id"], USER_ID)
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

    def test_hook_install_is_idempotent_and_uninstall_preserves_other_hooks(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "hooks.json"
            path.write_text(
                json.dumps(
                    {
                        "hooks": {
                            "Stop": [{"hooks": [{"type": "command", "command": "other-tool capture", "timeout": 5}]}]
                        }
                    }
                ),
                encoding="utf-8",
            )
            script = Path(root) / "mem0 runtime" / "codex_hook.py"

            self.assertTrue(configure_hooks(path, script, install=True))
            self.assertFalse(configure_hooks(path, script, install=True))
            self.assertTrue(hooks_installed(path))
            installed = json.loads(path.read_text(encoding="utf-8"))
            command = installed["hooks"]["UserPromptSubmit"][0]["hooks"][0]["command"]
            self.assertEqual(command, f"{shlex.quote(sys.executable)} {shlex.quote(str(script))} search")
            self.assertTrue(configure_hooks(path, script, install=False))

            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["hooks"]["Stop"][0]["hooks"][0]["command"], "other-tool capture")
            self.assertNotIn("UserPromptSubmit", data["hooks"])

    def test_hook_install_refuses_mixed_inline_configuration(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "hooks.json"
            path.with_name("config.toml").write_text(
                "[[hooks.UserPromptSubmit]]\nhooks = []\n",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "inline hooks already exist"):
                configure_hooks(path, Path(root) / "codex_hook.py", install=True)

    def test_hook_install_allows_codex_trust_state(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "hooks.json"
            path.with_name("config.toml").write_text(
                '[hooks.state."/tmp/hooks.json:Stop:0:0"]\ntrusted_hash = "sha256:test"\n',
                encoding="utf-8",
            )

            self.assertTrue(configure_hooks(path, Path(root) / "codex_hook.py", install=True))


if __name__ == "__main__":
    unittest.main()
