"""Validated, atomically persisted user settings shared across platforms."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final, Mapping

from .allowed_keys import validate_allowed_keys
from .hotkeys import parse_hotkey


DEVICE_KINDS: Final = frozenset({"keyboard", "mouse", "touchpad", "touchscreen"})
LOCK_MODES: Final = frozenset(
    {"all", "all-input", "keyboard", "mouse", "touchpad", "touchscreen"}
)


class SettingsError(ValueError):
    """Raised when persisted settings are invalid."""


def _integer(value: object, name: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise SettingsError(f"{name} must be an integer")
    if not minimum <= value <= maximum:
        raise SettingsError(f"{name} must be between {minimum} and {maximum}")
    return value


def _boolean(value: object, name: str) -> bool:
    if not isinstance(value, bool):
        raise SettingsError(f"{name} must be a boolean")
    return value


@dataclass(frozen=True, slots=True)
class UserSettings:
    schema_version: int = 1
    default_locked_kinds: tuple[str, ...] = (
        "keyboard",
        "mouse",
        "touchpad",
        "touchscreen",
    )
    primary_hotkey: str = "CTRL+ALT+Z"
    emergency_hotkey: str = "CTRL+ALT+SHIFT+F12"
    idle_lock_enabled: bool = False
    idle_lock_seconds: int = 600
    hide_cursor_enabled: bool = False
    hide_cursor_seconds: int = 60
    start_at_login: bool = True
    ignore_lid_close: bool = False
    lid_power_policy_enabled: bool = False
    lid_battery_threshold: int = 20
    allowed_keys: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _integer(self.schema_version, "schema_version", 1, 1)
        kinds = self.default_locked_kinds
        if not isinstance(kinds, tuple) or not kinds:
            raise SettingsError("default_locked_kinds must be a non-empty tuple")
        if len(kinds) != len(set(kinds)) or any(kind not in DEVICE_KINDS for kind in kinds):
            raise SettingsError("default_locked_kinds contains an unknown or duplicate kind")
        try:
            primary = parse_hotkey(self.primary_hotkey).text
            emergency = parse_hotkey(self.emergency_hotkey).text
        except ValueError as exc:
            raise SettingsError(str(exc)) from exc
        if primary != self.primary_hotkey or emergency != self.emergency_hotkey:
            raise SettingsError("hotkeys must use canonical spelling and modifier order")
        if primary == emergency:
            raise SettingsError("primary and emergency shortcuts must be different")
        for name in (
            "idle_lock_enabled",
            "hide_cursor_enabled",
            "start_at_login",
            "ignore_lid_close",
            "lid_power_policy_enabled",
        ):
            _boolean(getattr(self, name), name)
        _integer(self.idle_lock_seconds, "idle_lock_seconds", 60, 86_400)
        _integer(self.hide_cursor_seconds, "hide_cursor_seconds", 1, 86_399)
        _integer(self.lid_battery_threshold, "lid_battery_threshold", 1, 99)
        if validate_allowed_keys(self.allowed_keys) != self.allowed_keys:
            raise SettingsError("allowed_keys must be unique canonical key names")

    @classmethod
    def from_mapping(cls, values: Mapping[str, object]) -> "UserSettings":
        if not isinstance(values, Mapping):
            raise SettingsError("settings root must be an object")
        known = {field.name for field in __import__("dataclasses").fields(cls)}
        unknown = sorted(set(values) - known)
        if unknown:
            raise SettingsError("unknown settings: " + ", ".join(unknown))
        converted = dict(values)
        kinds = converted.get("default_locked_kinds")
        if isinstance(kinds, list):
            converted["default_locked_kinds"] = tuple(kinds)
        allowed_keys = converted.get("allowed_keys")
        if isinstance(allowed_keys, list):
            converted["allowed_keys"] = tuple(allowed_keys)
        try:
            return cls(**converted)
        except TypeError as exc:
            raise SettingsError(str(exc)) from exc

    def to_mapping(self) -> dict[str, object]:
        payload = asdict(self)
        payload["default_locked_kinds"] = list(self.default_locked_kinds)
        payload["allowed_keys"] = list(self.allowed_keys)
        return payload


def load_settings(path: Path) -> UserSettings:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SettingsError(f"cannot read settings: {exc}") from exc
    return UserSettings.from_mapping(value)


def save_settings(path: Path, settings: UserSettings) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(settings.to_mapping(), handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.chmod(temporary_name, 0o600)
        except OSError:
            # Windows ACLs, not POSIX modes, are authoritative there.
            pass
        os.replace(temporary_name, path)
    except BaseException:
        try:
            os.unlink(temporary_name)
        except OSError:
            pass
        raise
