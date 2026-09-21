"""Contracts implemented by the Linux and Windows platform backends."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol, runtime_checkable


class CapabilityLevel(str, Enum):
    VERIFIED = "verified"
    EXPERIMENTAL = "experimental"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True, slots=True)
class CapabilityReport:
    keyboard: CapabilityLevel
    mouse: CapabilityLevel
    touchpad: CapabilityLevel
    touchscreen: CapabilityLevel
    cursor_hiding: CapabilityLevel
    lid_control: CapabilityLevel
    detail: str = ""

    def level_for(self, kind: str) -> CapabilityLevel:
        if kind not in {"keyboard", "mouse", "touchpad", "touchscreen"}:
            raise ValueError(f"unknown input kind: {kind}")
        return getattr(self, kind)

    def require_lockable(self, kinds: set[str] | frozenset[str]) -> None:
        unavailable = sorted(
            kind
            for kind in kinds
            if self.level_for(kind) is CapabilityLevel.UNSUPPORTED
        )
        if unavailable:
            raise UnsupportedCapabilityError(
                "not supported on this platform: " + ", ".join(unavailable)
            )


class UnsupportedCapabilityError(RuntimeError):
    """Raised before a transition if a requested class cannot be controlled."""


@runtime_checkable
class InputBackend(Protocol):
    """Small transactional interface shared by platform input implementations."""

    @property
    def capabilities(self) -> CapabilityReport: ...

    @property
    def locked_kinds(self) -> frozenset[str]: ...

    def lock(self, kinds: frozenset[str]) -> frozenset[str]: ...

    def unlock(self, kinds: frozenset[str] | None = None) -> frozenset[str]: ...

    def close(self) -> None: ...
