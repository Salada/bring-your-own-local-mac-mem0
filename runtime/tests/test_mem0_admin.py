import importlib.machinery
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SCRIPT = Path(__file__).parents[1] / "bin" / "mem0-admin"
LOADER = importlib.machinery.SourceFileLoader("mem0_admin", str(SCRIPT))
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
mem0_admin = importlib.util.module_from_spec(SPEC)
sys.modules[LOADER.name] = mem0_admin
LOADER.exec_module(mem0_admin)


def item(memory_id, text, kind="decision", created="2026-09-01T00:00:00+00:00", pinned=False):
    return {
        "id": memory_id,
        "memory": text,
        "hash": f"hash-{memory_id}",
        "created_at": created,
        "updated_at": created,
        "metadata": {"type": kind, "pinned": pinned},
    }


class Mem0AdminTest(unittest.TestCase):
    def test_category_recommendation_is_preview_only(self):
        response = {"mode": "preview", "applied": False, "recommended_categories": [{"work": "Work facts"}]}
        with (
            mock.patch.object(mem0_admin, "http_json", return_value=response) as request,
            mock.patch.object(mem0_admin, "capture_backup") as backup,
            mock.patch("builtins.print"),
        ):
            mem0_admin.recommend_categories("Coding assistant", 8)

        backup.assert_not_called()
        self.assertEqual(request.call_args.args, ("POST", "/v1/admin/categories/recommend"))
        self.assertEqual(request.call_args.kwargs["data"], {"use_case": "Coding assistant", "max_categories": 8})

    def test_backup_prefers_sibling_command_without_path_dependency(self):
        completed = mock.Mock(stdout="[time] captured\n/backup/generation\n")
        with mock.patch.object(mem0_admin.subprocess, "run", return_value=completed) as run:
            self.assertEqual(mem0_admin.capture_backup(), "/backup/generation")

        self.assertEqual(run.call_args.args[0], [str(SCRIPT.with_name("mem0-backup")), "capture"])

    def test_auto_rejects_noninteractive_yes_bypass(self):
        with mock.patch.object(sys, "argv", ["mem0-admin", "dream", "--auto", "--yes"]):
            self.assertEqual(mem0_admin.main(), 1)

    def test_plan_only_deletes_exact_duplicates_and_expired_temporary_items(self):
        memories = [
            item("new", "Use SQLite", created="2026-09-02T00:00:00+00:00"),
            item("old", "Use SQLite", created="2026-09-01T00:00:00+00:00"),
            item("temp", "old session", kind="session_state", created="2020-01-01T00:00:00+00:00"),
            item("pinned", "old summary", kind="compact_summary", created="2020-01-01T00:00:00+00:00", pinned=True),
            item("unique", "Use Qdrant"),
        ]

        actions, omitted = mem0_admin.plan_actions(mem0_admin.analyze(memories))

        self.assertEqual({action["memory_id"] for action in actions}, {"old", "temp"})
        duplicate = next(action for action in actions if action["memory_id"] == "old")
        self.assertEqual(duplicate["keeper_id"], "new")
        self.assertEqual(omitted, 0)

    def test_iter_memories_follows_cursors_and_deduplicates_ids(self):
        responses = [
            {"results": [item("1", "one"), item("2", "two")], "next_cursor": "cursor-2"},
            {"results": [item("2", "two"), item("3", "three")], "next_cursor": None},
        ]
        with mock.patch.object(mem0_admin, "http_json", side_effect=responses) as request:
            results = list(mem0_admin.iter_memories("project"))

        self.assertEqual([entry["id"] for entry in results], ["1", "2", "3"])
        self.assertEqual(request.call_count, 2)
        self.assertTrue(all(call.kwargs["params"]["show_expired"] for call in request.call_args_list))

    def test_apply_backs_up_before_any_guarded_delete(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan_path = root / "plan.json"
            action = {
                "action": "delete",
                "memory_id": "old",
                "expected_hash": "hash-old",
                "expected_revision": "2026-09-01T00:00:00+00:00",
                "reason": "exact_duplicate",
                "keeper_id": "new",
                "keeper_hash": "hash-new",
                "keeper_revision": "2026-09-02T00:00:00+00:00",
                "preview": "Use SQLite",
            }
            plan_path.write_text(
                json.dumps({"schema_version": 1, "user_id": mem0_admin.USER_ID, "app_id": None, "actions": [action]}),
                encoding="utf-8",
            )
            events = []

            def backup():
                events.append("backup")
                return "/backup/generation"

            def delete(*_args):
                events.append("delete")

            with (
                mock.patch.object(mem0_admin, "STATE_ROOT", root / "state"),
                mock.patch.object(mem0_admin, "validate_action", return_value=item("old", "Use SQLite")),
                mock.patch.object(mem0_admin, "capture_backup", side_effect=backup),
                mock.patch.object(mem0_admin, "guarded_delete", side_effect=delete),
            ):
                mem0_admin.apply_plan(plan_path, assume_yes=True)

        self.assertEqual(events, ["backup", "delete"])

    def test_oversized_plan_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            plan_path = Path(temporary) / "plan.json"
            plan_path.write_text(
                json.dumps(
                    {"schema_version": 1, "user_id": mem0_admin.USER_ID, "actions": [{"action": "delete"}] * 11}
                ),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(mem0_admin.AdminError, "oversized"):
                mem0_admin.load_plan(plan_path)

    def test_validate_exact_duplicate_rechecks_keeper(self):
        action = {
            "memory_id": "old",
            "expected_hash": "hash-old",
            "expected_revision": "2026-09-01T00:00:00+00:00",
            "reason": "exact_duplicate",
            "keeper_id": "new",
            "keeper_hash": "hash-new",
            "keeper_revision": "2026-09-02T00:00:00+00:00",
        }
        responses = [
            {**item("old", "Use SQLite", created="2026-09-01T00:00:00+00:00"), "user_id": mem0_admin.USER_ID},
            {**item("new", "Use PostgreSQL", created="2026-09-02T00:00:00+00:00"), "user_id": mem0_admin.USER_ID},
        ]
        with mock.patch.object(mem0_admin, "get_memory", side_effect=responses):
            with self.assertRaisesRegex(mem0_admin.AdminError, "no longer an exact duplicate"):
                mem0_admin.validate_action(action)

    def test_forget_stops_if_memory_changes_after_confirmation(self):
        original = {**item("target", "old content"), "user_id": mem0_admin.USER_ID}
        changed = {**item("target", "new content"), "user_id": mem0_admin.USER_ID, "hash": "new-hash"}
        with (
            tempfile.TemporaryDirectory() as temporary,
            mock.patch.object(mem0_admin, "STATE_ROOT", Path(temporary)),
            mock.patch.object(mem0_admin, "get_memory", side_effect=[original, changed]),
            mock.patch.object(mem0_admin, "capture_backup") as backup,
        ):
            with self.assertRaisesRegex(mem0_admin.AdminError, "changed after confirmation"):
                mem0_admin.forget(None, "target", None, assume_yes=True)
        backup.assert_not_called()

    def test_exact_duplicate_delete_sends_keeper_expectations(self):
        target = {**item("old", "Use SQLite"), "user_id": mem0_admin.USER_ID}
        action = {
            "reason": "exact_duplicate",
            "keeper_id": "new",
            "keeper_hash": "hash-new",
            "keeper_revision": "2026-09-02T00:00:00+00:00",
        }
        with mock.patch.object(mem0_admin, "http_json", return_value={}) as request:
            mem0_admin.guarded_delete(target, "project", action)

        params = request.call_args.kwargs["params"]
        self.assertEqual(params["expected_keeper_id"], "new")
        self.assertEqual(params["expected_keeper_hash"], "hash-new")
        self.assertEqual(params["expected_keeper_revision"], "2026-09-02T00:00:00+00:00")

    def test_category_backfill_dry_run_never_backs_up_or_applies(self):
        response = {
            "scanned": 1,
            "categorized": 1,
            "applied": 0,
            "items": [{"id": "m1", "categories": ["technology"]}],
            "next_cursor": None,
        }
        with (
            mock.patch.object(mem0_admin, "http_json", return_value=response) as request,
            mock.patch.object(mem0_admin, "capture_backup") as backup,
            mock.patch("builtins.print"),
        ):
            mem0_admin.categorize_backfill(
                apply=False,
                overwrite=False,
                page_size=25,
                max_items=100,
                assume_yes=False,
            )

        backup.assert_not_called()
        self.assertFalse(request.call_args.kwargs["data"]["apply"])

    def test_category_backfill_apply_backs_up_before_first_page(self):
        events = []

        def backup():
            events.append("backup")
            return "/backup/generation"

        def request(*_args, **_kwargs):
            events.append("request")
            return {"scanned": 0, "categorized": 0, "applied": 0, "next_cursor": None}

        with (
            mock.patch.object(mem0_admin, "capture_backup", side_effect=backup),
            mock.patch.object(mem0_admin, "http_json", side_effect=request),
            mock.patch("builtins.print"),
        ):
            mem0_admin.categorize_backfill(
                apply=True,
                overwrite=False,
                page_size=25,
                max_items=100,
                assume_yes=True,
            )

        self.assertEqual(events, ["backup", "request"])


if __name__ == "__main__":
    unittest.main()
