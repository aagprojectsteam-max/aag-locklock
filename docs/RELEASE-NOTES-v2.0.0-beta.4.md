# AAG LockLock 2.0.0-beta.4

Beta.4 publishes the canonical Linux source that matches the accepted
installation and formally includes the AAG safe-suspend adapter that had already
been deployed on the reference machine.

## Changes

- align runtime, VERSION and Python package metadata on 2.0.0-beta.4;
- package aag_sleep_transaction_compat.py in source, wheel and installer;
- preserve the beta.3 thermal/recovery hardening and bounded lid-ignore policy;
- keep the legacy fail-closed sleep graph probe when the AAG transaction
  configuration is absent;
- add adapter-contract and version-consistency regression tests;
- keep local reports and production evidence out of the public source tree.

## Qualification

- full reference qualification: 43 shared, 132 Linux, 175 configuration/protocol/syntax checks PASS
- sanitized public CI subset: 43 shared, 106 Linux, 149 configuration/protocol/syntax checks PASS
- Linux reference installation: 57/57 managed source/installed mappings matched
- live lid-ignore ON/OFF and inhibitor acquire/release PASS
- timed pointer lock and auto-unlock PASS
- final state: unlocked, lid-ignore off, no LockLock inhibitor, no release errors

See docs/BETA4-QUALIFICATION.md.
