"""Native transport/ABI checks only; never install hooks or change power state."""
import os
import unittest
import uuid

@unittest.skipUnless(os.name == 'nt', 'Windows native APIs required')
class NativeTests(unittest.TestCase):
    def test_pipe_round_trip_and_shutdown(self):
        from locklock_windows.ipc import NamedPipeServer, send_request, current_user_sid
        name = r'\\.\pipe\LockLock-test-' + uuid.uuid4().hex
        server = NamedPipeServer(name, current_user_sid(), lambda request:{'ok':True, 'echo':request})
        server.start()
        try:
            for _ in range(3):
                try:
                    response = send_request(name, {'cmd':'fixture'}, timeout_ms=5000)
                except Exception as exc:
                    self.fail(
                        f"client={type(exc).__name__}: {exc}; "
                        f"server_phase={server.phase}; "
                        f"server_request_error={server.last_request_error!r}; "
                        f"server_error={server.error!r}"
                    )
                self.assertEqual(response, {'ok':True,'echo':{'cmd':'fixture'}})
        finally:
            server.close()
        self.assertFalse(server._thread.is_alive())
        self.assertIsNone(server.error)

    def test_module_handle_pointer(self):
        import ctypes
        from locklock_windows.input_hooks import configure_kernel32
        kernel = ctypes.windll.kernel32
        configure_kernel32(kernel)
        handle = kernel.GetModuleHandleW(None)
        self.assertTrue(handle)
        import win32api
        self.assertEqual(handle, win32api.GetModuleHandle(None))
