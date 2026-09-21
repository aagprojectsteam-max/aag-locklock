"""Portable names for individual keys that may bypass keyboard locking."""

from __future__ import annotations

from typing import Final


# Canonical name: (friendly label, Linux evdev name, Windows virtual-key code).
ALLOWED_KEY_CATALOG: Final[dict[str, tuple[str, str, int]]] = {
    **{chr(code): (chr(code), f"KEY_{chr(code)}", code) for code in range(65, 91)},
    **{str(number): (str(number), f"KEY_{number}", 0x30 + number) for number in range(10)},
    **{f"F{n}": (f"F{n}", f"KEY_F{n}", 0x6F + n) for n in range(1, 25)},
    "ESC": ("Escape", "KEY_ESC", 0x1B),
    "TAB": ("Tab", "KEY_TAB", 0x09),
    "SPACE": ("Space", "KEY_SPACE", 0x20),
    "ENTER": ("Enter", "KEY_ENTER", 0x0D),
    "BACKSPACE": ("Backspace", "KEY_BACKSPACE", 0x08),
    "DELETE": ("Delete", "KEY_DELETE", 0x2E),
    "INSERT": ("Insert", "KEY_INSERT", 0x2D),
    "HOME": ("Home", "KEY_HOME", 0x24),
    "END": ("End", "KEY_END", 0x23),
    "PAGEUP": ("Page Up", "KEY_PAGEUP", 0x21),
    "PAGEDOWN": ("Page Down", "KEY_PAGEDOWN", 0x22),
    "LEFT": ("Left Arrow", "KEY_LEFT", 0x25),
    "UP": ("Up Arrow", "KEY_UP", 0x26),
    "RIGHT": ("Right Arrow", "KEY_RIGHT", 0x27),
    "DOWN": ("Down Arrow", "KEY_DOWN", 0x28),
    "VOLUMEUP": ("Volume Up", "KEY_VOLUMEUP", 0xAF),
    "VOLUMEDOWN": ("Volume Down", "KEY_VOLUMEDOWN", 0xAE),
    "MUTE": ("Mute", "KEY_MUTE", 0xAD),
    "PLAYPAUSE": ("Play / Pause", "KEY_PLAYPAUSE", 0xB3),
    "NEXTSONG": ("Next Track", "KEY_NEXTSONG", 0xB0),
    "PREVIOUSSONG": ("Previous Track", "KEY_PREVIOUSSONG", 0xB1),
    "STOPCD": ("Stop Media", "KEY_STOPCD", 0xB2),
    # Current Copilot keyboards report a synthetic Super+Shift+F23 chord.
    "COPILOT": ("Copilot / Assistant", "KEY_F23", 0x86),
}

GTK_KEY_ALIASES: Final[dict[str, str]] = {
    "ESCAPE": "ESC", "RETURN": "ENTER", "KP_ENTER": "ENTER",
    "PAGE_UP": "PAGEUP", "PAGE_DOWN": "PAGEDOWN",
    "XF86AUDIORAISEVOLUME": "VOLUMEUP", "XF86AUDIOLOWERVOLUME": "VOLUMEDOWN",
    "XF86AUDIOMUTE": "MUTE", "XF86AUDIOPLAY": "PLAYPAUSE",
    "XF86AUDIONEXT": "NEXTSONG", "XF86AUDIOPREV": "PREVIOUSSONG",
    "XF86AUDIOSTOP": "STOPCD",
    "XF86ASSISTANT": "COPILOT", "XF86COPILOT": "COPILOT",
    "XF86TOUCHPADOFF": "COPILOT",
}


def validate_allowed_keys(value: object) -> tuple[str, ...]:
    if not isinstance(value, (list, tuple)):
        raise ValueError("allowed_keys must be a list")
    if len(value) > 128:
        raise ValueError("no more than 128 allowed keys may be configured")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str):
            raise ValueError("every allowed key must be a string")
        canonical = item.strip().upper()
        if canonical not in ALLOWED_KEY_CATALOG:
            raise ValueError(f"unsupported allowed key: {item}")
        if canonical not in result:
            result.append(canonical)
    return tuple(result)


def display_key(name: str) -> str:
    return ALLOWED_KEY_CATALOG[name][0]


def gtk_key_to_canonical(name: str) -> str | None:
    upper = name.upper()
    candidate = GTK_KEY_ALIASES.get(upper, upper)
    return candidate if candidate in ALLOWED_KEY_CATALOG else None
