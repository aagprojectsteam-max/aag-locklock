"""Per-user Windows startup registration."""

from __future__ import annotations

import os
import subprocess
import sys


RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
VALUE_NAME = "AAG LockLock"


def startup_command() -> str:
    if getattr(sys, "frozen", False):
        arguments = [sys.executable]
    else:
        arguments = [sys.executable, "-m", "locklock_windows.agent"]
    return subprocess.list2cmdline(arguments)


def is_enabled() -> bool:
    if os.name != "nt":
        return False
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as key:
            value, _kind = winreg.QueryValueEx(key, VALUE_NAME)
            return value == startup_command()
    except FileNotFoundError:
        return False


def set_enabled(enabled: bool) -> None:
    if os.name != "nt":
        raise OSError("Windows startup settings can run only on Windows")
    import winreg

    with winreg.CreateKeyEx(
        winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_QUERY_VALUE | winreg.KEY_SET_VALUE
    ) as key:
        if enabled:
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, startup_command())
        else:
            try:
                winreg.DeleteValue(key, VALUE_NAME)
            except FileNotFoundError:
                pass
