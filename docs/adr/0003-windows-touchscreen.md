# ADR 0003: Windows touchscreen

Status: unsupported pending proof.

## Decision

Do not equate `WH_MOUSE_LL` with touchscreen suppression. Windows touch APIs
route `WM_TOUCH`/pointer messages to windows; they do not document a global
low-level suppression hook equivalent to the keyboard and mouse hooks.

Do not disable a PnP/HID device, add an unsigned filter driver or place a
full-screen overlay without an explicit future design review. The Windows UI
must disable touchscreen selection and explain the limitation until an
independent, reversible method is proven on real touch hardware.
