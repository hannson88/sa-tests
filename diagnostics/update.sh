#!/usr/bin/env bash
set -euo pipefail

[ "$(id -u)" = "0" ] || { printf 'Run this updater as root.\n' >&2; exit 1; }
temporary="$(mktemp)"
trap 'rm -f "$temporary"' EXIT
curl -fsSL \
  "https://github.com/hannson88/sa-tests/releases/latest/download/install.sh" \
  -o "$temporary"
exec bash "$temporary"

