"""Secured local Windows named-pipe transport using pywin32."""

from __future__ import annotations

import threading
import time
import logging

from locklock_core import MAX_MESSAGE_BYTES, decode_message, encode_message


def current_user_sid() -> str:
    import win32api
    import win32security

    token = win32security.OpenProcessToken(win32api.GetCurrentProcess(), win32security.TOKEN_QUERY)
    try:
        sid = win32security.GetTokenInformation(token, win32security.TokenUser)[0]
        return win32security.ConvertSidToStringSid(sid)
    finally:
        token.Close()


def _security_attributes(authorized_sid: str):
    import ntsecuritycon
    import pywintypes
    import win32security

    dacl = win32security.ACL()
    access = ntsecuritycon.GENERIC_READ | ntsecuritycon.GENERIC_WRITE
    for sid_text in (
        authorized_sid,
        "S-1-5-18",  # LocalSystem
        "S-1-5-32-544",  # Builtin Administrators
    ):
        dacl.AddAccessAllowedAce(
            win32security.ACL_REVISION,
            access,
            win32security.ConvertStringSidToSid(sid_text),
        )
    descriptor = win32security.SECURITY_DESCRIPTOR()
    descriptor.SetSecurityDescriptorDacl(True, dacl, False)
    attributes = pywintypes.SECURITY_ATTRIBUTES()
    attributes.SECURITY_DESCRIPTOR = descriptor
    return attributes


def _verified_client(pipe) -> tuple[str, bool]:
    import win32api
    import win32pipe
    import win32security

    impersonated = False
    token = None
    try:
        win32pipe.ImpersonateNamedPipeClient(pipe)
        impersonated = True
        token = win32security.OpenThreadToken(
            win32api.GetCurrentThread(), win32security.TOKEN_QUERY, True
        )
        sid = win32security.GetTokenInformation(token, win32security.TokenUser)[0]
        administrators = win32security.ConvertStringSidToSid("S-1-5-32-544")
        is_administrator = bool(win32security.CheckTokenMembership(token, administrators))
        return win32security.ConvertSidToStringSid(sid), is_administrator
    finally:
        try:
            if token is not None:
                token.Close()
        finally:
            if impersonated:
                win32security.RevertToSelf()


class Deadline:
    """One monotonic budget for connect, request, response and consumption ACK."""
    def __init__(self, seconds, stop=None, clock=time.monotonic):
        self.clock = clock
        self.end = clock() + seconds
        self.stop = stop or threading.Event()

    def check(self):
        if self.stop.is_set():
            raise InterruptedError("pipe server stopped")
        remaining = self.end - self.clock()
        if remaining <= 0:
            raise TimeoutError("named-pipe request deadline expired")
        return remaining

    def pause(self):
        self.stop.wait(min(.025, self.check()))
        self.check()


def read_message(handle, deadline, file_api):
    chunks = bytearray()
    while True:
        deadline.check()
        try:
            status, data = file_api.ReadFile(handle, MAX_MESSAGE_BYTES + 1)
        except Exception as exc:
            if getattr(exc, "winerror", None) == 232:  # PIPE_NOWAIT, no data yet
                deadline.pause()
                continue
            raise
        if status not in {0, 234}:
            raise OSError(f"pipe read failed: {status}")
        if not data:
            raise EOFError("pipe peer disconnected")
        chunks.extend(data)
        if len(chunks) > MAX_MESSAGE_BYTES or status == 234:
            raise ValueError("pipe message exceeds limit")
        if b"\n" in chunks:
            return decode_message(chunks)


def write_message(handle, payload, deadline, file_api):
    data = encode_message(payload)
    while True:
        deadline.check()
        status, written = file_api.WriteFile(handle, data)
        if status:
            raise OSError(f"pipe write failed: {status}")
        if written == len(data):
            return
        if written != 0:
            raise OSError("partial message-mode pipe write")
        # A nonblocking message-mode write transfers all bytes or zero bytes.
        deadline.pause()


