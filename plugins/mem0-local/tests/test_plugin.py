from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest import mock

PLUGIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN / "core"))

import flush_worker
import local_memory
import mcp_server
import memory_cli


class EnvironmentMixin:
    def setUp(self):
        self.environment = mock.patch.dict(os.environ, {}, clear=False)
        self.environment.start()
        for name in (
            "MEM0_CODEX_MEMORY_PROFILE",
            "MEM0_CODEX_RECALL_LEVEL",
            "MEM0_CODEX_CAPTURE_LEVEL",
        ):
            os.environ.pop(name, None)

    def tearDown(self):
        self.environment.stop()


class PolicyTests(EnvironmentMixin, unittest.TestCase):
    def test_balanced_is_default(self):
        policy = local_memory.resolve_policy()
        self.assertEqual(
            (policy.recall, policy.capture, policy.result_limit),
            ("balanced", "balanced", 5),
        )

    def test_independent_overrides(self):
        os.environ.update(
            {
                "MEM0_CODEX_MEMORY_PROFILE": "conservative",
                "MEM0_CODEX_RECALL_LEVEL": "aggressive",
            }
        )
        policy = local_memory.resolve_policy()
        self.assertEqual(
            (policy.recall, policy.capture), ("aggressive", "conservative")
        )

    def test_invalid_level_is_rejected(self):
        os.environ["MEM0_CODEX_MEMORY_PROFILE"] = "maximum"
        with self.assertRaisesRegex(ValueError, "invalid profile"):
            local_memory.resolve_policy()


