# LockLock 2.0.0-beta.4 Linux qualification

Beta.4 is the first public snapshot after the Linux source/runtime
canonicalization. It preserves the accepted bounded lid-ignore state machine and
packages the narrow AAG safe-suspend adapter as an explicit source, wheel and
installer component.

## Automated qualification

- full reference qualification: 43 shared, 132 Linux, 175 configuration/protocol/syntax checks PASS
- sanitized public CI subset: 43 shared, 106 Linux, 149 configuration/protocol/syntax checks PASS
- version-consistency regression: PASS
- wheel and source distribution builds: PASS
- isolated wheel import inventory: PASS
- AAG adapter present in source, wheel and installer payload: PASS

## Reference Linux installation

On the reference Ubuntu 26.04 / GNOME 50 / Wayland machine:

- daemon and tray were active with zero automatic restarts;
- input-lock doctor reported 16 PASS, 0 FAIL;
- 57 managed source/installed mappings matched byte-for-byte;
- all input ended unlocked with no incomplete devices or release errors;
- the AAG sleep graph was reported ready.

## Lid-ignore acceptance

With the physical lid open, enabling temporary lid-ignore:

- reached LID_IGNORE_ARMED;
- acquired the real logind handle-lid-switch block inhibitor;
- reported lid_no_suspend_effective=true;
- kept the lid controller connected;
- did not create a global sleep blocker.

Disabling it released the inhibitor and device grab and returned to SAFE_NORMAL.

The bounded physical close/open path had already been exercised on the same
accepted state-machine design: physical close was detected, finite supervision
started, reopening cancelled the timer, and the inhibitor was released cleanly.
Beta.4 does not expand the allowed closed-lid interval or remove thermal,
battery, telemetry or AAG-suspend safeguards.

## Input-lock acceptance

A timed mouse-mode test grabbed the expected pointer/touchpad nodes while
leaving the keyboard available. Automatic unlock released all grabs and left no
incomplete device or release error.

## Scope

This qualification applies to the tested Linux reference stack. Windows support
remains beta/experimental where the Windows compatibility documentation says
hardware acceptance is still required.
