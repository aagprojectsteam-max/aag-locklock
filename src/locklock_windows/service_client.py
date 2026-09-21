"""User-agent client for the optional Windows power helper service."""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes

from locklock_core import UserSettings
from locklock_windows.ipc import send_request
from locklock_windows.paths import pipe_name_for_sid


class SYSTEM_POWER_STATUS(ctypes.Structure):
    _fields_ = [
        ("ACLineStatus", ctypes.c_ubyte),
        ("BatteryFlag", ctypes.c_ubyte),
        ("BatteryLifePercent", ctypes.c_ubyte),
        ("SystemStatusFlag", ctypes.c_ubyte),
        ("BatteryLifeTime", wintypes.DWORD),
        ("BatteryFullLifeTime", wintypes.DWORD),
    ]


class PowerServiceClient:
    def __init__(self, authorized_sid: str) -> None:
        self.pipe_name = pipe_name_for_sid(authorized_sid, service=True)
        self._last_apply: bool | None = None
        self.last_error = ""

    @staticmethod
    def power_status() -> tuple[bool, int | None]:
        if os.name != "nt":
            raise OSError("Windows power status is available only on Windows")
        status = SYSTEM_POWER_STATUS()
        if not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(status)):
            raise ctypes.WinError()
        percentage = None if status.BatteryLifePercent == 255 else int(status.BatteryLifePercent)
        return status.ACLineStatus == 1, percentage

    def sync(self, settings: UserSettings, *, force: bool = False) -> None:
        on_ac, percentage = self.power_status()
        above_threshold = percentage is not None and percentage > settings.lid_battery_threshold
        should_apply = (
            settings.ignore_lid_close
            and settings.lid_power_policy_enabled
            and (on_ac or above_threshold)
        )
        if not force and not should_apply and should_apply == self._last_apply:
            return
        command = "apply-lid-do-nothing" if should_apply else "restore-lid"
        request: dict[str, object] = {"cmd": command}
        if should_apply:
            request["lease_seconds"] = 45
        try:
            try:
                response = send_request(self.pipe_name, request, timeout_ms=1500)
            except Exception:
                self._start_service()
                response = send_request(self.pipe_name, request, timeout_ms=5000)
            if response.get("ok") is not True:
                raise RuntimeError(str(response.get("error", "power service rejected command")))
            self._last_apply = should_apply
            self.last_error = ""
        except Exception as exc:
            self.last_error = str(exc)
            # Normal Windows power policy remains authoritative when applying
            # fails. A failed restore is retried by the service journal at start.
            if should_apply:
                self._last_apply = False
            raise

    @staticmethod
    def _start_service() -> None:
        import pywintypes
        import win32serviceutil

        try:
            win32serviceutil.StartService("AAGLockLock")
        except pywintypes.error as exc:
            if exc.winerror != 1056:  # ERROR_SERVICE_ALREADY_RUNNING
                raise
        win32serviceutil.WaitForServiceStatus(
            "AAGLockLock", 4, 10  # SERVICE_RUNNING, timeout seconds
        )

    def restore_and_stop(self) -> None:
        try:
            try:
                send_request(self.pipe_name, {"cmd": "restore-lid"}, timeout_ms=1500)
            except Exception:
                self._start_service()
                send_request(self.pipe_name, {"cmd": "restore-lid"}, timeout_ms=5000)
        finally:
            try:
                send_request(self.pipe_name, {"cmd": "shutdown"}, timeout_ms=1500)
            except Exception:
                pass
