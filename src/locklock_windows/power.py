"""Recoverable Windows lid power-policy operations."""

from __future__ import annotations

import ctypes
import json
import os
import tempfile
import threading
import time
import uuid
from ctypes import wintypes
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol


POWER_BUTTON_SUBGROUP = "4f971e89-eebd-4455-a8de-9e59040e7347"
LID_ACTION_SETTING = "5ca83367-6e45-459f-a27b-476b1d01c936"
LID_ACTION_DO_NOTHING = 0


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]


def _guid(value: str) -> GUID:
    return GUID.from_buffer_copy(uuid.UUID(value).bytes_le)


class PowerPolicyError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class LidPolicySnapshot:
    scheme: str
    ac_value: int
    dc_value: int

    def __post_init__(self) -> None:
        try:
            uuid.UUID(self.scheme)
        except (ValueError, AttributeError) as exc:
            raise PowerPolicyError("journal contains an invalid power scheme") from exc
        for name, value in (("ac_value", self.ac_value), ("dc_value", self.dc_value)):
            if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 3:
                raise PowerPolicyError(f"journal {name} is invalid")


class PowerApi(Protocol):
    def active_scheme(self) -> str: ...

    def read_lid_values(self, scheme: str) -> tuple[int, int]: ...

    def write_lid_values(self, scheme: str, ac_value: int, dc_value: int) -> None: ...


