import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from env_loader import load_env_file


class EnvLoaderTest(unittest.TestCase):
    def test_loads_values_without_executing_shell(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            marker = root / "executed"
            path = root / ".env"
            path.write_text(
                f"MEM0_DEFAULT_USER_ID=test-user\nBAD-KEY=no\nVALUE=$(touch {marker})\n",
                encoding="utf-8",
            )
            with mock.patch.dict(os.environ, {}, clear=True):
                load_env_file(path)
                self.assertEqual(os.environ["MEM0_DEFAULT_USER_ID"], "test-user")
                self.assertEqual(os.environ["VALUE"], f"$(touch {marker})")
                self.assertNotIn("BAD-KEY", os.environ)
                self.assertFalse(marker.exists())


if __name__ == "__main__":
    unittest.main()
