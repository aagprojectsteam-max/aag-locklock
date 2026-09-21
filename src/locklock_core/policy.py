"""Pure monotonic-time policy shared by platform agents."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .settings import UserSettings


class PolicyAction(str, Enum):
    LOCK_DEFAULT = "lock-default"
    UNLOCK_ALL = "unlock-all"
    HIDE_CURSOR = "hide-cursor"
    SHOW_CURSOR = "show-cursor"


@dataclass(slots=True)
class PolicyEngine:
    settings: UserSettings
    last_activity: float
    last_pointer_activity: float | None = None
    auto_unlock_deadline: float | None = None
    cursor_hidden: bool = False

    def __post_init__(self) -> None:
        if self.last_pointer_activity is None:
            self.last_pointer_activity = self.last_activity

    def activity(self, now: float, *, pointer: bool = True) -> tuple[PolicyAction, ...]:
        self.last_activity = now
        if pointer:
            self.last_pointer_activity = now
        if pointer and self.cursor_hidden:
            self.cursor_hidden = False
            return (PolicyAction.SHOW_CURSOR,)
        return ()

    def locked(self, now: float, auto_unlock_seconds: int = 0) -> None:
        self.auto_unlock_deadline = (
            now + auto_unlock_seconds if auto_unlock_seconds > 0 else None
        )

    def unlocked(self, now: float) -> None:
        self.auto_unlock_deadline = None
        self.last_activity = now
        self.last_pointer_activity = now

    def update_settings(self, settings: UserSettings, now: float) -> tuple[PolicyAction, ...]:
        self.settings = settings
        self.last_activity = now
        self.last_pointer_activity = now
        if self.cursor_hidden and not settings.hide_cursor_enabled:
            self.cursor_hidden = False
            return (PolicyAction.SHOW_CURSOR,)
        return ()

    def tick(self, now: float, *, is_locked: bool) -> tuple[PolicyAction, ...]:
        actions: list[PolicyAction] = []
        if is_locked:
            if self.auto_unlock_deadline is not None and now >= self.auto_unlock_deadline:
                self.auto_unlock_deadline = None
                actions.append(PolicyAction.UNLOCK_ALL)
            return tuple(actions)
        if (
            self.settings.idle_lock_enabled
            and now - self.last_activity >= self.settings.idle_lock_seconds
        ):
            self.last_activity = now
            actions.append(PolicyAction.LOCK_DEFAULT)
        if (
            self.settings.hide_cursor_enabled
            and not self.cursor_hidden
            and self.last_pointer_activity is not None
            and now - self.last_pointer_activity >= self.settings.hide_cursor_seconds
        ):
            self.cursor_hidden = True
            actions.append(PolicyAction.HIDE_CURSOR)
        return tuple(actions)
