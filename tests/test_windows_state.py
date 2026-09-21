from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from locklock_core import CapabilityLevel, CapabilityReport, UserSettings  # noqa: E402
from locklock_windows.state import AgentController  # noqa: E402
from locklock_windows.input_hooks import (  # noqa: E402
    HookDecisionState,
    VK_LCONTROL,
    VK_LMENU,
    WM_KEYDOWN,
    WM_KEYUP,
)
from locklock_windows.session import (  # noqa: E402
    PBT_APMSUSPEND,
    WM_POWERBROADCAST,
    WM_WTSSESSION_CHANGE,
    WTS_SESSION_LOCK,
    transition_requires_unlock,
)


class FakeBackend:
    def __init__(self, *, touchscreen: CapabilityLevel = CapabilityLevel.UNSUPPORTED):
        self.capabilities = CapabilityReport(
            keyboard=CapabilityLevel.EXPERIMENTAL,
            mouse=CapabilityLevel.EXPERIMENTAL,
            touchpad=CapabilityLevel.EXPERIMENTAL,
            touchscreen=touchscreen,
            cursor_hiding=CapabilityLevel.EXPERIMENTAL,
            lid_control=CapabilityLevel.EXPERIMENTAL,
        )
        self._locked: frozenset[str] = frozenset()
        self.closed = False

    @property
    def locked_kinds(self) -> frozenset[str]:
        return self._locked

    def lock(self, kinds: frozenset[str]) -> frozenset[str]:
        self.capabilities.require_lockable(kinds)
        self._locked |= kinds
        return self._locked

    def unlock(self, kinds: frozenset[str] | None = None) -> frozenset[str]:
        self._locked = frozenset() if kinds is None else self._locked - kinds
        return self._locked

    def close(self) -> None:
        self.closed = True


class AgentControllerTests(unittest.TestCase):
    def controller(self, backend: FakeBackend, settings: UserSettings | None = None):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        controller = AgentController(
            backend,
            settings or UserSettings(default_locked_kinds=("keyboard", "mouse", "touchpad")),
            Path(directory.name) / "settings.json",
        )
        controller.session_changed(True)
        return controller

    def test_toggle_default_is_transactional(self) -> None:
        backend = FakeBackend()
        controller = self.controller(backend)
        self.assertTrue(controller.dispatch({"cmd": "toggle-default"})["ok"])
        self.assertEqual(backend.locked_kinds, {"keyboard", "mouse", "touchpad"})
        self.assertTrue(controller.dispatch({"cmd": "toggle-default"})["ok"])
        self.assertFalse(backend.locked_kinds)

    def test_touchscreen_fails_without_partial_lock(self) -> None:
        backend = FakeBackend()
        controller = self.controller(backend)
        response = controller.dispatch({"cmd": "lock", "mode": "all-input"})
        self.assertFalse(response["ok"])
        self.assertFalse(backend.locked_kinds)

    def test_quit_unlocks_and_closes_backend(self) -> None:
        backend = FakeBackend()
        controller = self.controller(backend)
        controller.dispatch({"cmd": "lock", "mode": "keyboard"})
        response = controller.dispatch({"cmd": "quit"})
        self.assertTrue(response["ok"])
        self.assertFalse(backend.locked_kinds)
        self.assertTrue(backend.closed)

    def test_invalid_settings_do_not_replace_current_settings(self) -> None:
        backend = FakeBackend()
        controller = self.controller(backend)
        response = controller.dispatch(
            {"cmd": "set-settings", "settings": {"idle_lock_seconds": True}}
        )
        self.assertFalse(response["ok"])
        self.assertEqual(controller.settings.idle_lock_seconds, 600)


class HookDecisionTests(unittest.TestCase):
    def test_allowed_key_passes_while_other_keys_are_blocked(self) -> None:
        state = HookDecisionState(
            "CTRL+ALT+Z", "CTRL+ALT+SHIFT+F12", ("VOLUMEUP",)
        )
        state.lock(frozenset({"keyboard"}))
        blocked, _ = state.keyboard_event(ord("A"), WM_KEYDOWN)
        self.assertTrue(blocked)
        state.keyboard_event(ord("A"), WM_KEYUP)
        allowed, _ = state.keyboard_event(0xAF, WM_KEYDOWN)
        self.assertFalse(allowed)
        allowed, _ = state.keyboard_event(0xAF, WM_KEYUP)
        self.assertFalse(allowed)

    def test_primary_action_waits_until_chord_is_released(self) -> None:
        state = HookDecisionState("CTRL+ALT+Z", "CTRL+ALT+SHIFT+F12")
        self.assertEqual(state.keyboard_event(VK_LCONTROL, WM_KEYDOWN), (False, None))
        self.assertEqual(state.keyboard_event(VK_LMENU, WM_KEYDOWN), (False, None))
        self.assertEqual(state.keyboard_event(ord("Z"), WM_KEYDOWN), (True, None))
        self.assertEqual(state.keyboard_event(ord("Z"), WM_KEYUP), (False, None))
        self.assertEqual(state.keyboard_event(VK_LMENU, WM_KEYUP), (False, None))
        self.assertEqual(state.keyboard_event(VK_LCONTROL, WM_KEYUP), (False, "toggle"))

    def test_emergency_action_is_seen_while_keyboard_is_locked(self) -> None:
        state = HookDecisionState("CTRL+ALT+Z", "CTRL+ALT+SHIFT+F12")
        state.lock(frozenset({"keyboard"}))
        for vk in (VK_LCONTROL, VK_LMENU, 0xA0, 0x7B):
            suppress, action = state.keyboard_event(vk, WM_KEYDOWN)
            self.assertTrue(suppress)
            self.assertIsNone(action)
        for vk in (0x7B, 0xA0, VK_LMENU):
            suppress, action = state.keyboard_event(vk, WM_KEYUP)
            self.assertTrue(suppress)
            self.assertIsNone(action)
        suppress, action = state.keyboard_event(VK_LCONTROL, WM_KEYUP)
        self.assertTrue(suppress)
        self.assertEqual(action, "emergency")

    def test_lock_refuses_held_key(self) -> None:
        state = HookDecisionState("CTRL+ALT+Z", "CTRL+ALT+SHIFT+F12")
        state.keyboard_event(ord("A"), WM_KEYDOWN)
        with self.assertRaises(RuntimeError):
            state.lock(frozenset({"keyboard"}))


class SessionTransitionTests(unittest.TestCase):
    def test_suspend_and_session_lock_require_unlock(self) -> None:
        self.assertTrue(transition_requires_unlock(WM_POWERBROADCAST, PBT_APMSUSPEND))
        self.assertTrue(transition_requires_unlock(WM_WTSSESSION_CHANGE, WTS_SESSION_LOCK))
        self.assertFalse(transition_requires_unlock(0x9999, 0))


if __name__ == "__main__":
    unittest.main()
