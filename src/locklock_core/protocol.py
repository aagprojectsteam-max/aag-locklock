"""Bounded JSON framing shared by local IPC transports."""

from __future__ import annotations

import json
from typing import Any


MAX_MESSAGE_BYTES = 16_384


class ProtocolError(RuntimeError):
    """Raised for malformed or unsafe protocol data."""


def encode_message(message: dict[str, object]) -> bytes:
    if not isinstance(message, dict):
        raise ProtocolError("message must be an object")
    try:
        encoded = json.dumps(
            message,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8") + b"\n"
    except (TypeError, ValueError) as exc:
        raise ProtocolError(f"message is not valid JSON: {exc}") from exc
    if len(encoded) > MAX_MESSAGE_BYTES:
        raise ProtocolError("message is too large")
    return encoded


def decode_message(data: bytes | bytearray) -> dict[str, Any]:
    if not isinstance(data, (bytes, bytearray)):
        raise ProtocolError("message must be bytes")
    if len(data) > MAX_MESSAGE_BYTES:
        raise ProtocolError("message is too large")
    raw = bytes(data)
    if b"\n" in raw:
        raw = raw.split(b"\n", 1)[0]
    if not raw:
        raise ProtocolError("message is empty")
    try:
        message = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError(f"invalid JSON message: {exc}") from exc
    if not isinstance(message, dict):
        raise ProtocolError("message must contain an object")
    return message
