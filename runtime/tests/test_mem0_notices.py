import unittest
from unittest import mock

from mem0.memory import notices


class Mem0NoticeTest(unittest.TestCase):
    def test_telemetry_disabled_skips_notice_fetch(self):
        with (
            mock.patch.object(notices.telemetry_module, "MEM0_TELEMETRY", False),
            mock.patch.object(notices, "_claim_first_run_notice") as claim,
            mock.patch.object(notices, "_fetch_remote_config") as fetch,
        ):
            notices.display_first_run_notice(None, "sync", "add")

        claim.assert_not_called()
        fetch.assert_not_called()
