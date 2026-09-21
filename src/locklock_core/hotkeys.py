"""Portable hotkey parsing and canonicalization."""

from __future__ import annotations

import re
from dataclasses import dataclass


_MODIFIER_ORDER = ("CTRL", "ALT", "SHIFT", "SUPER")
_ALIASES = {"CONTROL": "CTRL", "META": "SUPER", "WIN": "SUPER"}
_KEY_PATTERN = re.compile(r"(?:[A-Z0-9]|F(?:[1-9]|1[0-2]))\Z")


class HotkeyError(ValueError):
    """Raised when a shortcut cannot be represented safely."""


@dataclass(frozen=True, slots=True)
class Hotkey:
    modifiers: tuple[str, ...]
    key: str

    @property
    def text(self) -> str:
        return "+".join((*self.modifiers, self.key))


def parse_hotkey(value: str, *, minimum_modifiers: int = 2) -> Hotkey:
    if not isinstance(value, str):
        raise HotkeyError("shortcut must be text")
    raw = [part.strip().upper() for part in value.split("+") if part.strip()]
    tokens = [_ALIASES.get(part, part).removeprefix("KEY_") for part in raw]
    if len(tokens) != len(set(tokens)):
        raise HotkeyError("shortcut contains a duplicate key")
    modifiers = tuple(name for name in _MODIFIER_ORDER if name in tokens)
    keys = [token for token in tokens if token not in _MODIFIER_ORDER]
    if len(modifiers) < minimum_modifiers:
        raise HotkeyError(f"shortcut requires at least {minimum_modifiers} modifiers")
    if len(keys) != 1 or not _KEY_PATTERN.fullmatch(keys[0]):
        raise HotkeyError("shortcut key must be A-Z, 0-9, or F1-F12")
    if len(tokens) != len(modifiers) + 1:
        raise HotkeyError("shortcut contains an unsupported modifier")
    return Hotkey(modifiers=modifiers, key=keys[0])
