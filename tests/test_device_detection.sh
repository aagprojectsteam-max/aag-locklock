#!/usr/bin/env bash
set -Eeuo pipefail

command -v input-lock >/dev/null || {
    printf '%s\n' 'FAIL: input-lock is not installed' >&2
    exit 1
}

systemctl is-active --quiet input-lock.service || {
    printf '%s\n' 'FAIL: input-lock.service is not active' >&2
    exit 1
}

STATUS=$(input-lock status --json)
python3 -c '
import json, sys
state = json.load(sys.stdin)
assert state["daemon"] == "running"
assert int(state["active_devices"]) > 0
assert not state["locked_kinds"], "run this test while unlocked"
' <<<"$STATUS"

input-lock list-devices
printf '%s\n' 'PASS: daemon is unlocked and detects at least one managed event node'
