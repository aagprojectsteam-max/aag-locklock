# ADR 0001: Windows process model

Status: accepted for implementation; hardware validation pending.

## Decision

Run input hooks, shortcuts, cursor behavior and tray UI in an interactive
per-user agent. Use a separate non-interactive Windows Service only for
operations that require elevation, initially temporary power-policy changes.

## Reason

Windows services are isolated in Session 0 and must not directly interact with
the user's desktop. Keeping hooks in the agent also means process termination
causes Windows to remove the hooks instead of leaving a persistent input lock.
