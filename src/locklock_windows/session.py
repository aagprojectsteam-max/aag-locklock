"""Windows power/session monitor that releases input before transitions."""

from __future__ import annotations

import os
import threading
from collections.abc import Callable


WM_POWERBROADCAST = 0x0218
WM_QUERYENDSESSION = 0x0011
WM_ENDSESSION = 0x0016
WM_WTSSESSION_CHANGE = 0x02B1
PBT_APMSUSPEND = 0x0004
PBT_APMRESUMEAUTOMATIC = 0x0012
WTS_CONSOLE_DISCONNECT = 0x2
WTS_REMOTE_DISCONNECT = 0x4
WTS_SESSION_LOGOFF = 0x6
WTS_SESSION_LOCK = 0x7
WTS_SESSION_UNLOCK = 0x8


def transition_requires_unlock(message: int, event: int) -> bool:
    if message == WM_POWERBROADCAST:
        return event in {PBT_APMSUSPEND, PBT_APMRESUMEAUTOMATIC}
    if message in {WM_QUERYENDSESSION, WM_ENDSESSION}:
        return True
    if message == WM_WTSSESSION_CHANGE:
        return event in {
            WTS_CONSOLE_DISCONNECT,
            WTS_REMOTE_DISCONNECT,
            WTS_SESSION_LOGOFF,
            WTS_SESSION_LOCK,
            WTS_SESSION_UNLOCK,
        }
    return False


class WindowsSessionMonitor:
    def __init__(self, on_session: Callable[[bool], None]) -> None:
        if os.name != "nt":
            raise OSError("WindowsSessionMonitor can run only on Windows")
        self.on_session = on_session
        self._ready = threading.Event()
        self._startup_error: BaseException | None = None
        self._window = None
        self._thread = threading.Thread(
            target=self._run, name="locklock-win-session", daemon=True
        )
        self._thread.start()
        if not self._ready.wait(5):
            raise RuntimeError("timed out while starting the Windows session monitor")
        if self._startup_error:
            raise RuntimeError(str(self._startup_error))

    def close(self) -> None:
        if self._window:
            import win32con
            import win32gui

            win32gui.PostMessage(self._window, win32con.WM_CLOSE, 0, 0)
        if threading.current_thread() is not self._thread:
            self._thread.join(timeout=5)

    def _run(self) -> None:
        import win32api
        import win32con
        import win32gui
        import win32ts

        class_name = f"AAGLockLockSessionMonitor-{os.getpid()}"

        def window_proc(window, message, wparam, lparam):
            if transition_requires_unlock(message, int(wparam)):
                try:
                    self.on_session(False)
                except Exception:
                    pass
            if message == win32con.WM_TIMER:
                self.on_session(interactive_session_active())
                return 0
            if message == win32con.WM_CLOSE:
                try:
                    win32ts.WTSUnRegisterSessionNotification(window)
                except Exception:
                    pass
                win32gui.DestroyWindow(window)
                return 0
            if message == win32con.WM_DESTROY:
                win32gui.PostQuitMessage(0)
                return 0
            if message == WM_QUERYENDSESSION:
                return 1
            return win32gui.DefWindowProc(window, message, wparam, lparam)

        try:
            window_class = win32gui.WNDCLASS()
            window_class.hInstance = win32api.GetModuleHandle(None)
            window_class.lpszClassName = class_name
            window_class.lpfnWndProc = window_proc
            win32gui.RegisterClass(window_class)
            self._window = win32gui.CreateWindowEx(
                0,
                class_name,
                class_name,
                0,
                0,
                0,
                0,
                0,
                None,
                None,
                window_class.hInstance,
                None,
            )
            win32ts.WTSRegisterSessionNotification(
                self._window, win32ts.NOTIFY_FOR_THIS_SESSION
            )
        except BaseException as exc:
            self._startup_error = exc
            self._ready.set()
            return
        self.on_session(interactive_session_active())
        import ctypes
        from ctypes import wintypes
        timer = ctypes.windll.user32.SetTimer
        timer.argtypes = [wintypes.HWND, ctypes.c_size_t, wintypes.UINT, ctypes.c_void_p]
        timer.restype = ctypes.c_size_t
        if not timer(self._window, 1, 1000, None):
            self.on_session(False)
            self._startup_error = RuntimeError("Cannot start session eligibility timer")
            self._ready.set()
            win32gui.DestroyWindow(self._window)
            return
        self._ready.set()
        win32gui.PumpMessages()
        self._window = None


def interactive_session_active() -> bool:
    """Require this process's active console and the ordinary input desktop."""
    import ctypes
    from ctypes import wintypes
    import win32api
    import win32ts
    try:
        session = win32ts.ProcessIdToSessionId(win32api.GetCurrentProcessId())
        if session != win32ts.WTSGetActiveConsoleSessionId():
            return False
        if win32ts.WTSQuerySessionInformation(None, session, win32ts.WTSConnectState) != win32ts.WTSActive:
            return False
        user32 = ctypes.windll.user32
        user32.OpenInputDesktop.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        user32.OpenInputDesktop.restype = wintypes.HANDLE
        user32.CloseDesktop.argtypes = [wintypes.HANDLE]
        user32.CloseDesktop.restype = wintypes.BOOL
        user32.GetUserObjectInformationW.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
        user32.GetUserObjectInformationW.restype = wintypes.BOOL
        desktop = user32.OpenInputDesktop(0, False, 1)  # DESKTOP_READOBJECTS
        if not desktop:
            return False
        try:
            name = ctypes.create_unicode_buffer(256)
            needed = wintypes.DWORD()
            return bool(user32.GetUserObjectInformationW(desktop, 2, name, ctypes.sizeof(name), ctypes.byref(needed))) and name.value.lower() == "default"
        finally:
            user32.CloseDesktop(desktop)
    except Exception:
        return False
