import os
import subprocess
import tempfile
import unittest
from pathlib import Path

RUNTIME = Path(__file__).parents[1]
CTL = RUNTIME / "bin" / "mem0-ctl"
STOP = RUNTIME / "stop.sh"


class RuntimeControlTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.bin_dir = self.root / "bin"
        self.bin_dir.mkdir()
        self.log = self.root / "calls.log"
        self._command(
            "launchctl",
            """#!/bin/sh
printf '%s\\n' "$*" >> "$FAKE_LOG"
if [ "$1" = print ]; then
    exit "${FAKE_PRINT_EXIT:-1}"
fi
""",
        )
        self._command(
            "docker",
            """#!/bin/sh
printf 'docker %s\\n' "$*" >> "$FAKE_LOG"
""",
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def _command(self, name, source):
        path = self.bin_dir / name
        path.write_text(source)
        path.chmod(0o755)

    def _env(self, **overrides):
        return {
            **os.environ,
            "PATH": f"{self.bin_dir}:/usr/bin:/bin",
            "FAKE_LOG": str(self.log),
            **overrides,
        }

    def test_start_bootstraps_configured_launchd_job(self):
        mem0_home = self.root / "mem0"
        mem0_home.mkdir()
        plist = self.root / "com.salada.mem0.plist"
        plist.touch()
        subprocess.run(
            [str(CTL), "start"],
            check=True,
            env=self._env(
                MEM0_HOME=str(mem0_home),
                MEM0_LAUNCHD_LABEL="com.salada.mem0",
                MEM0_LAUNCHD_PLIST=str(plist),
            ),
        )
        service = f"gui/{os.getuid()}/com.salada.mem0"
        self.assertEqual(
            self.log.read_text().splitlines(),
            [
                f"docker compose --project-directory {mem0_home} up -d",
                f"print {service}",
                f"bootstrap gui/{os.getuid()} {plist}",
            ],
        )

    def test_stop_boots_out_configured_launchd_job(self):
        subprocess.run(
            [str(STOP)],
            check=True,
            env=self._env(
                MEM0_LAUNCHD_LABEL="com.salada.mem0",
                FAKE_PRINT_EXIT="0",
            ),
        )
        service = f"gui/{os.getuid()}/com.salada.mem0"
        self.assertEqual(
            self.log.read_text().splitlines(),
            [f"print {service}", f"bootout {service}", "docker compose down"],
        )

    def test_agents_configure_uses_native_client_commands(self):
        self._command(
            "codex",
            """#!/bin/sh
printf 'codex %s\\n' "$*" >> "$FAKE_LOG"
""",
        )
        self._command(
            "opencode",
            """#!/bin/sh
printf 'opencode %s\\n' "$*" >> "$FAKE_LOG"
""",
        )
        self._command(
            "agy",
            """#!/bin/sh
printf 'agy %s\\n' "$*" >> "$FAKE_LOG"
""",
        )

        result = subprocess.run(
            [str(CTL), "agents", "configure"],
            check=True,
            env=self._env(MEM0_MCP_URL="http://127.0.0.1:9999/mcp"),
            text=True,
            capture_output=True,
        )

        self.assertEqual(
            self.log.read_text().splitlines(),
            [
                "codex mcp get mem0",
                "codex mcp remove mem0",
                "codex mcp add mem0 --url http://127.0.0.1:9999/mcp",
                "opencode mcp add mem0 --url http://127.0.0.1:9999/mcp",
                "agy mcp add --type http mem0 http://127.0.0.1:9999/mcp",
            ],
        )
        self.assertIn("their use remains model-selected", result.stdout)
        self.assertIn("codex-hooks install", result.stdout)

    def test_agents_remove_continues_after_opencode_guidance(self):
        for agent in ("codex", "opencode", "agy"):
            self._command(
                agent,
                f"""#!/bin/sh
printf '{agent} %s\\n' "$*" >> "$FAKE_LOG"
""",
            )

        result = subprocess.run(
            [str(CTL), "agents", "remove"],
            env=self._env(),
            text=True,
            capture_output=True,
        )

        self.assertEqual(result.returncode, 2)
        self.assertEqual(
            self.log.read_text().splitlines(),
            ["codex mcp remove mem0", "agy mcp remove mem0"],
        )
        self.assertIn("remove mcp.mem0", result.stderr)

    def test_codex_hooks_uses_runtime_python(self):
        mem0_home = self.root / "mem0"
        runtime_python = mem0_home / ".venv" / "bin" / "python"
        runtime_python.parent.mkdir(parents=True)
        runtime_python.write_text(
            '#!/bin/sh\nprintf \'python %s\\n\' "$*" >> "$FAKE_LOG"\n',
            encoding="utf-8",
        )
        runtime_python.chmod(0o755)
        (mem0_home / "codex_hook.py").touch()

        subprocess.run(
            [str(CTL), "codex-hooks", "status"],
            check=True,
            env=self._env(MEM0_HOME=str(mem0_home)),
        )

        self.assertEqual(
            self.log.read_text().splitlines(),
            [f"python {mem0_home / 'codex_hook.py'} status"],
        )


if __name__ == "__main__":
    unittest.main()
