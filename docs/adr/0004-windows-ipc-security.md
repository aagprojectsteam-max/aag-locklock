# ADR 0004: Windows IPC and authorization

Status: accepted for implementation.

## Decision

Use local Windows named pipes with remote clients rejected. Apply an explicit
DACL for the installed user SID, Administrators and SYSTEM. After reading a
request, the server impersonates the pipe client, verifies its token SID and
always calls `RevertToSelf` in a `finally` path. A failed impersonation rejects
the request.

Messages reuse the shared bounded one-JSON-object framing. The user-agent pipe
and privileged-service pipe have different names and command allowlists.
