#!/usr/bin/python3
"""Tests for the reversible GNOME/UPower lid no-suspend policy."""

from __future__ import annotations

import tempfile
import json
from unittest.mock import Mock
import unittest
from pathlib import Path

from input_lock_lid_policy import (
    GNOME_POLICY_VALUES,
    LidNoSuspendPolicy,
    PolicyError,
    UPOWER_DROPIN_CONTENT,
    UPowerPolicyController,
)


class MemorySettings:
    def __init__(self) -> None:
        self.values: dict[str, object] = {
            "lid-close-ac-action": "suspend",
            "lid-close-battery-action": "suspend",
            "sleep-inactive-ac-type": "nothing",
            "sleep-inactive-battery-type": "suspend",
            "sleep-inactive-ac-timeout": 3600,
            "sleep-inactive-battery-timeout": 900,
            "lid-close-suspend-with-external-monitor": False,
        }
        self.sync_count = 0

    def get(self, key: str) -> object:
        return self.values[key]

    def set(self, key: str, value: object) -> None:
        self.values[key] = value

    def sync(self) -> None:
        self.sync_count += 1


class LidNoSuspendPolicyTests(unittest.TestCase):
    def test_legacy_user_restoration_is_verified(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = MemorySettings()
            original = dict(settings.values)
            backup = Path(directory) / "policy.json"
            backup.write_text(json.dumps({"version":1,"values": original}))
            settings.values.update(GNOME_POLICY_VALUES)
            helper = Mock(return_value={"normal_os_policy": True})
            policy = LidNoSuspendPolicy(settings, backup_path=backup, helper=helper)
            policy.disable()
            self.assertEqual(settings.values, original)
            self.assertFalse(backup.exists())
            self.assertNotIn("enable", repr(helper.call_args_list))

    def test_root_failure_retains_journal_but_still_restores_user(self):
        with tempfile.TemporaryDirectory() as directory:
            settings = MemorySettings()
            original = dict(settings.values)
            backup = Path(directory)/"policy.json"
            backup.write_text(json.dumps({"version":1,"values":original}))
            settings.values.update(GNOME_POLICY_VALUES)
            policy = LidNoSuspendPolicy(settings, backup_path=backup, helper=Mock(side_effect=PolicyError("failed")))
            with self.assertRaises(PolicyError):
                policy.disable()
            self.assertEqual(settings.values, original)
            self.assertTrue(backup.exists())

    def test_enable_is_rejected_without_changes(self):
        settings = MemorySettings()
        helper = Mock()
        with self.assertRaises(PolicyError):
            LidNoSuspendPolicy(settings, helper=helper).enable()
        helper.assert_not_called()
        self.assertEqual(settings.sync_count, 0)


class UPowerPolicyControllerTests(unittest.TestCase):
    def test_runtime_failure_retains_durable_retry_after_dropin_removed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root/"UPower.conf"
            config.write_text("[UPower]\nCriticalPowerAction=PowerOff\n")
            restart = Mock()
            runtime = Mock(return_value="Ignore")
            controller = UPowerPolicyController(config_path=config, dropin_dir=root, restart=restart,
                                               service_active=lambda:True, runtime_action=runtime)
            controller.dropin_path.write_text(UPOWER_DROPIN_CONTENT)
            with self.assertRaises(PolicyError):
                controller.disable()
            self.assertFalse(controller.dropin_path.exists())
            self.assertTrue((root/".input-lock-restore-pending.json").exists())
            runtime.return_value = "PowerOff"
            self.assertTrue(controller.disable()["normal_os_policy"])
            self.assertEqual(restart.call_count, 2)
            self.assertFalse((root/".input-lock-restore-pending.json").exists())
            controller.disable()
            self.assertEqual(restart.call_count, 2)

    def test_unmanaged_dropin_is_retained(self):
        with tempfile.TemporaryDirectory() as directory:
            controller = UPowerPolicyController(config_path=Path(directory)/"base", dropin_dir=Path(directory))
            controller.dropin_path.write_text("# administrator custom content")
            with self.assertRaises(PolicyError):
                controller.disable()
            self.assertTrue(controller.dropin_path.exists())


if __name__ == "__main__":
    unittest.main()
