"""Windows paths and per-user pipe names."""

from __future__ import annotations

import os
from pathlib import Path


PRODUCT_DIRECTORY = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local")) / "AAG" / "LockLock"
SETTINGS_PATH = PRODUCT_DIRECTORY / "settings.json"
PROGRAM_DATA_DIRECTORY = Path(os.environ.get("PROGRAMDATA", "C:/ProgramData")) / "AAG" / "LockLock"
SERVICE_CONFIG_PATH = PROGRAM_DATA_DIRECTORY / "service.json"
POWER_JOURNAL_PATH = PROGRAM_DATA_DIRECTORY / "power-restore.json"


def pipe_name_for_sid(sid: str, *, service: bool = False) -> str:
    safe_sid = "".join(character if character.isalnum() or character == "-" else "_" for character in sid)
    suffix = "service" if service else "agent"
    return rf"\\.\pipe\AAG-LockLock-{suffix}-{safe_sid}"
