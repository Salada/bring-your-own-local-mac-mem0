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
            [f"print {service}", f"bootstrap gui/{os.getuid()} {plist}"],
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


if __name__ == "__main__":
    unittest.main()
