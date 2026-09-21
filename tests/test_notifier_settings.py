#!/usr/bin/python3
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


SOURCE = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SOURCE))

import input_lock_notifier as notifier_module  # noqa: E402
from input_lock_notifier import TrayNotifier  # noqa: E402


class CursorSettingsTests(unittest.TestCase):
    def test_defaults_when_file_is_absent(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cursor-settings.json"
            with mock.patch.object(notifier_module, "CURSOR_SETTINGS_PATH", path):
                self.assertEqual(
                    TrayNotifier._load_cursor_settings(),
                    {"enabled": False, "seconds": 60},
                )

    def test_settings_are_saved_and_loaded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested/cursor-settings.json"
            with mock.patch.object(notifier_module, "CURSOR_SETTINGS_PATH", path):
                TrayNotifier._save_cursor_settings(True, 125)
                self.assertEqual(
                    TrayNotifier._load_cursor_settings(),
                    {"enabled": True, "seconds": 125},
                )
                self.assertEqual(json.loads(path.read_text())["seconds"], 125)
                self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_invalid_settings_fall_back_safely(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "cursor-settings.json"
            path.write_text('{"enabled": true, "seconds": 0}')
            with mock.patch.object(notifier_module, "CURSOR_SETTINGS_PATH", path):
                self.assertEqual(
                    TrayNotifier._load_cursor_settings(),
                    {"enabled": False, "seconds": 60},
                )


class StartupTests(unittest.TestCase):
    def test_missing_display_exits_cleanly_for_systemd_retry(self) -> None:
        with mock.patch.object(
            notifier_module.Gtk, "init_check", return_value=(False, [])
        ):
            with mock.patch.object(notifier_module, "TrayNotifier") as tray:
                self.assertEqual(notifier_module.main(), 75)
                tray.assert_not_called()

    def test_ready_display_starts_tray(self) -> None:
        with mock.patch.object(
            notifier_module.Gtk, "init_check", return_value=(True, [])
        ):
            with mock.patch.object(notifier_module, "TrayNotifier") as tray:
                tray.return_value.run.return_value = 0
                self.assertEqual(notifier_module.main(), 0)
                tray.return_value.run.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()

class ExplicitActionTests(unittest.TestCase):
    def test_queued_unlock_does_not_change_into_lock_after_state_change(self):
        tray = TrayNotifier.__new__(TrayNotifier)
        tray.current_state = {'locked_kinds': []}
        tray.config = mock.Mock()
        with mock.patch.object(notifier_module, 'send_request', return_value={'ok':True}) as send:
            tray._toggle_worker(True)
        self.assertEqual(send.call_args.args[0], {'cmd':'emergency-unlock'})

    def test_lid_worker_uses_captured_generation(self):
        tray = TrayNotifier.__new__(TrayNotifier)
        tray.current_state = {'lid_generation': 999}
        tray.config = mock.Mock()
        with mock.patch.object(notifier_module, 'send_request', return_value={'ok':True}) as send:
            tray._lid_toggle_worker(True, 123)
        self.assertEqual(send.call_args.args[0]['generation'],123)
