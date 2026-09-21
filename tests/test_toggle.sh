#!/usr/bin/env bash
set -Eeuo pipefail

if [[ ${1:-} != --armed ]]; then
    cat <<'EOF'
This test temporarily locks pointer devices for 5 seconds.
It never locks the keyboard. Run it only after `input-lock doctor` passes:

    ./tests/test_toggle.sh --armed
EOF
    exit 2
fi

input-lock emergency-unlock >/dev/null
input-lock lock mouse --timeout 5
printf '%s\n' 'Pointer is locked. It must auto-unlock in five seconds; keyboard remains usable.'
sleep 7

STATUS=$(input-lock status --json)
python3 -c '
import json, sys
state = json.load(sys.stdin)
locked = state["locked"]
assert not locked["mouse"]
assert not locked["touchpad"]
' <<<"$STATUS"

printf '%s\n' 'PASS: pointer lock auto-unlocked'
