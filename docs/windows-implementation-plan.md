# Windows implementation plan and gates

The Ubuntu 1.2.0 baseline is Git commit `4a78b8d`. Every phase must keep the
Ubuntu suite green.

## Phase 1 — shared core (implemented)

- Portable hotkey parsing, settings, bounded JSON framing, capability reports
  and monotonic policy.
- Shared tests run without physical devices or platform imports.
- Linux imports shared version, mode and message-size definitions.

Gate: all existing Ubuntu tests plus shared tests pass.

## Phase 2 — Windows user agent (implemented; acceptance pending)

- Dedicated message-loop thread with `WH_KEYBOARD_LL` and `WH_MOUSE_LL`.
- Transactional logical state, primary shortcut and emergency unlock handled
  inside the hook path.
- Named-pipe server restricted to the current user, administrators and SYSTEM.
- Auto-lock and cursor policy, notification-area UI and settings.

Gate: Windows VM tests prove install/start/status/keyboard/mouse/unlock/quit and
crash release. Hooks are never described as touchscreen support.

## Phase 3 — Windows privileged helper and power (implemented; acceptance pending)

- Non-interactive service with a separate authenticated named pipe.
- Read, journal, apply and restore exact active-scheme AC/DC lid values.
- Session, power, stop and shutdown cleanup.

Gate: restore tests pass for normal stop, forced agent stop, upgrade, uninstall,
service restart and simulated incomplete journal recovery.

## Phase 4 — hardware validation and signed packaging (pending on Windows hardware)

- Real Windows 11 x64 laptop tests for internal/external keyboard and mouse,
  precision touchpad, touch display, lid, battery, suspend and multiple screens.
- Signed-installation-ready bundle and repeatable build. MSI and publisher
  signing remain release work.

Gate: only features passing the real-hardware checklist move from experimental
to verified. Independent touchscreen blocking remains unsupported unless a
documented user-mode method passes the safety review and device tests.

## Stop conditions

- No requested lock may be partially presented as successful.
- No permanent device disable, unsigned driver, cursor-scheme replacement or
  unjournaled power change is accepted.
- If the emergency chord or crash release fails once, Windows locking is not
  released as a stable build.