class HookTests(EnvironmentMixin, unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.temp = tempfile.TemporaryDirectory()
        self.data_dir = Path(self.temp.name) / "plugin-data"
        self.event = {"session_id": "s1", "cwd": "/work/demo"}

    def tearDown(self):
        self.temp.cleanup()
        super().tearDown()

    def test_balanced_recalls_only_first_substantive_prompt(self):
        result = {"id": "m1", "memory": "Use the local adapter", "score": 0.8}
        with mock.patch.object(
            local_memory, "search_memories", return_value=[result]
        ) as search:
            first = local_memory.process_hook(
                "user-prompt",
                {**self.event, "prompt": "Please continue the adapter implementation"},
                self.data_dir,
            )
            second = local_memory.process_hook(
                "user-prompt",
                {**self.event, "prompt": "Please run the complete validation suite"},
                self.data_dir,
            )
        self.assertEqual(search.call_count, 1)
        self.assertIn(
            "Use the local adapter", first["hookSpecificOutput"]["additionalContext"]
        )
        self.assertIsNone(second)

    def test_aggressive_recalls_every_prompt_and_bootstraps(self):
        os.environ["MEM0_CODEX_MEMORY_PROFILE"] = "aggressive"
        with mock.patch.object(
            local_memory, "search_memories", return_value=[]
        ) as search:
            local_memory.process_hook("session-start", self.event, self.data_dir)
            local_memory.process_hook(
                "user-prompt",
                {**self.event, "prompt": "First sufficiently long prompt"},
                self.data_dir,
            )
            local_memory.process_hook(
                "user-prompt",
                {**self.event, "prompt": "Second sufficiently long prompt"},
                self.data_dir,
            )
        self.assertEqual(search.call_count, 3)

    def test_conservative_captures_only_explicit_remember_request(self):
        os.environ["MEM0_CODEX_MEMORY_PROFILE"] = "conservative"
        with (
            mock.patch.object(local_memory, "search_memories", return_value=[]),
            mock.patch.object(local_memory, "spawn_flush") as spawn,
        ):
            local_memory.process_hook(
                "user-prompt",
                {**self.event, "prompt": "Explain this implementation in detail"},
                self.data_dir,
            )
            local_memory.process_hook(
                "stop",
                {**self.event, "last_assistant_message": "An ordinary answer"},
                self.data_dir,
            )
            local_memory.process_hook(
                "user-prompt",
                {**self.event, "prompt": "기억해줘: 이 프로젝트는 로컬 우선이다"},
                self.data_dir,
            )
            local_memory.process_hook(
                "stop",
                {
                    **self.event,
                    "last_assistant_message": "이 프로젝트는 로컬 우선이라고 기억할게요.",
                },
                self.data_dir,
            )
        spawn.assert_called_once()
        with local_memory.connect(self.data_dir) as database:
            rows = database.execute(
                "SELECT content, explicit FROM events ORDER BY id"
            ).fetchall()
        self.assertEqual(len(rows), 2)
        self.assertTrue(all(row["explicit"] for row in rows))

    def test_pause_suppresses_new_events(self):
        local_memory.set_paused(self.data_dir, True)
        with mock.patch.object(local_memory, "search_memories") as search:
            output = local_memory.process_hook(
                "user-prompt",
                {**self.event, "prompt": "Remember this sufficiently long prompt"},
                self.data_dir,
            )
        self.assertIsNone(output)
        search.assert_not_called()
        self.assertEqual(local_memory.status(self.data_dir)["pending_events"], 0)

    def test_session_start_recovers_pending_events_from_prior_session(self):
        prior = {"session_id": "prior", "cwd": "/work/other"}
        with local_memory.connect(self.data_dir) as database:
            prior_key = local_memory.session_key(prior)
            local_memory.ensure_session(database, prior_key, "other", "/work/other")
            local_memory.record_event(
                database, prior_key, "prompt", "user", "pending fact"
            )
        with mock.patch.object(local_memory, "spawn_flush") as spawn:
            local_memory.process_hook("session-start", self.event, self.data_dir)
        spawn.assert_called_once_with(self.data_dir, prior_key, "session-recovery")

    def test_parent_context_is_reused_for_subagent(self):
        with local_memory.connect(self.data_dir) as database:
            key = local_memory.session_key(self.event)
            local_memory.ensure_session(database, key, "demo", "/work/demo")
            database.execute(
                "UPDATE sessions SET last_context='- prior decision' WHERE session_key=?",
                (key,),
            )
            database.commit()
        output = local_memory.process_hook("sidekick-start", self.event, self.data_dir)
        self.assertEqual(output["hookSpecificOutput"]["hookEventName"], "SubagentStart")
        self.assertIn(
            "prior decision", output["hookSpecificOutput"]["additionalContext"]
        )

    def test_child_session_id_falls_back_to_latest_project_context(self):
        with local_memory.connect(self.data_dir) as database:
            key = local_memory.session_key(self.event)
            local_memory.ensure_session(database, key, "demo", "/work/demo")
            database.execute(
                "UPDATE sessions SET last_context='- inherited context' WHERE session_key=?",
                (key,),
            )
            database.commit()
        output = local_memory.process_hook(
            "sidekick-start", {**self.event, "session_id": "child"}, self.data_dir
        )
        self.assertIn(
            "inherited context", output["hookSpecificOutput"]["additionalContext"]
        )

    def test_secret_event_is_not_queued(self):
        local_memory.process_hook(
            "post-tool",
            {
                **self.event,
                "tool_name": "shell",
                "tool_input": "API_KEY=super-secret",
                "tool_response": "ok",
            },
            self.data_dir,
        )
        self.assertEqual(local_memory.status(self.data_dir)["pending_events"], 0)

    def test_balanced_flushes_at_ten_events(self):
        with local_memory.connect(self.data_dir) as database:
            key = local_memory.session_key(self.event)
            local_memory.ensure_session(database, key, "demo", "/work/demo")
            for number in range(9):
                local_memory.record_event(
                    database, key, "tool", "assistant", f"result {number}"
                )
        with mock.patch.object(local_memory, "spawn_flush") as spawn:
            local_memory.process_hook(
                "stop",
                {**self.event, "last_assistant_message": "tenth event"},
                self.data_dir,
            )
        spawn.assert_called_once_with(
            self.data_dir, local_memory.session_key(self.event), "stop"
        )


class FlushTests(unittest.TestCase):
    def test_successful_flush_deletes_claimed_events(self):
        with tempfile.TemporaryDirectory() as root:
            data_dir = Path(root)
            event = {"session_id": "s1", "cwd": "/work/demo"}
            key = local_memory.session_key(event)
            with local_memory.connect(data_dir) as database:
                local_memory.ensure_session(database, key, "demo", "/work/demo")
                local_memory.record_event(
                    database, key, "prompt", "user", "durable input"
                )
            with mock.patch.object(
                flush_worker, "http_json", return_value={}
            ) as request:
                self.assertTrue(flush_worker.flush(data_dir, key, "pre-compact"))
            self.assertEqual(request.call_args.args[0], "/v1/memories")
            with local_memory.connect(data_dir) as database:
                self.assertEqual(
                    database.execute("SELECT COUNT(*) FROM events").fetchone()[0], 0
                )

    def test_failed_flush_restores_pending_state(self):
        with tempfile.TemporaryDirectory() as root:
            data_dir = Path(root)
            event = {"session_id": "s1", "cwd": "/work/demo"}
            key = local_memory.session_key(event)
            with local_memory.connect(data_dir) as database:
                local_memory.ensure_session(database, key, "demo", "/work/demo")
                local_memory.record_event(
                    database, key, "prompt", "user", "durable input"
                )
            with (
                mock.patch.object(
                    flush_worker, "http_json", side_effect=OSError("offline")
                ),
                self.assertRaises(OSError),
            ):
                flush_worker.flush(data_dir, key, "stop")
            with local_memory.connect(data_dir) as database:
                self.assertEqual(
                    database.execute("SELECT status FROM events").fetchone()[0],
                    "pending",
                )

    def test_recent_inflight_event_is_not_reclaimed(self):
        with tempfile.TemporaryDirectory() as root:
            data_dir = Path(root)
            with local_memory.connect(data_dir) as database:
                database.execute(
                    "INSERT INTO events(session_key, kind, role, content, status, batch_id, claimed_at, created_at, digest) "
                    "VALUES('s', 'prompt', 'user', 'old content', 'inflight', 'batch', ?, 0, 'digest')",
                    (time.time(),),
                )
                database.commit()
                local_memory.recover_inflight(database)
                self.assertEqual(
                    database.execute("SELECT status FROM events").fetchone()[0],
                    "inflight",
                )

    def test_stale_inflight_event_is_reclaimed(self):
        with tempfile.TemporaryDirectory() as root:
            data_dir = Path(root)
            with local_memory.connect(data_dir) as database:
                database.execute(
                    "INSERT INTO events(session_key, kind, role, content, status, batch_id, claimed_at, created_at, digest) "
                    "VALUES('s', 'prompt', 'user', 'old content', 'inflight', 'batch', ?, 0, 'digest')",
                    (time.time() - 301,),
                )
                database.commit()
                local_memory.recover_inflight(database)
                self.assertEqual(
                    database.execute("SELECT status FROM events").fetchone()[0],
                    "pending",
                )


class CliTests(EnvironmentMixin, unittest.TestCase):
    def test_preflight_detects_legacy_hook_without_printing_command(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "hooks.json"
            path.write_text(
                json.dumps(
                    {
                        "hooks": {
                            "Stop": [
                                {
                                    "hooks": [
                                        {"command": "/private/codex_hook.py capture"}
                                    ]
                                }
                            ]
                        }
                    }
                ),
                encoding="utf-8",
            )
            output = StringIO()
            with (
                mock.patch.object(
                    sys,
                    "argv",
                    ["memory_cli.py", "preflight", "--codex-hooks-file", str(path)],
                ),
                redirect_stdout(output),
            ):
                self.assertEqual(memory_cli.main(), 2)
        self.assertIn("Legacy Mem0 Codex hooks", output.getvalue())
        self.assertNotIn("/private/", output.getvalue())

    def test_status_reports_invalid_profile_without_traceback(self):
        os.environ["MEM0_CODEX_MEMORY_PROFILE"] = "invalid"
        with tempfile.TemporaryDirectory() as root:
            output = StringIO()
            with (
                mock.patch.object(
                    sys,
                    "argv",
                    ["memory_cli.py", "status", "--plugin-data-dir", root],
                ),
                redirect_stdout(output),
            ):
                self.assertEqual(memory_cli.main(), 2)
        self.assertIn("configuration error", output.getvalue())
        self.assertNotIn("Traceback", output.getvalue())


class ContractTests(unittest.TestCase):
    def test_all_documented_hooks_are_declared(self):
        hooks = json.loads((PLUGIN / "hooks" / "hooks.json").read_text())["hooks"]
        self.assertEqual(
            set(hooks),
            {
                "SessionStart",
                "UserPromptSubmit",
                "PostToolUse",
                "SubagentStart",
                "SubagentStop",
                "Stop",
                "PreCompact",
                "SessionEnd",
            },
        )

    def test_mcp_exposes_only_focused_search(self):
        listed = mcp_server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
        self.assertEqual(
            [tool["name"] for tool in listed["result"]["tools"]], ["search_memories"]
        )

    def test_mcp_tools_call_returns_bounded_local_results(self):
        result = {"id": "m1", "memory": "A durable choice", "score": 0.9}
        with mock.patch.object(
            mcp_server, "search_memories", return_value=[result]
        ) as search:
            called = mcp_server.handle(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {
                        "name": "search_memories",
                        "arguments": {
                            "query": "choice",
                            "top_k": 50,
                            "project": "demo",
                        },
                    },
                }
            )
        search.assert_called_once_with("choice", "demo", limit=20, threshold=None)
        payload = json.loads(called["result"]["content"][0]["text"])
        self.assertEqual(payload["results"][0]["memory"], "A durable choice")

    def test_manifest_and_marketplace_paths_resolve(self):
        manifest = json.loads(
            (PLUGIN / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8")
        )
        self.assertTrue((PLUGIN / manifest["skills"].removeprefix("./")).is_dir())
        self.assertTrue((PLUGIN / manifest["mcpServers"].removeprefix("./")).is_file())
        repository = PLUGIN.parents[1]
        marketplace_path = repository / ".agents" / "plugins" / "marketplace.json"
        marketplace = json.loads(marketplace_path.read_text(encoding="utf-8"))
        source = marketplace["plugins"][0]["source"]["path"].removeprefix("./")
        self.assertEqual((repository / source).resolve(), PLUGIN.resolve())


if __name__ == "__main__":
    unittest.main()
