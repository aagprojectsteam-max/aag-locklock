from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from locklock_windows.power import PowerPolicyLease, PowerPolicyManager  # noqa: E402


SCHEME = "381b4222-f694-41f0-9685-ff5bb260df2e"


class FakePowerApi:
    def __init__(self) -> None:
        self.values = (1, 2)
        self.fail_writes = 0

    def active_scheme(self) -> str:
        return SCHEME

    def read_lid_values(self, scheme: str) -> tuple[int, int]:
        self.assert_scheme(scheme)
        return self.values

    def write_lid_values(self, scheme: str, ac_value: int, dc_value: int) -> None:
        self.assert_scheme(scheme)
        if self.fail_writes:
            self.fail_writes -= 1
            raise RuntimeError("simulated power write failure")
        self.values = (ac_value, dc_value)

    @staticmethod
    def assert_scheme(scheme: str) -> None:
        if scheme != SCHEME:
            raise AssertionError(scheme)


class PowerPolicyManagerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "power-restore.json"
        self.api = FakePowerApi()
        self.manager = PowerPolicyManager(self.api, self.path)

    def test_apply_journals_before_change_and_restore_removes_journal(self) -> None:
        self.manager.apply_do_nothing()
        self.assertEqual(self.api.values, (0, 0))
        self.assertTrue(self.path.exists())
        self.manager.restore()
        self.assertEqual(self.api.values, (1, 2))
        self.assertFalse(self.path.exists())

    def test_expired_agent_lease_restores_policy(self) -> None:
        now = [100.0]
        lease = PowerPolicyLease(self.manager, clock=lambda: now[0])
        lease.apply(45)
        self.assertEqual(self.api.values, (0, 0))
        now[0] = 144.9
        self.assertFalse(lease.tick())
        now[0] = 145.0
        self.assertTrue(lease.tick())
        self.assertEqual(self.api.values, (1, 2))
        self.assertFalse(self.path.exists())

    def test_new_manager_recovers_after_simulated_crash(self) -> None:
        self.manager.apply_do_nothing()
        recovered = PowerPolicyManager(self.api, self.path)
        self.assertTrue(recovered.restore())
        self.assertEqual(self.api.values, (1, 2))

    def test_failed_apply_rolls_back_and_clears_journal_if_recovery_succeeds(self) -> None:
        self.api.fail_writes = 1
        with self.assertRaises(RuntimeError):
            self.manager.apply_do_nothing()
        self.assertEqual(self.api.values, (1, 2))
        self.assertFalse(self.path.exists())

    def test_failed_restore_keeps_journal_for_next_start(self) -> None:
        self.manager.apply_do_nothing()
        self.api.fail_writes = 1
        with self.assertRaises(RuntimeError):
            self.manager.restore()
        self.assertTrue(self.path.exists())


if __name__ == "__main__":
    unittest.main()
