#!/usr/bin/python3
from __future__ import annotations

import sys
import unittest
from pathlib import Path


SOURCE = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SOURCE))

from input_lock_gnome import hotkey_to_binding  # noqa: E402


class GnomeBindingTests(unittest.TestCase):
    def test_primary_binding(self) -> None:
        self.assertEqual(hotkey_to_binding("CTRL+ALT+Z"), "<Control><Alt>z")

    def test_function_key_binding(self) -> None:
        self.assertEqual(
            hotkey_to_binding("CTRL+ALT+SHIFT+F11"),
            "<Control><Alt><Shift>F11",
        )

    def test_modifier_order_is_canonicalized(self) -> None:
        self.assertEqual(
            hotkey_to_binding("SHIFT+ALT+CTRL+F12"),
            "<Control><Alt><Shift>F12",
        )

    def test_unsafe_shortcut_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            hotkey_to_binding("CTRL+Z")


if __name__ == "__main__":
    unittest.main()
