# ADR 0002: Windows keyboard and pointer input

Status: accepted as experimental until Windows hardware tests pass.

## Decision

Use documented low-level `WH_KEYBOARD_LL` and `WH_MOUSE_LL` hooks on a dedicated
message-loop thread. Callbacks only update bounded state or enqueue actions and
return immediately. A nonzero callback result suppresses a selected class.

The fixed emergency chord is recognized in the keyboard hook before ordinary
suppression. `Ctrl+Alt+Del` is never intercepted. The Windows primary shortcut
must not use F12 because Windows reserves F12 for a debugger.

## Consequences

Mouse and precision-touchpad pointer output share the Windows mouse path and
cannot be claimed as independently isolated devices. Hook health and repeated
lock/unlock require real Windows validation because Windows can silently remove
a hook whose callback times out.
