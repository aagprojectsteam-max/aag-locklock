#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)

if (( EUID != 0 )); then
    printf '%s\n' 'Run with: sudo ./update.sh' >&2
    exit 1
fi

TARGET_USER=${SUDO_USER:-}
if [[ -r /etc/input-lock/install-state ]]; then
    SAVED_USER=$(awk -F= '$1=="TARGET_USER" {print $2}' /etc/input-lock/install-state)
    [[ -n "$SAVED_USER" ]] && TARGET_USER=$SAVED_USER
fi

[[ -n "$TARGET_USER" && "$TARGET_USER" != root ]] || {
    printf '%s\n' 'Cannot determine target user; run sudo ./install.sh --user LOGIN --update' >&2
    exit 1
}

exec "$PROJECT_DIR/install.sh" --user "$TARGET_USER" --update
