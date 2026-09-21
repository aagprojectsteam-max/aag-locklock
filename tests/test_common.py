#!/usr/bin/python3
from __future__ import annotations

import json
import socket
import sys
import tempfile
import threading
import unittest
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SOURCE))

from input_lock_common import (  # noqa: E402
    ConfigError,
    ProtocolError,
    load_config,
    response_ok,
    send_request,
)


BASE_CONFIG = """\
AUTHORIZED_UID=1000
AUTHORIZED_USER=tester
HOTKEY=CTRL+ALT+Z
EMERGENCY_HOTKEY=CTRL+ALT+SHIFT+F12
DEFAULT_MODE=all
AUTO_UNLOCK_SECONDS=30
DEBOUNCE_MS=700
EXCLUDE_DEVICES=/dev/input/by-id/Keyboard With Spaces-event-kbd
EXCLUDE_VENDOR_PRODUCT=046d:c31c
"""


class ConfigTests(unittest.TestCase):
    def parse(self, text: str = BASE_CONFIG):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config"
            path.write_text(text, encoding="utf-8")
            return load_config(path)

    def test_valid_config(self) -> None:
        config = self.parse()
        self.assertEqual(config.authorized_uid, 1000)
        self.assertEqual(config.auto_unlock_seconds, 30)
        self.assertEqual(config.exclude_vendor_product, ("046d:c31c",))
        self.assertIn("Keyboard With Spaces", config.exclude_devices[0])

    def test_unknown_key_is_rejected(self) -> None:
        with self.assertRaises(ConfigError):
            self.parse(BASE_CONFIG + "UNSAFE_SHELL_COMMAND=anything\n")

    def test_duplicate_key_is_rejected(self) -> None:
        with self.assertRaises(ConfigError):
            self.parse(BASE_CONFIG + "AUTHORIZED_UID=2000\n")

    def test_bad_boolean_is_rejected(self) -> None:
        with self.assertRaises(ConfigError):
            self.parse(BASE_CONFIG + "SHOW_NOTIFICATIONS=perhaps\n")

    def test_bad_vendor_product_is_rejected(self) -> None:
        with self.assertRaises(ConfigError):
            self.parse(BASE_CONFIG.replace("046d:c31c", "not-a-device"))

    def test_same_hotkeys_are_rejected(self) -> None:
        with self.assertRaises(ConfigError):
            self.parse(
                BASE_CONFIG.replace(
                    "EMERGENCY_HOTKEY=CTRL+ALT+SHIFT+F12",
                    "EMERGENCY_HOTKEY=CTRL+ALT+Z",
                )
            )


class ProtocolTests(unittest.TestCase):
    def test_one_request_one_response(self) -> None:
        try:
            probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            probe.close()
        except PermissionError:
            self.skipTest("the current test sandbox blocks AF_UNIX socket creation")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "control.sock"
            ready = threading.Event()

            def server() -> None:
                listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                listener.bind(str(path))
                listener.listen(1)
                ready.set()
                connection, _ = listener.accept()
                request = json.loads(connection.recv(4096).decode("utf-8"))
                response = {"ok": True, "echo": request.get("cmd")}
                connection.sendall(json.dumps(response).encode("utf-8") + b"\n")
                connection.close()
                listener.close()

            worker = threading.Thread(target=server, daemon=True)
            worker.start()
            self.assertTrue(ready.wait(2))
            response = send_request({"cmd": "ping"}, socket_path=path)
            self.assertEqual(response["echo"], "ping")
            worker.join(2)

    def test_error_response(self) -> None:
        with self.assertRaises(ProtocolError):
            response_ok({"ok": False, "error": "denied"})


if __name__ == "__main__":
    unittest.main()
