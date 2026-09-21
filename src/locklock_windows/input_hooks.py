"""Documented Win32 low-level keyboard/mouse hook backend."""

from __future__ import annotations

import ctypes
import queue
import sys
import threading
from ctypes import wintypes
from typing import Callable

from locklock_core import ALLOWED_KEY_CATALOG, CapabilityLevel, CapabilityReport, parse_hotkey


WH_KEYBOARD_LL = 13
WH_MOUSE_LL = 14
HC_ACTION = 0
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105
WM_QUIT = 0x0012

VK_SHIFT = 0x10
VK_CONTROL = 0x11
VK_MENU = 0x12
VK_LWIN = 0x5B
VK_RWIN = 0x5C
VK_LSHIFT = 0xA0
VK_RSHIFT = 0xA1
VK_LCONTROL = 0xA2
VK_RCONTROL = 0xA3
VK_LMENU = 0xA4
VK_RMENU = 0xA5

MOUSE_DOWN_MESSAGES = {0x0201, 0x0204, 0x0207, 0x020B}
MOUSE_UP_MESSAGES = {0x0202, 0x0205, 0x0208, 0x020C}

_CALLBACK = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)
LRESULT = ctypes.c_ssize_t
HOOKPROC = _CALLBACK(LRESULT, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


class WindowsHookError(RuntimeError):
    pass


def _hotkey_groups(text: str) -> tuple[tuple[frozenset[int], ...], int]:
    hotkey = parse_hotkey(text)
    groups: list[frozenset[int]] = []
    values = {
        "CTRL": frozenset({VK_CONTROL, VK_LCONTROL, VK_RCONTROL}),
        "ALT": frozenset({VK_MENU, VK_LMENU, VK_RMENU}),
        "SHIFT": frozenset({VK_SHIFT, VK_LSHIFT, VK_RSHIFT}),
        "SUPER": frozenset({VK_LWIN, VK_RWIN}),
    }
    for modifier in hotkey.modifiers:
        groups.append(values[modifier])
    if len(hotkey.key) == 1:
        key = ord(hotkey.key)
    else:
        key = 0x70 + int(hotkey.key[1:]) - 1
    return tuple(groups), key


class HookDecisionState:
    """Pure, locked state machine used by the native hook callbacks."""

    def __init__(self, primary_hotkey: str, emergency_hotkey: str, allowed_keys: tuple[str, ...] = ()) -> None:
        self._lock = threading.RLock()
        self._locked_kinds: frozenset[str] = frozenset()
        self._pressed_keys: set[int] = set()
        self._mouse_buttons = 0
        self._pending_primary = False
        self._pending_emergency = False
        self.update_hotkeys(primary_hotkey, emergency_hotkey)
        self.update_allowed_keys(allowed_keys)

    @property
    def locked_kinds(self) -> frozenset[str]:
        with self._lock:
            return self._locked_kinds

    def update_hotkeys(self, primary: str, emergency: str) -> None:
        primary_groups, primary_key = _hotkey_groups(primary)
        emergency_groups, emergency_key = _hotkey_groups(emergency)
        if primary_key == 0x7B:  # F12 is reserved by Windows for debuggers.
            raise ValueError("F12 cannot be the Windows primary shortcut")
        with self._lock:
            self._primary_groups, self._primary_key = primary_groups, primary_key
            self._emergency_groups, self._emergency_key = emergency_groups, emergency_key
            self._emergency_release = frozenset({emergency_key}).union(*emergency_groups)
            self._primary_release = frozenset({primary_key}).union(*primary_groups)

    def update_allowed_keys(self, keys: tuple[str, ...]) -> None:
        with self._lock:
            self._allowed_vks = frozenset(ALLOWED_KEY_CATALOG[key][2] for key in keys)

    def lock(self, kinds: frozenset[str]) -> frozenset[str]:
        WindowsInputHooks.capabilities.require_lockable(kinds)
        with self._lock:
            if "keyboard" in kinds and self._pressed_keys:
                raise WindowsHookError("release all keyboard keys before locking")
            if kinds & {"mouse", "touchpad"} and self._mouse_buttons:
                raise WindowsHookError("release all mouse buttons before locking")
            self._locked_kinds = frozenset(self._locked_kinds | kinds)
            return self._locked_kinds

    def unlock(self, kinds: frozenset[str] | None = None) -> frozenset[str]:
        with self._lock:
            self._locked_kinds = (
                frozenset() if kinds is None else frozenset(self._locked_kinds - kinds)
            )
            return self._locked_kinds

    @staticmethod
    def _matches(
        pressed: set[int], groups: tuple[frozenset[int], ...], key: int
    ) -> bool:
        return key in pressed and all(group & pressed for group in groups)

    def keyboard_event(self, vk: int, message: int) -> tuple[bool, str | None]:
        down = message in {WM_KEYDOWN, WM_SYSKEYDOWN}
        up = message in {WM_KEYUP, WM_SYSKEYUP}
        action: str | None = None
        suppress_trigger = False
        with self._lock:
            if down:
                self._pressed_keys.add(vk)
            elif up:
                self._pressed_keys.discard(vk)
            if self._matches(self._pressed_keys, self._emergency_groups, self._emergency_key):
                self._pending_emergency = True
                suppress_trigger = True
            if self._matches(self._pressed_keys, self._primary_groups, self._primary_key):
                self._pending_primary = True
                suppress_trigger = True
            if self._pending_emergency and not self._pressed_keys & self._emergency_release:
                self._pending_emergency = False
                self._pending_primary = False
                action = "emergency"
            elif self._pending_primary and not self._pressed_keys & self._primary_release:
                self._pending_primary = False
                action = "toggle"
            locked = "keyboard" in self._locked_kinds and vk not in self._allowed_vks
            return locked or suppress_trigger, action

    def mouse_event(self, message: int) -> bool:
        with self._lock:
            if message in MOUSE_DOWN_MESSAGES:
                self._mouse_buttons += 1
            elif message in MOUSE_UP_MESSAGES:
                self._mouse_buttons = max(0, self._mouse_buttons - 1)
            return bool(self._locked_kinds & {"mouse", "touchpad"})


class WindowsInputHooks:
    """Hook owner. Hook removal or process exit releases suppression."""

    capabilities = CapabilityReport(
        keyboard=CapabilityLevel.EXPERIMENTAL,
        mouse=CapabilityLevel.EXPERIMENTAL,
        touchpad=CapabilityLevel.EXPERIMENTAL,
        touchscreen=CapabilityLevel.UNSUPPORTED,
        cursor_hiding=CapabilityLevel.UNSUPPORTED,
        lid_control=CapabilityLevel.EXPERIMENTAL,
        detail=(
            "Keyboard and mouse require Windows 11 hardware acceptance; "
            "independent touchscreen suppression is unavailable."
        ),
    )

    def __init__(
        self,
        primary_hotkey: str,
        emergency_hotkey: str,
        allowed_keys: tuple[str, ...] = (),
        *,
        on_toggle: Callable[[], None],
        on_emergency: Callable[[], None],
        on_activity: Callable[[str], None],
    ) -> None:
        if sys.platform != "win32":
            raise OSError("WindowsInputHooks can run only on Windows")
        self.on_toggle = on_toggle
        self.on_emergency = on_emergency
        self.on_activity = on_activity
        self._decision = HookDecisionState(primary_hotkey, emergency_hotkey, allowed_keys)
        self._actions: queue.SimpleQueue[str] = queue.SimpleQueue()
        self._keyboard_activity_pending = threading.Event()
        self._pointer_activity_pending = threading.Event()
        self._stop_actions = threading.Event()
        self._ready = threading.Event()
        self._startup_error: BaseException | None = None
        self._thread_id = 0
        self._keyboard_hook = None
        self._mouse_hook = None
        self._keyboard_callback = HOOKPROC(self._keyboard_proc)
        self._mouse_callback = HOOKPROC(self._mouse_proc)
        self._action_thread = threading.Thread(
            target=self._action_loop, name="locklock-win-actions", daemon=True
        )
        self._hook_thread = threading.Thread(
            target=self._hook_loop, name="locklock-win-hooks", daemon=True
        )
        self._action_thread.start()
        self._hook_thread.start()
        if not self._ready.wait(5):
            raise WindowsHookError("timed out while installing Windows input hooks")
        if self._startup_error is not None:
            raise WindowsHookError(str(self._startup_error))

    @property
    def locked_kinds(self) -> frozenset[str]:
        return self._decision.locked_kinds

    def update_hotkeys(self, primary: str, emergency: str) -> None:
        self._decision.update_hotkeys(primary, emergency)

    def update_allowed_keys(self, keys: tuple[str, ...]) -> None:
        self._decision.update_allowed_keys(keys)

    def lock(self, kinds: frozenset[str]) -> frozenset[str]:
        return self._decision.lock(kinds)

    def unlock(self, kinds: frozenset[str] | None = None) -> frozenset[str]:
        return self._decision.unlock(kinds)

    def close(self) -> None:
        self.unlock()
        self._stop_actions.set()
        self._actions.put("stop")
        if self._thread_id:
            ctypes.windll.user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        if threading.current_thread() is not self._hook_thread:
            self._hook_thread.join(timeout=5)
        if threading.current_thread() is not self._action_thread:
            self._action_thread.join(timeout=5)

    def _keyboard_proc(self, code: int, message: int, data: int) -> int:
        user32 = ctypes.windll.user32
        if code < HC_ACTION:
            return user32.CallNextHookEx(None, code, message, data)
        vk = ctypes.cast(data, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents.vkCode
        suppress, action = self._decision.keyboard_event(vk, message)
        self._queue_activity("keyboard")
        if action:
            self._actions.put(action)
        return 1 if suppress else user32.CallNextHookEx(None, code, message, data)

    def _mouse_proc(self, code: int, message: int, data: int) -> int:
        user32 = ctypes.windll.user32
        if code < HC_ACTION:
            return user32.CallNextHookEx(None, code, message, data)
        locked = self._decision.mouse_event(message)
        self._queue_activity("pointer")
        return 1 if locked else user32.CallNextHookEx(None, code, message, data)

    def _queue_activity(self, kind: str) -> None:
        pending = (
            self._pointer_activity_pending
            if kind == "pointer"
            else self._keyboard_activity_pending
        )
        if not pending.is_set():
            pending.set()
            self._actions.put(f"activity:{kind}")

    def _action_loop(self) -> None:
        while not self._stop_actions.is_set():
            action = self._actions.get()
            if action == "stop":
                return
            try:
                if action == "activity:pointer":
                    self._pointer_activity_pending.clear()
                    self.on_activity("pointer")
                elif action == "activity:keyboard":
                    self._keyboard_activity_pending.clear()
                    self.on_activity("keyboard")
                elif action == "toggle":
                    self.on_toggle()
                elif action == "emergency":
                    self.on_emergency()
            except Exception:
                # The UI/status layer reports transition errors; the callback
                # thread must never be allowed to fail or block here.
                continue

    def _hook_loop(self) -> None:
        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD]
        user32.SetWindowsHookExW.restype = wintypes.HHOOK
        user32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
        user32.CallNextHookEx.restype = LRESULT
        user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
        user32.UnhookWindowsHookEx.restype = wintypes.BOOL
        configure_kernel32(kernel32)
        self._thread_id = kernel32.GetCurrentThreadId()
        try:
            module = kernel32.GetModuleHandleW(None)
            self._keyboard_hook = user32.SetWindowsHookExW(
                WH_KEYBOARD_LL, self._keyboard_callback, module, 0
            )
            self._mouse_hook = user32.SetWindowsHookExW(
                WH_MOUSE_LL, self._mouse_callback, module, 0
            )
            if not self._keyboard_hook or not self._mouse_hook:
                raise ctypes.WinError()
        except BaseException as exc:
            for hook in (self._keyboard_hook, self._mouse_hook):
                if hook:
                    user32.UnhookWindowsHookEx(hook)
            self._keyboard_hook = self._mouse_hook = None
            self._startup_error = exc
            self._ready.set()
            return
        self._ready.set()
        message = wintypes.MSG()
        try:
            while user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
                user32.TranslateMessage(ctypes.byref(message))
                user32.DispatchMessageW(ctypes.byref(message))
        finally:
            if self._mouse_hook:
                user32.UnhookWindowsHookEx(self._mouse_hook)
            if self._keyboard_hook:
                user32.UnhookWindowsHookEx(self._keyboard_hook)
            self._mouse_hook = None
            self._keyboard_hook = None


def configure_kernel32(kernel32) -> None:
    """Pointer-sized Win32 results must never use ctypes' default C int."""
    kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    kernel32.GetModuleHandleW.restype = wintypes.HMODULE
    kernel32.GetCurrentThreadId.argtypes = []
    kernel32.GetCurrentThreadId.restype = wintypes.DWORD
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.GetLastError.argtypes = []
    kernel32.GetLastError.restype = wintypes.DWORD
