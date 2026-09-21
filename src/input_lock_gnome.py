#!/usr/bin/python3
"""Install/remove the two GNOME fallback keybindings without losing others."""

from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
from typing import Final


ROOT_SCHEMA: Final = "org.gnome.settings-daemon.plugins.media-keys"
KEY: Final = "custom-keybindings"
PRIMARY_PATH: Final = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/input-lock/"
EMERGENCY_PATH: Final = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/input-lock-emergency/"
OWN_PATHS: Final = (PRIMARY_PATH, EMERGENCY_PATH)
PRIMARY_BINDING: Final = "<Control><Alt>z"
EMERGENCY_BINDING: Final = "<Control><Alt><Shift>F12"


def run(*arguments: str) -> str:
    result = subprocess.run(
        ["gsettings", *arguments],
        check=False,
        capture_output=True,
        text=True,
        timeout=8,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "gsettings failed")
    return result.stdout.strip()


def schema(path: str) -> str:
    return f"org.gnome.settings-daemon.plugins.media-keys.custom-keybinding:{path}"


def quote(value: str) -> str:
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def parse_paths(value: str) -> list[str]:
    from gi.repository import GLib

    parsed = GLib.Variant.parse(GLib.VariantType.new("as"), value, None, None).unpack()
    if not isinstance(parsed, list) or not all(isinstance(item, str) for item in parsed):
        raise RuntimeError("GNOME custom-keybindings has an unexpected value")
    return parsed


def paths() -> list[str]:
    return parse_paths(run("get", ROOT_SCHEMA, KEY))


def binding_for(path: str) -> str:
    value = run("get", schema(path), "binding")
    parsed = ast.literal_eval(value)
    return str(parsed)


def hotkey_to_binding(hotkey: str) -> str:
    aliases = {"CONTROL": "CTRL", "META": "SUPER"}
    tokens = [aliases.get(token.strip().upper(), token.strip().upper()) for token in hotkey.split("+") if token.strip()]
    modifiers = {"CTRL": "<Control>", "ALT": "<Alt>", "SHIFT": "<Shift>", "SUPER": "<Super>"}
    selected_modifiers: list[str] = []
    keys: list[str] = []
    for token in tokens:
        if token in modifiers:
            if token not in selected_modifiers:
                selected_modifiers.append(token)
        else:
            keys.append(token.removeprefix("KEY_"))
    if len(selected_modifiers) < 2 or len(keys) != 1:
        raise ValueError("shortcut must contain at least two modifiers and one key")
    key = keys[0]
    if len(key) == 1 and key.isalnum():
        key = key.lower()
    elif not re.fullmatch(r"F(?:[1-9]|1[0-2])", key):
        raise ValueError("shortcut key must be A-Z, 0-9, or F1-F12")
    order = ("CTRL", "ALT", "SHIFT", "SUPER")
    return "".join(modifiers[name] for name in order if name in selected_modifiers) + key


def daemon_primary_hotkey() -> str:
    result = subprocess.run(
        ["/usr/bin/input-lock", "status", "--json"],
        check=False,
        capture_output=True,
        text=True,
        timeout=4,
    )
    if result.returncode != 0:
        return "CTRL+ALT+Z"
    payload = json.loads(result.stdout)
    value = payload.get("primary_hotkey")
    return str(value) if isinstance(value, str) else "CTRL+ALT+Z"


def find_collisions(primary_binding: str = PRIMARY_BINDING) -> list[tuple[str, str]]:
    collisions: list[tuple[str, str]] = []
    for path in paths():
        if path in OWN_PATHS:
            continue
        try:
            binding = binding_for(path)
        except Exception:
            continue
        if binding in {primary_binding, EMERGENCY_BINDING}:
            collisions.append((path, binding))
    return collisions


def check(primary_binding: str = PRIMARY_BINDING) -> int:
    collisions = find_collisions(primary_binding)
    if collisions:
        for path, binding in collisions:
            print(f"Collision: {binding} is already assigned at {path}", file=sys.stderr)
        return 2
    return 0


def install() -> int:
    primary_binding = hotkey_to_binding(daemon_primary_hotkey())
    if check(primary_binding) != 0:
        return 2
    current = paths()
    updated = current + [path for path in OWN_PATHS if path not in current]
    run("set", ROOT_SCHEMA, KEY, repr(updated))
    values = (
        (
            PRIMARY_PATH,
            "Input Lock — toggle keyboard and mouse",
            "/usr/bin/input-lock gnome-hotkey",
            primary_binding,
        ),
        (
            EMERGENCY_PATH,
            "Input Lock — emergency unlock",
            "/usr/bin/input-lock gnome-emergency",
            EMERGENCY_BINDING,
        ),
    )
    for path, name, command, binding in values:
        run("set", schema(path), "name", quote(name))
        run("set", schema(path), "command", quote(command))
        run("set", schema(path), "binding", quote(binding))
    print("GNOME fallback shortcuts installed.")
    return 0


def set_primary(hotkey: str) -> int:
    binding = hotkey_to_binding(hotkey)
    if binding == EMERGENCY_BINDING:
        raise ValueError("the primary shortcut must differ from the emergency shortcut")
    if check(binding) != 0:
        return 2
    run("set", schema(PRIMARY_PATH), "binding", quote(binding))
    print(f"GNOME primary shortcut set to {binding}.")
    return 0


def remove() -> int:
    current = paths()
    updated = [path for path in current if path not in OWN_PATHS]
    run("set", ROOT_SCHEMA, KEY, repr(updated))
    for path in OWN_PATHS:
        for key in ("name", "command", "binding"):
            try:
                run("reset", schema(path), key)
            except Exception:
                pass
    print("GNOME fallback shortcuts removed.")
    return 0


def status() -> int:
    current = paths()
    found = 0
    for path in OWN_PATHS:
        if path in current:
            print(f"{path}: {binding_for(path)}")
            found += 1
        else:
            print(f"{path}: missing")
    return 0 if found == len(OWN_PATHS) else 1


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "action", choices=("check", "install", "remove", "status", "set-primary")
    )
    parser.add_argument("hotkey", nargs="?")
    args = parser.parse_args()
    try:
        if args.action == "set-primary":
            if not args.hotkey:
                parser.error("set-primary requires HOTKEY")
            return set_primary(args.hotkey)
        return {"check": check, "install": install, "remove": remove, "status": status}[args.action]()
    except Exception as exc:
        print(f"GNOME shortcut operation failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
