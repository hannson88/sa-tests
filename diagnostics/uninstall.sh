#!/usr/bin/env bash
set -euo pipefail

INSTALL_ROOT="${SENTRYALERT_DIAG_INSTALL_ROOT:-/opt/sentryalert-diagnostics}"
DATA_ROOT="${SENTRYALERT_DIAG_DATA_ROOT:-/mutable/diagnostics}"
purge="no"
[ "${1:-}" = "--purge" ] && purge="yes"
[ -z "${1:-}" ] || [ "$purge" = "yes" ] || {
  printf 'Usage: sentryalert-diag-uninstall [--purge]\n' >&2
  exit 2
}
[ "$(id -u)" = "0" ] || { printf 'Run this uninstaller as root.\n' >&2; exit 1; }

if command -v rw >/dev/null 2>&1; then
  rw || true
elif [ -x /opt/SentryAlert/scripts/rw ]; then
  /opt/SentryAlert/scripts/rw || true
else
  mount / -o remount,rw 2>/dev/null || true
fi

systemctl disable --now sentryalert-diagnostics.service 2>/dev/null || true
rm -f /etc/systemd/system/sentryalert-diagnostics.service
systemctl daemon-reload

for path in /usr/local/bin/sentryalert-diag /usr/local/bin/sentryalert-*-diag-* /usr/local/bin/sentryalert-diag-*; do
  if [ -L "$path" ] && readlink "$path" | grep -q "$INSTALL_ROOT"; then
    rm -f "$path"
  fi
done
rm -rf "$INSTALL_ROOT"

if [ "$purge" = "yes" ]; then
  rm -rf "$DATA_ROOT"
  printf 'Diagnostics package and persistent evidence removed.\n'
else
  printf 'Diagnostics package removed. Evidence remains in %s.\n' "$DATA_ROOT"
fi

if command -v ro >/dev/null 2>&1; then
  ro || true
elif [ -x /opt/SentryAlert/scripts/ro ]; then
  /opt/SentryAlert/scripts/ro || true
fi

