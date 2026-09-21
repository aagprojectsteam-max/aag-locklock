# Windows API references

Official Microsoft documentation used for the Windows design:

- [Interactive Services](https://learn.microsoft.com/en-us/windows/win32/services/interactive-services) — services cannot directly interact with users on current Windows; use a separate per-user process and IPC.
- [LowLevelKeyboardProc](https://learn.microsoft.com/en-us/windows/win32/winmsg/lowlevelkeyboardproc) — `WH_KEYBOARD_LL`, suppression return value, message-loop and callback-timeout requirements.
- [LowLevelMouseProc](https://learn.microsoft.com/en-us/windows/win32/winmsg/lowlevelmouseproc) — `WH_MOUSE_LL`, suppression return value and callback-timeout requirements.
- [RegisterHotKey](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-registerhotkey) — global shortcut behavior, no-repeat flag and Windows' F12 reservation.
- [Named Pipes](https://learn.microsoft.com/en-us/windows/win32/ipc/named-pipes) — local pipe transport and the need to reject remote access explicitly.
- [Impersonating a Named Pipe Client](https://learn.microsoft.com/en-us/windows/win32/ipc/impersonating-a-named-pipe-client) — client-token verification and mandatory reversion.
- [Windows Touch architectural overview](https://learn.microsoft.com/en-us/windows/win32/wintouch/architectural-overview) — touch/gesture messages are delivered to an application window, not exposed as a documented global suppression hook.
- [ShowCursor](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-showcursor) — thread-local display-count semantics; global cursor hiding is therefore unsupported.
- [Power setting GUIDs](https://learn.microsoft.com/en-us/windows/win32/power/power-setting-guids) — lid, AC/DC source and related power notifications.
- [Lid switch close action](https://learn.microsoft.com/en-us/windows-hardware/customize/power-settings/power-button-and-lid-settings-lid-switch-close-action) — `LIDACTION` GUID and values.

These references justify API selection; they do not replace the real Windows 11
hardware acceptance tests required by the implementation plan.

## Remediation contract references

- [ctypes return types](https://docs.python.org/3/library/ctypes.html#return-types): declare pointer-returning native functions explicitly.
- [Tkinter threading model](https://docs.python.org/3/library/tkinter.html#threading-model): worker-to-Tk calls can wait for the interpreter event loop; use the main-thread queue.
- [Named-pipe wait modes](https://learn.microsoft.com/en-us/windows/win32/ipc/named-pipe-type-read-and-wait-modes): bounded nonblocking message-mode polling and zero-byte writes.
- [ConnectNamedPipe](https://learn.microsoft.com/en-us/windows/win32/api/namedpipeapi/nf-namedpipeapi-connectnamedpipe): distinguish listening from an established nonblocking connection.
- [FlushFileBuffers](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-flushfilebuffers): the old server-side pipe flush can wait for the client; beta.2 replaces it with a bounded consumption ACK.
- [OpenInputDesktop](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-openinputdesktop): combine input-desktop checks with active-console identity, since a disconnected session alone is insufficient.
- [Linux input event synchronization](https://docs.kernel.org/input/event-codes.html): discard through the next SYN_REPORT after SYN_DROPPED, then query device state.
