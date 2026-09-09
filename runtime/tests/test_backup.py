import importlib.machinery
import importlib.util
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "bin" / "mem0-backup"
LOADER = importlib.machinery.SourceFileLoader("mem0_backup", str(SCRIPT))
SPEC = importlib.util.spec_from_loader(LOADER.name, LOADER)
mem0_backup = importlib.util.module_from_spec(SPEC)
sys.modules[LOADER.name] = mem0_backup
LOADER.exec_module(mem0_backup)
sys.path.insert(0, str(ROOT))
import backup_lock  # noqa: E402 - runtime path is inserted above for the script test


class GenerationTest(unittest.TestCase):
    def test_generation_uses_utc_rfc3339(self):
        instant = datetime(2026, 9, 6, 18, 0, tzinfo=timezone.utc)
        name = mem0_backup.generation_name(instant)

        self.assertEqual(name, "mem0-2026-09-06T18:00:00+00:00")
        self.assertEqual(mem0_backup.parse_generation(name).utcoffset(), timedelta(0))

    def test_generation_rejects_utc_and_malformed_names(self):
        for name in (
            "mem0-2026-09-07T03:00:00Z",
            "mem0-2026-09-07T03-00-00+09-00",
            "mem0-latest",
        ):
            with self.subTest(name=name), self.assertRaises(ValueError):
                mem0_backup.parse_generation(name)

    def test_due_after_seven_days(self):
        old = mem0_backup.parse_generation("mem0-2026-08-31T03:00:00+00:00")
        before = old + timedelta(days=7) - timedelta(seconds=1)
        at = old + timedelta(days=7)

        self.assertFalse(mem0_backup.backup_due([(old, mem0_backup.generation_name(old))], before))
        self.assertTrue(mem0_backup.backup_due([(old, mem0_backup.generation_name(old))], at))