class NamedPipeServer:
    def __init__(self, pipe_name, authorized_sid, dispatch):
        self.pipe_name, self.authorized_sid, self.dispatch = pipe_name, authorized_sid, dispatch
        self._stop = threading.Event()
        self._ready = threading.Event()
        self.error = None
        self._thread = threading.Thread(target=self._run, name="locklock-win-pipe", daemon=True)

    def start(self):
        self._thread.start()
        if not self._ready.wait(5):
            self._stop.set()
            raise TimeoutError("named-pipe server did not start")
        if self.error:
            raise RuntimeError(self.error)

    def close(self):
        self._stop.set()
        if threading.current_thread() is not self._thread:
            self._thread.join(timeout=1)

    def _run(self):
        import win32file
        import win32pipe
        # Deliberate bounded synchronous polling, not overlapped I/O. No read,
        # write, accept or FlushFileBuffers can wait indefinitely for a peer.
        mode = win32pipe.PIPE_TYPE_MESSAGE | win32pipe.PIPE_READMODE_MESSAGE | win32pipe.PIPE_NOWAIT | 8
        pipe = None
        try:
            pipe = win32pipe.CreateNamedPipe(self.pipe_name,
                win32pipe.PIPE_ACCESS_DUPLEX | 0x00080000,
                mode, 1, MAX_MESSAGE_BYTES, MAX_MESSAGE_BYTES, 1000,
                _security_attributes(self.authorized_sid))
            while not self._stop.is_set():
                self._ready.set()
                try:
                    while not self._stop.is_set():
                        try:
                            win32pipe.ConnectNamedPipe(pipe, None)
                        except Exception as exc:
                            if getattr(exc, "winerror", None) == 535:  # CONNECTED
                                break
                            if getattr(exc, "winerror", None) != 536:  # LISTENING
                                raise
                        # Initial success means listening in PIPE_NOWAIT mode.
                        self._stop.wait(.025)
                    deadline = Deadline(5, self._stop)
                    request = read_message(pipe, deadline, win32file)
                    sid, administrator = _verified_client(pipe)
                    if sid not in {self.authorized_sid, "S-1-5-18"} and not administrator:
                        response = {"ok":False, "error":"unauthorized pipe client"}
                    else:
                        response = self.dispatch(request)
                    write_message(pipe, response, deadline, win32file)
                    # Disconnect would discard unread bytes. A bounded ACK
                    # replaces the old unbounded server FlushFileBuffers call.
                    read_message(pipe, deadline, win32file)
                except (TimeoutError, InterruptedError, EOFError):
                    pass
                except Exception as exc:
                    logging.getLogger(__name__).warning("pipe request rejected: %s", exc)
                finally:
                    try:
                        win32pipe.DisconnectNamedPipe(pipe)
                    except Exception:
                        pass
        except Exception as exc:
            self.error = str(exc)
        finally:
            if pipe is not None:
                win32file.CloseHandle(pipe)
            self._ready.set()


def send_request(pipe_name, request, *, timeout_ms=5000):
    import win32file
    import win32pipe
    deadline = Deadline(timeout_ms / 1000)
    while True:
        try:
            # CreateFile on a pipe is immediate; a busy instance is retried
            # within the same budget, with no separate blocking connect wait.
            deadline.check()
            handle = win32file.CreateFile(pipe_name,
                win32file.GENERIC_READ | win32file.GENERIC_WRITE, 0, None,
                win32file.OPEN_EXISTING, 0, None)
            break
        except Exception as exc:
            if getattr(exc, "winerror", None) not in {2, 231}:  # absent or busy
                raise
            deadline.pause()
    try:
        win32pipe.SetNamedPipeHandleState(handle,
            win32pipe.PIPE_READMODE_MESSAGE | win32pipe.PIPE_NOWAIT, None, None)
        write_message(handle, request, deadline, win32file)
        response = read_message(handle, deadline, win32file)
        try:
            write_message(handle, {"ack":True}, deadline, win32file)
        except Exception as exc:
            if getattr(exc, "winerror", None) not in {109, 232, 233}:
                raise
        return response
    finally:
        win32file.CloseHandle(handle)
