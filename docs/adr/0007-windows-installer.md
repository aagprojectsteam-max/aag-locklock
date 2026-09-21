# ADR 0007: Windows packaging

Status: accepted direction; signing infrastructure pending.

## Decision

Use PyInstaller for deterministic agent/service executables and WiX Toolset for
an MSI capable of service install, repair, upgrade and removal. Build output is
signing-ready but must not be called signed unless an actual publisher
certificate is supplied.

The MSI custom-action sequence must request unlock/restore before replacement
or removal. Start-at-login controls only the user agent; service installation is
machine-wide and independently permissioned.