class LocalBackupTest(unittest.TestCase):
    def make_generation(self, root: Path, name: str = "mem0-2026-09-07T03:00:00+00:00") -> Path:
        generation = root / name
        generation.mkdir(parents=True)
        database_path = generation / "history.db"
        database = sqlite3.connect(database_path)
        database.execute("CREATE TABLE history (id INTEGER PRIMARY KEY, value TEXT)")
        database.execute("INSERT INTO history(value) VALUES ('ok')")
        database.commit()
        database.close()
        (generation / "qdrant.snapshot").write_bytes(b"qdrant-snapshot")
        files = {
            name: {
                "sha256": mem0_backup.sha256(generation / name),
                "size": (generation / name).stat().st_size,
            }
            for name in ("history.db", "qdrant.snapshot")
        }
        manifest = {
            "schema_version": 1,
            "generation": generation.name,
            "created_at": generation.name.removeprefix("mem0-"),
            "timezone": "UTC",
            "qdrant": {
                "version": "1.15.4",
                "collection": "mem0",
                "points_count": 1,
                "vectors": {"size": 2560, "distance": "Cosine"},
            },
            "sqlite": {"rows": {"history": 1}},
            "files": files,
        }
        (generation / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        (generation / "SHA256SUMS").write_text(
            "".join(f"{files[name]['sha256']}  {name}\n" for name in sorted(files)),
            encoding="utf-8",
        )
        return generation

    def test_sqlite_online_backup_and_verify(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source.db"
            source_db = sqlite3.connect(source)
            source_db.execute("CREATE TABLE messages (id INTEGER PRIMARY KEY)")
            source_db.executemany("INSERT INTO messages DEFAULT VALUES", [(), ()])
            source_db.commit()
            source_db.close()

            rows = mem0_backup.sqlite_backup(source, root / "backup.db")

            self.assertEqual(rows, {"messages": 2})
            mem0_backup.verify(self.make_generation(root))

    def test_quiesced_sqlite_copy_uses_restricted_container(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "source.db"
            destination = root / "backup.db"
            database = sqlite3.connect(source)
            database.execute("CREATE TABLE history (id INTEGER PRIMARY KEY)")
            database.execute("INSERT INTO history DEFAULT VALUES")
            database.commit()
            database.close()

            def fake_run(command, **kwargs):
                shutil.copyfile(source, destination)
                return subprocess.CompletedProcess(command, 0)

            with mock.patch.object(mem0_backup.subprocess, "run", side_effect=fake_run) as run:
                rows = mem0_backup.copy_quiesced_sqlite(source, destination)

            command = run.call_args.args[0]
            self.assertEqual(rows, {"history": 1})
            self.assertIn("--network", command)
            self.assertIn("none", command)
            self.assertIn("--read-only", command)
            self.assertIn("ALL", command)

    def test_quiesced_sqlite_copy_rejects_unsafe_image_version(self):
        with (
            tempfile.TemporaryDirectory() as temp_dir,
            mock.patch.dict(os.environ, {"QDRANT_IMAGE": "latest --privileged"}),
        ):
            with self.assertRaisesRegex(mem0_backup.BackupError, "unsafe characters"):
                mem0_backup.copy_quiesced_sqlite(Path(temp_dir) / "source.db", Path(temp_dir) / "backup.db")

    def test_verify_detects_tampering(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            generation = self.make_generation(Path(temp_dir))
            (generation / "qdrant.snapshot").write_bytes(b"tampered")

            with self.assertRaises(mem0_backup.BackupError):
                mem0_backup.verify(generation)

    def test_partial_capture_is_verified_against_expected_generation(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            generation = self.make_generation(Path(temp_dir))
            expected_name = generation.name
            partial = generation.with_name(f"._partial-{expected_name}")
            generation.rename(partial)

            manifest = mem0_backup.verify(partial, expected_name=expected_name)

            self.assertEqual(manifest["generation"], expected_name)

    def test_env_file_is_parsed_without_shell_execution(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            marker = root / "executed"
            env_file = root / ".env"
            env_file.write_text(f"MEM0_TEST_VALUE=$(touch {marker})\n", encoding="utf-8")
            with mock.patch.dict(os.environ, {}, clear=True):
                mem0_backup.load_env_file(env_file)
                self.assertEqual(os.environ["MEM0_TEST_VALUE"], f"$(touch {marker})")
                self.assertFalse(marker.exists())

    def test_backup_lock_blocks_mutations_until_capture_releases(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            lock_path = Path(temp_dir) / "write.lock"
            environment = os.environ.copy()
            environment["MEM0_WRITE_LOCK_PATH"] = str(lock_path)
            environment["PYTHONPATH"] = str(ROOT)
            child_code = (
                "from backup_lock import mutation_lock\n"
                "print('ready', flush=True)\n"
                "with mutation_lock():\n"
                "    print('acquired', flush=True)\n"
            )
            with mock.patch.dict(os.environ, {"MEM0_WRITE_LOCK_PATH": str(lock_path)}):
                with backup_lock.backup_lock():
                    child = subprocess.Popen(
                        [sys.executable, "-c", child_code],
                        env=environment,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                    )
                    self.assertEqual(child.stdout.readline().strip(), "ready")
                    time.sleep(0.1)
                    self.assertIsNone(child.poll())
                stdout, stderr = child.communicate(timeout=3)

            self.assertEqual(child.returncode, 0, stderr)
            self.assertEqual(stdout.strip(), "acquired")


class RestoreTest(unittest.TestCase):
    def test_qdrant_snapshot_version_gate(self):
        for current in ("1.15.4", "1.15.9", "1.16.0"):
            with self.subTest(current=current):
                mem0_backup.require_qdrant_compatibility("1.15.4", current)
        for current in ("1.15.3", "1.17.0", "2.15.4"):
            with self.subTest(current=current), self.assertRaises(mem0_backup.BackupError):
                mem0_backup.require_qdrant_compatibility("1.15.4", current)

    def test_restore_requires_explicit_yes_before_lookup(self):
        with (
            mock.patch.object(mem0_backup, "restore_generation") as restore_generation,
            self.assertRaisesRegex(mem0_backup.BackupError, "pass --yes"),
        ):
            mem0_backup.restore("mem0-2026-09-07T03:00:00+00:00", confirmed=False)

        restore_generation.assert_not_called()

    def test_restore_requires_installed_launchd_managed_runtime(self):
        with (
            mock.patch.dict(os.environ, {"MEM0_HOME": "/different/runtime"}),
            self.assertRaisesRegex(mem0_backup.BackupError, "installed MEM0_HOME"),
        ):
            mem0_backup.require_managed_runtime()

        with tempfile.TemporaryDirectory() as temp_dir:
            runtime = Path(temp_dir)
            with (
                mock.patch.object(mem0_backup, "RUNTIME_DIR", runtime),
                mock.patch.dict(
                    os.environ,
                    {
                        "MEM0_HOME": str(runtime),
                        "MEM0_LAUNCHD_PLIST": str(runtime / "missing.plist"),
                    },
                ),
                self.assertRaisesRegex(mem0_backup.BackupError, "launchd-managed API"),
            ):
                mem0_backup.require_managed_runtime()

    def test_qdrant_restore_upload_is_pinned_to_snapshot_checksum(self):
        generation = Path("/safe/generation")
        manifest = {"files": {"qdrant.snapshot": {"sha256": "abc123"}}}
        response = subprocess.CompletedProcess(["curl"], 0, stdout='{"result":true,"status":"ok"}', stderr="")
        with mock.patch.object(mem0_backup, "run_checked", return_value=response) as run:
            mem0_backup.recover_qdrant(generation, "http://127.0.0.1:6333", "mem0/local", manifest)

        command = run.call_args.args[0]
        self.assertIn(f"snapshot=@{generation / 'qdrant.snapshot'}", command)
        self.assertIn("/collections/mem0%2Flocal/snapshots/upload?", command[-1])
        self.assertIn("priority=snapshot", command[-1])
        self.assertIn("checksum=abc123", command[-1])

    def test_restore_stops_stack_before_rollback_capture_and_restarts_after_verification(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target = LocalBackupTest().make_generation(root / "staging")
            rollback = LocalBackupTest().make_generation(
                root / "restore" / "rollback", "mem0-2026-09-09T01:00:00+00:00"
            )
            history = root / "history.db"
            events = []

            def control(action):
                events.append(action)

            def capture(**_kwargs):
                events.append("capture")
                return rollback

            with (
                mock.patch.dict(
                    os.environ,
                    {
                        "MEM0_BACKUP_STAGING_DIR": str(target.parent),
                        "MEM0_RESTORE_STATE_DIR": str(root / "restore"),
                        "MEM0_HISTORY_DB": str(history),
                    },
                ),
                mock.patch.object(
                    mem0_backup,
                    "qdrant_metadata",
                    return_value={"version": "1.15.4"},
                ),
                mock.patch.object(mem0_backup, "require_managed_runtime"),
                mock.patch.object(mem0_backup, "control_stack", side_effect=control),
                mock.patch.object(
                    mem0_backup, "wait_for_mem0_down", side_effect=lambda *_args: events.append("api-down")
                ),
                mock.patch.object(mem0_backup, "start_qdrant", side_effect=lambda: events.append("qdrant")),
                mock.patch.object(mem0_backup, "wait_for_qdrant", return_value="1.15.4"),
                mock.patch.object(mem0_backup, "capture", side_effect=capture),
                mock.patch.object(mem0_backup, "maintenance_lock", return_value=nullcontext()),
                mock.patch.object(
                    mem0_backup,
                    "recover_qdrant",
                    side_effect=lambda *_args: events.append("restore-qdrant"),
                ),
                mock.patch.object(
                    mem0_backup,
                    "restore_history",
                    side_effect=lambda *_args: events.append("restore-history"),
                ),
                mock.patch.object(
                    mem0_backup,
                    "verify_restored_state",
                    side_effect=lambda *_args: events.append("verify"),
                ),
            ):
                result = mem0_backup.restore(target.name, confirmed=True)

            self.assertEqual(result, rollback)
            self.assertEqual(
                events,
                [
                    "stop",
                    "api-down",
                    "qdrant",
                    "capture",
                    "restore-qdrant",
                    "restore-history",
                    "verify",
                    "start",
                ],
            )
            self.assertFalse((root / "restore" / "in-progress.json").exists())

    def test_failed_restore_keeps_marker_and_api_down_for_exact_rollback(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            target = LocalBackupTest().make_generation(root / "staging")
            rollback = LocalBackupTest().make_generation(
                root / "restore" / "rollback", "mem0-2026-09-09T01:00:00+00:00"
            )
            actions = []
            with (
                mock.patch.dict(
                    os.environ,
                    {
                        "MEM0_BACKUP_STAGING_DIR": str(target.parent),
                        "MEM0_RESTORE_STATE_DIR": str(root / "restore"),
                    },
                ),
                mock.patch.object(
                    mem0_backup,
                    "qdrant_metadata",
                    return_value={"version": "1.15.4"},
                ),
                mock.patch.object(mem0_backup, "require_managed_runtime"),
                mock.patch.object(mem0_backup, "control_stack", side_effect=actions.append),
                mock.patch.object(mem0_backup, "wait_for_mem0_down"),
                mock.patch.object(mem0_backup, "start_qdrant"),
                mock.patch.object(mem0_backup, "wait_for_qdrant", return_value="1.15.4"),
                mock.patch.object(mem0_backup, "capture", return_value=rollback),
                mock.patch.object(mem0_backup, "maintenance_lock", return_value=nullcontext()),
                mock.patch.object(
                    mem0_backup,
                    "recover_qdrant",
                    side_effect=mem0_backup.BackupError("injected failure"),
                ),
                self.assertRaisesRegex(mem0_backup.BackupError, "rollback generation"),
            ):
                mem0_backup.restore(target.name, confirmed=True)

            marker_path = root / "restore" / "in-progress.json"
            marker = json.loads(marker_path.read_text(encoding="utf-8"))
            self.assertEqual(actions, ["stop"])
            self.assertEqual(marker["rollback_generation"], rollback.name)
            self.assertEqual(marker["phase"], "qdrant")

            with (
                mock.patch.dict(
                    os.environ,
                    {"MEM0_RESTORE_STATE_DIR": str(root / "restore")},
                ),
                mock.patch.object(mem0_backup, "restore_generation") as restore_generation,
            ):
                with self.assertRaises(mem0_backup.BackupError) as raised:
                    mem0_backup.restore(target.name, confirmed=True)
            self.assertIn(rollback.name, str(raised.exception))
            restore_generation.assert_not_called()

    def test_incomplete_restore_can_recover_when_live_collection_is_unavailable(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            rollback = LocalBackupTest().make_generation(
                root / "restore" / "rollback", "mem0-2026-09-09T01:00:00+00:00"
            )
            marker_path = root / "restore" / "in-progress.json"
            marker_path.parent.mkdir(parents=True, exist_ok=True)
            marker_path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "target_generation": "mem0-2026-09-07T03:00:00+00:00",
                        "rollback_generation": rollback.name,
                        "rollback_path": str(rollback),
                        "phase": "history",
                    }
                ),
                encoding="utf-8",
            )
            with (
                mock.patch.dict(
                    os.environ,
                    {"MEM0_RESTORE_STATE_DIR": str(root / "restore")},
                ),
                mock.patch.object(
                    mem0_backup,
                    "qdrant_metadata",
                    side_effect=mem0_backup.BackupError("collection unavailable"),
                ) as metadata,
                mock.patch.object(mem0_backup, "control_stack"),
                mock.patch.object(mem0_backup, "require_managed_runtime"),
                mock.patch.object(mem0_backup, "wait_for_mem0_down"),
                mock.patch.object(mem0_backup, "start_qdrant"),
                mock.patch.object(mem0_backup, "wait_for_qdrant", return_value="1.15.4"),
                mock.patch.object(mem0_backup, "maintenance_lock", return_value=nullcontext()),
                mock.patch.object(mem0_backup, "recover_qdrant"),
                mock.patch.object(mem0_backup, "restore_history"),
                mock.patch.object(mem0_backup, "verify_restored_state"),
            ):
                self.assertEqual(mem0_backup.restore(rollback.name, confirmed=True), rollback)

            metadata.assert_not_called()
            self.assertFalse(marker_path.exists())

    def test_restored_vector_verification_ignores_non_shape_fields(self):
        manifest = {
            "qdrant": {
                "points_count": 1,
                "vectors": {"size": 2560, "distance": "Cosine"},
            },
            "sqlite": {"rows": {"history": 1}},
        }
        with (
            mock.patch.object(
                mem0_backup,
                "qdrant_metadata",
                return_value={
                    "points_count": 1,
                    "vectors": {"size": 2560, "distance": "Cosine", "on_disk": True},
                },
            ),
            mock.patch.object(mem0_backup, "sqlite_counts", return_value={"history": 1}),
        ):
            mem0_backup.verify_restored_state(manifest, "http://127.0.0.1:6333", "mem0", Path("/history.db"))

    def test_restore_history_replaces_database_and_removes_sidecars(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            generation = LocalBackupTest().make_generation(root / "generation")
            live = root / "history.db"
            database = sqlite3.connect(live)
            database.execute("CREATE TABLE obsolete (id INTEGER PRIMARY KEY)")
            database.commit()
            database.close()
            for suffix in ("-wal", "-shm", "-journal"):
                live.with_name(live.name + suffix).write_bytes(b"stale")

            mem0_backup.restore_history(generation, live, {"history": 1})

            self.assertEqual(mem0_backup.sqlite_counts(live), {"history": 1})
            for suffix in ("-wal", "-shm", "-journal"):
                self.assertFalse(live.with_name(live.name + suffix).exists())

    def test_restore_state_paths_follow_environment_after_import(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            with mock.patch.dict(
                os.environ,
                {
                    "MEM0_WRITE_LOCK_PATH": str(root / "custom.lock"),
                    "MEM0_RESTORE_STATE_DIR": str(root / "restore"),
                },
            ):
                with backup_lock.backup_lock():
                    self.assertTrue((root / "custom.lock").exists())
                self.assertEqual(backup_lock.restore_marker(), root / "restore" / "in-progress.json")


class RemotePolicyTest(unittest.TestCase):
    def test_remote_root_rejects_empty_root_and_parent_traversal(self):
        for value in ("", "backup:/", "backup:/home/../unsafe", "not-a-remote"):
            with (
                self.subTest(value=value),
                mock.patch.dict(os.environ, {"MEM0_BACKUP_REMOTE": value}, clear=False),
                self.assertRaises(mem0_backup.BackupError),
            ):
                mem0_backup.remote_root()

    def test_local_partials_are_reported_but_not_resumed(self):
        with (
            tempfile.TemporaryDirectory() as temp_dir,
            mock.patch.dict(os.environ, {"MEM0_BACKUP_STAGING_DIR": temp_dir}),
        ):
            root = Path(temp_dir)
            partial = root / "._partial-mem0-2026-09-07T03:00:00+00:00"
            partial.mkdir()
            (root / "._partial-invalid").mkdir()

            self.assertEqual(mem0_backup.local_partials(), [partial])
            self.assertEqual(mem0_backup.local_pending(), [])

    def test_rotation_only_prunes_oldest_valid_generation(self):
        generations = []
        start = datetime(2026, 6, 1, 3, tzinfo=mem0_backup.BACKUP_TZ)
        for week in range(13):
            instant = start + timedelta(days=7 * week)
            generations.append((instant, mem0_backup.generation_name(instant)))
        with (
            mock.patch.object(mem0_backup, "remote_generations", return_value=generations),
            mock.patch.object(mem0_backup, "rclone") as rclone,
        ):
            expired = mem0_backup.rotate("backup:/mem0-backups")

        self.assertEqual(expired, [generations[0][1]])
        rclone.assert_called_once_with("purge", f"backup:/mem0-backups/{generations[0][1]}")

    def test_publish_resumes_after_remote_final_was_already_created(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            generation = LocalBackupTest().make_generation(Path(temp_dir))
            created_at = mem0_backup.parse_generation(generation.name)
            with (
                mock.patch.object(
                    mem0_backup,
                    "remote_generations",
                    return_value=[(created_at, generation.name)],
                ),
                mock.patch.object(mem0_backup, "rclone") as rclone,
            ):
                mem0_backup.publish(generation, "backup:/mem0-backups")

        rclone.assert_called_once_with(
            "check",
            str(generation),
            f"backup:/mem0-backups/{generation.name}",
            "--download",
        )

    def test_sigterm_becomes_a_backup_error(self):
        with self.assertRaisesRegex(mem0_backup.BackupError, "termination requested"):
            mem0_backup.terminate(15, None)


if __name__ == "__main__":
    unittest.main()
