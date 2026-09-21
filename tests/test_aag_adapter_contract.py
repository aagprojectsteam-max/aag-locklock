"""Regression tests for the narrow AAG safe-suspend adapter contract."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

import aag_sleep_transaction_compat as compat
import input_lock_safety as safety


class AAGAdapterContractTests(unittest.TestCase):
    def test_stack_ready_delegates_when_transaction_config_exists(self):
        config = Mock()
        config.exists.return_value = True
        runner = Mock()
        with (
            patch.object(safety, "AAG_TRANSACTION_CONFIG", config),
            patch.object(compat, "stack_ready", return_value=True) as delegate,
        ):
            self.assertTrue(safety.stack_ready(runner))
        delegate.assert_called_once_with(runner)

    def test_resume_confirmation_delegates_when_transaction_config_exists(self):
        config = Mock()
        config.exists.return_value = True
        with (
            patch.object(safety, "AAG_TRANSACTION_CONFIG", config),
            patch.object(compat, "resume_confirmed", return_value=True) as delegate,
        ):
            self.assertTrue(safety.aag_resume_confirmed(123.5))
        delegate.assert_called_once_with(123.5)

    def test_legacy_graph_remains_fail_closed_without_adapter(self):
        config = Mock()
        config.exists.return_value = False
        runner = Mock(return_value=SimpleNamespace(returncode=1, stdout=""))
        with patch.object(safety, "AAG_TRANSACTION_CONFIG", config):
            self.assertFalse(safety.stack_ready(runner))
        self.assertTrue(runner.called)

    def test_adapter_graph_requires_every_expected_token(self):
        good = {
            "systemd-suspend.service": (
                "aag-storage-sleep-v2.service aag-suspend-failure-failsafe.service "
                "/usr/lib/systemd/systemd-sleep suspend aag-sleep-transaction native-pre "
                "aag-sleep-transaction native-post"
            ),
            "aag-storage-sleep-v2.service": (
                "aag-ugreen-sleep-guard-v2 pre aag-sleep-transaction begin "
                "aag-sleep-transaction verify-release"
            ),
            "aag-suspend-failure-failsafe.service": (
                "aag-sleep-transaction failure-recover --what=sleep:handle-lid-switch"
            ),
            "aag-t700-resume-check.service": (
                "aag-sleep-transaction resume-verify-device "
                "aag-sleep-transaction resume-verify-terminal"
            ),
            "input-lock-protect.service": "input_lock_safety.py",
        }

        def run(argv, **_kwargs):
            unit = argv[2]
            return SimpleNamespace(returncode=0, stdout="LoadState=loaded\n" + good[unit])

        self.assertTrue(compat.stack_ready(run))
        broken = dict(good)
        broken["aag-t700-resume-check.service"] = "aag-sleep-transaction resume-verify-device"

        def bad_run(argv, **_kwargs):
            unit = argv[2]
            return SimpleNamespace(returncode=0, stdout="LoadState=loaded\n" + broken[unit])

        self.assertFalse(compat.stack_ready(bad_run))


if __name__ == "__main__":
    unittest.main()
