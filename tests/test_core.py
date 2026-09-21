from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from locklock_core import (  # noqa: E402
    CapabilityLevel,
    CapabilityReport,
    HotkeyError,
    PolicyAction,
    PolicyEngine,
    ProtocolError,
    SettingsError,
    UserSettings,
    decode_message,
    encode_message,
    load_settings,
    parse_hotkey,
    save_settings,
)


class HotkeyTests(unittest.TestCase):
    def test_canonicalizes_aliases_and_order(self) -> None:
        self.assertEqual(parse_hotkey("alt+control+z").text, "CTRL+ALT+Z")

    def test_rejects_unsafe_shortcut(self) -> None:
        with self.assertRaises(HotkeyError):
            parse_hotkey("CTRL+Z")


class SettingsTests(unittest.TestCase):
    def test_round_trip_is_atomic_and_validated(self) -> None:
        settings = UserSettings(
            default_locked_kinds=("keyboard", "mouse"),
            hide_cursor_enabled=True,
            hide_cursor_seconds=3,
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "settings.json"
            save_settings(path, settings)
            self.assertEqual(load_settings(path), settings)
            self.assertFalse(any(path.parent.glob("*.tmp")))

    def test_rejects_unknown_keys(self) -> None:
        with self.assertRaises(SettingsError):
            UserSettings.from_mapping({"surprise": True})

    def test_rejects_boolean_integer(self) -> None:
        with self.assertRaises(SettingsError):
            UserSettings(idle_lock_seconds=True)  # type: ignore[arg-type]

    def test_allowed_keys_are_validated_and_round_trip(self) -> None:
        settings = UserSettings(allowed_keys=("VOLUMEUP", "A"))
        self.assertEqual(settings.to_mapping()["allowed_keys"], ["VOLUMEUP", "A"])
        self.assertEqual(UserSettings.from_mapping(settings.to_mapping()), settings)
        with self.assertRaises(ValueError):
            UserSettings(allowed_keys=("LEFTCTRL",))


class ProtocolTests(unittest.TestCase):
    def test_round_trip(self) -> None:
        message = {"cmd": "status", "label": "שלום"}
        self.assertEqual(decode_message(encode_message(message)), message)

    def test_rejects_non_object_and_oversize(self) -> None:
        with self.assertRaises(ProtocolError):
            decode_message(json.dumps([1, 2]).encode())
        with self.assertRaises(ProtocolError):
            encode_message({"value": "x" * 20_000})


class CapabilityTests(unittest.TestCase):
    def test_unsupported_kind_fails_before_transition(self) -> None:
        report = CapabilityReport(
            keyboard=CapabilityLevel.VERIFIED,
            mouse=CapabilityLevel.VERIFIED,
            touchpad=CapabilityLevel.VERIFIED,
            touchscreen=CapabilityLevel.UNSUPPORTED,
            cursor_hiding=CapabilityLevel.EXPERIMENTAL,
            lid_control=CapabilityLevel.EXPERIMENTAL,
        )
        with self.assertRaises(RuntimeError):
            report.require_lockable(frozenset({"keyboard", "touchscreen"}))


class PolicyTests(unittest.TestCase):
    def test_repeated_cursor_cycle(self) -> None:
        settings = UserSettings(hide_cursor_enabled=True, hide_cursor_seconds=3)
        policy = PolicyEngine(settings=settings, last_activity=0)
        self.assertEqual(policy.tick(3, is_locked=False), (PolicyAction.HIDE_CURSOR,))
        self.assertEqual(policy.activity(4), (PolicyAction.SHOW_CURSOR,))
        self.assertEqual(policy.tick(7, is_locked=False), (PolicyAction.HIDE_CURSOR,))

    def test_keyboard_activity_does_not_restore_hidden_cursor(self) -> None:
        settings = UserSettings(hide_cursor_enabled=True, hide_cursor_seconds=3)
        policy = PolicyEngine(settings=settings, last_activity=0)
        self.assertEqual(policy.tick(3, is_locked=False), (PolicyAction.HIDE_CURSOR,))
        self.assertEqual(policy.activity(4, pointer=False), ())
        self.assertTrue(policy.cursor_hidden)

    def test_auto_lock_and_unlock_deadline(self) -> None:
        settings = UserSettings(idle_lock_enabled=True, idle_lock_seconds=60)
        policy = PolicyEngine(settings=settings, last_activity=0)
        self.assertEqual(policy.tick(60, is_locked=False), (PolicyAction.LOCK_DEFAULT,))
        policy.locked(60, auto_unlock_seconds=30)
        self.assertEqual(policy.tick(90, is_locked=True), (PolicyAction.UNLOCK_ALL,))


if __name__ == "__main__":
    unittest.main()
