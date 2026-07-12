#!/usr/bin/env bash
set -euo pipefail

REPOSITORY="${SENTRYALERT_DIAG_REPOSITORY:-hannson88/sa-tests}"
RELEASE_REF="${SENTRYALERT_DIAG_RELEASE_REF:-latest}"

say() { printf '%s\n' "$*"; }
fail() { say "ERROR: $*" >&2; exit 1; }

[ "$(id -u)" = "0" ] || fail "Run this script as root, for example: curl ... | sudo bash"

if [ "$RELEASE_REF" = "latest" ]; then
  base="https://github.com/$REPOSITORY/releases/latest/download"
  query="?cache_bust=$(date +%s)"
else
  base="https://github.com/$REPOSITORY/releases/download/$RELEASE_REF"
  query=""
fi

temporary="$(mktemp -d)"
trap 'rm -rf "$temporary"' EXIT

if command -v curl >/dev/null 2>&1; then
  curl -fsSL "$base/install.sh$query" -o "$temporary/install.sh"
elif command -v wget >/dev/null 2>&1; then
  wget -qO "$temporary/install.sh" "$base/install.sh$query"
else
  fail "curl or wget is required."
fi

bash "$temporary/install.sh"

say ""
say "Collecting USB storage layout check now..."
sentryalert-usb-storage-check