def _save_snapshot(path: Path, snapshot: LidPolicySnapshot) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(asdict(snapshot), handle, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _load_snapshot(path: Path) -> LidPolicySnapshot:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or set(value) != {"scheme", "ac_value", "dc_value"}:
            raise PowerPolicyError("power journal has an unexpected schema")
        return LidPolicySnapshot(**value)
    except (OSError, json.JSONDecodeError, TypeError) as exc:
        raise PowerPolicyError(f"cannot read power journal: {exc}") from exc


class PowerPolicyManager:
    def __init__(self, api: PowerApi, journal_path: Path) -> None:
        self.api = api
        self.journal_path = journal_path
        self.rearm_required = False

    @property
    def pending_restore(self) -> bool:
        return self.journal_path.exists()

    def reconcile_active_scheme(self) -> bool:
        if self.pending_restore and self.api.active_scheme() != _load_snapshot(self.journal_path).scheme:
            self.restore()
            self.rearm_required = True
            return True
        return False

    def apply_do_nothing(self) -> LidPolicySnapshot:
        self.reconcile_active_scheme()
        if self.rearm_required:
            raise PowerPolicyError("The active power plan changed; disable lid-ignore before rearming")
        if self.pending_restore:
            snapshot = _load_snapshot(self.journal_path)
        else:
            scheme = self.api.active_scheme()
            ac_value, dc_value = self.api.read_lid_values(scheme)
            snapshot = LidPolicySnapshot(scheme, ac_value, dc_value)
            _save_snapshot(self.journal_path, snapshot)
        try:
            self.api.write_lid_values(
                snapshot.scheme, LID_ACTION_DO_NOTHING, LID_ACTION_DO_NOTHING
            )
            if self.api.read_lid_values(snapshot.scheme) != (0, 0):
                raise PowerPolicyError("lid override verification failed")
        except BaseException:
            try:
                self.api.write_lid_values(
                    snapshot.scheme, snapshot.ac_value, snapshot.dc_value
                )
                if self.api.read_lid_values(snapshot.scheme) != (snapshot.ac_value, snapshot.dc_value):
                    raise PowerPolicyError("power rollback verification failed")
                self.journal_path.unlink(missing_ok=True)
            except BaseException:
                # Keep the journal so next service start retries recovery.
                pass
            raise
        if self.reconcile_active_scheme():
            raise PowerPolicyError("power plan changed during apply; policy restored")
        return snapshot

    def restore(self) -> bool:
        if not self.pending_restore:
            self.rearm_required = False
            return False
        snapshot = _load_snapshot(self.journal_path)
        self.api.write_lid_values(snapshot.scheme, snapshot.ac_value, snapshot.dc_value)
        if self.api.read_lid_values(snapshot.scheme) != (snapshot.ac_value, snapshot.dc_value):
            raise PowerPolicyError("power restoration verification failed; journal retained")
        self.journal_path.unlink()
        self.rearm_required = False
        return True


class PowerPolicyLease:
    """Restores policy when the interactive agent stops renewing its lease."""

    def __init__(
        self,
        manager: PowerPolicyManager,
        *,
        clock=time.monotonic,
    ) -> None:
        self.manager = manager
        self.clock = clock
        self.deadline: float | None = None
        self._lock = threading.RLock()

    def apply(self, lease_seconds: int) -> None:
        if isinstance(lease_seconds, bool) or not isinstance(lease_seconds, int):
            raise PowerPolicyError("lease_seconds must be an integer")
        if not 5 <= lease_seconds <= 120:
            raise PowerPolicyError("lease_seconds must be between 5 and 120")
        with self._lock:
            try:
                self.manager.apply_do_nothing()
            except BaseException:
                # A partial apply must retain a live retry deadline even if no
                # successful lease was established. No journal means no retry
                # is needed (and a plan-change rearm latch must stay latched).
                self.deadline = self.clock() if self.manager.pending_restore else None
                raise
            self.deadline = self.clock() + lease_seconds

    def restore(self) -> bool:
        with self._lock:
            restored = self.manager.restore()
            self.deadline = None
            return restored

    def tick(self) -> bool:
        with self._lock:
            if self.manager.reconcile_active_scheme():
                self.deadline = None
                return True
            if self.deadline is None or self.clock() < self.deadline:
                return False
            restored = self.manager.restore()
            self.deadline = None
            return restored


class WindowsPowerApi:
    def __init__(self) -> None:
        if os.name != "nt":
            raise OSError("WindowsPowerApi can run only on Windows")
        self.powrprof = ctypes.WinDLL("PowrProf.dll", use_last_error=True)
        self.kernel32 = ctypes.WinDLL("Kernel32.dll", use_last_error=True)
        self._configure()

    def _configure(self) -> None:
        guid_pointer = ctypes.POINTER(GUID)
        self.powrprof.PowerGetActiveScheme.argtypes = [wintypes.HKEY, ctypes.POINTER(guid_pointer)]
        self.powrprof.PowerGetActiveScheme.restype = wintypes.DWORD
        for name in ("PowerReadACValueIndex", "PowerReadDCValueIndex"):
            function = getattr(self.powrprof, name)
            function.argtypes = [
                wintypes.HKEY,
                ctypes.POINTER(GUID),
                ctypes.POINTER(GUID),
                ctypes.POINTER(GUID),
                ctypes.POINTER(wintypes.DWORD),
            ]
            function.restype = wintypes.DWORD
        for name in ("PowerWriteACValueIndex", "PowerWriteDCValueIndex"):
            function = getattr(self.powrprof, name)
            function.argtypes = [
                wintypes.HKEY,
                ctypes.POINTER(GUID),
                ctypes.POINTER(GUID),
                ctypes.POINTER(GUID),
                wintypes.DWORD,
            ]
            function.restype = wintypes.DWORD
        self.powrprof.PowerSetActiveScheme.argtypes = [wintypes.HKEY, ctypes.POINTER(GUID)]
        self.powrprof.PowerSetActiveScheme.restype = wintypes.DWORD
        self.kernel32.LocalFree.argtypes = [wintypes.HLOCAL]
        self.kernel32.LocalFree.restype = wintypes.HLOCAL

    @staticmethod
    def _check(result: int, operation: str) -> None:
        if result != 0:
            raise PowerPolicyError(f"{operation} failed with Windows error {result}")

    def active_scheme(self) -> str:
        pointer = ctypes.POINTER(GUID)()
        self._check(
            self.powrprof.PowerGetActiveScheme(None, ctypes.byref(pointer)),
            "PowerGetActiveScheme",
        )
        try:
            raw = ctypes.string_at(pointer, ctypes.sizeof(GUID))
            return str(uuid.UUID(bytes_le=raw))
        finally:
            self.kernel32.LocalFree(pointer)

    def _read(self, name: str, scheme: GUID, subgroup: GUID, setting: GUID) -> int:
        value = wintypes.DWORD()
        self._check(
            getattr(self.powrprof, name)(
                None,
                ctypes.byref(scheme),
                ctypes.byref(subgroup),
                ctypes.byref(setting),
                ctypes.byref(value),
            ),
            name,
        )
        return int(value.value)

    def read_lid_values(self, scheme: str) -> tuple[int, int]:
        scheme_guid = _guid(scheme)
        subgroup = _guid(POWER_BUTTON_SUBGROUP)
        setting = _guid(LID_ACTION_SETTING)
        return (
            self._read("PowerReadACValueIndex", scheme_guid, subgroup, setting),
            self._read("PowerReadDCValueIndex", scheme_guid, subgroup, setting),
        )

    def write_lid_values(self, scheme: str, ac_value: int, dc_value: int) -> None:
        scheme_guid = _guid(scheme)
        subgroup = _guid(POWER_BUTTON_SUBGROUP)
        setting = _guid(LID_ACTION_SETTING)
        old_ac, old_dc = self.read_lid_values(scheme)
        try:
            self._check(
                self.powrprof.PowerWriteACValueIndex(
                    None,
                    ctypes.byref(scheme_guid),
                    ctypes.byref(subgroup),
                    ctypes.byref(setting),
                    ac_value,
                ),
                "PowerWriteACValueIndex",
            )
            self._check(
                self.powrprof.PowerWriteDCValueIndex(
                    None,
                    ctypes.byref(scheme_guid),
                    ctypes.byref(subgroup),
                    ctypes.byref(setting),
                    dc_value,
                ),
                "PowerWriteDCValueIndex",
            )
            if self.active_scheme() == scheme:
                self._check(
                    self.powrprof.PowerSetActiveScheme(None, ctypes.byref(scheme_guid)),
                    "PowerSetActiveScheme",
                )
        except BaseException:
            # Best-effort transaction rollback. The manager's journal provides
            # the durable second recovery layer if this also fails.
            self.powrprof.PowerWriteACValueIndex(
                None,
                ctypes.byref(scheme_guid),
                ctypes.byref(subgroup),
                ctypes.byref(setting),
                old_ac,
            )
            self.powrprof.PowerWriteDCValueIndex(
                None,
                ctypes.byref(scheme_guid),
                ctypes.byref(subgroup),
                ctypes.byref(setting),
                old_dc,
            )
            if self.active_scheme() == scheme:
                self.powrprof.PowerSetActiveScheme(None, ctypes.byref(scheme_guid))
            raise
