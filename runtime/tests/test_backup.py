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
    def make_generation(self, root: Path) -> Path:
        generation = root / "mem0-2026-09-07T03:00:00+00:00"
        generation.mkdir()
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
            "created_at": "2026-09-07T03:00:00+00:00",
            "timezone": "UTC",
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
            mock.patch.dict(os.environ, {"QDRANT_VERSION": "latest --privileged"}),
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
            with mock.patch.object(backup_lock, "LOCK_PATH", lock_path):
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
