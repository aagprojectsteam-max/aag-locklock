# ADR 0006: Windows power and lid policy

Status: accepted design; implementation and hardware validation pending.

## Decision

Leave Windows power policy untouched by default. When the user explicitly opts
in, the service reads and journals the active scheme GUID and exact AC/DC
`LIDACTION` values before writing `Do Nothing`. Restore those values when the
condition ends, the option is disabled, the service stops, upgrade/uninstall
begins, or an incomplete journal is found on the next start.

Monitor source, charge and lid state through documented Windows power
notifications. A battery-threshold transition while the lid is already closed
must be tested explicitly; it must not be assumed that merely restoring the
setting causes immediate sleep.

The agent renews a short service lease while the temporary policy is required.
If the agent crashes or stops renewing, the service restores the journaled
values automatically instead of waiting for reboot or service shutdown.
