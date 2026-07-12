#!/usr/bin/env bash
set -euo pipefail

REPOSITORY="${SENTRYALERT_DIAG_REPOSITORY:-hannson88/sa-tests}"
INSTALL_ROOT="${SENTRYALERT_DIAG_INSTALL_ROOT:-/opt/sentryalert-diagnostics}"
DATA_ROOT="${SENTRYALERT_DIAG_DATA_ROOT:-/mutable/diagnostics}"
ASSET_PREFIX="sentryalert-diagnostics"
RELEASE_REF="${SENTRYALERT_DIAG_RELEASE_REF:-@RELEASE_REF@}"
case "$RELEASE_REF" in
  @*) RELEASE_REF="latest" ;;
esac
if [ -n "${BASH_SOURCE[0]:-}" ]; then
  SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd || pwd)"
else
  SCRIPT_DIR=""
fi

say() { printf '%s\n' "$*"; }
fail() { say "ERROR: $*" >&2; exit 1; }

download() {
  local url="$1" destination="$2"
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL "$url" -o "$destination"
  elif command -v wget >/dev/null 2>&1; then
    wget -qO "$destination" "$url"
  else
    fail "curl or wget is required."
  fi
}

bootstrap() {
  local temporary base query checksums archive_name archive extracted
  temporary="$(mktemp -d)"
  trap 'rm -rf "$temporary"' EXIT
  if [ "$RELEASE_REF" = "latest" ]; then
    base="https://github.com/$REPOSITORY/releases/latest/download"
    query="?cache_bust=$(date +%s)"
  else
    base="https://github.com/$REPOSITORY/releases/download/$RELEASE_REF"
    query=""
  fi
  checksums="$temporary/checksums.txt"
  download "$base/checksums.txt$query" "$checksums"
  archive_name="$(awk '$2 ~ /^sentryalert-diagnostics-[0-9].*\.tar\.gz$/ { print $2; exit }' "$checksums")"
  [ -n "$archive_name" ] || fail "No diagnostics archive was listed in checksums.txt."
  archive="$temporary/$archive_name"
  download "$base/$archive_name$query" "$archive"
  (
    cd "$temporary"
    sha256sum -c checksums.txt --ignore-missing
  )
  tar -xzf "$archive" -C "$temporary"
  extracted="$(find "$temporary" -mindepth 1 -maxdepth 1 -type d -name 'sentryalert-diagnostics-*' | head -n 1)"
  [ -n "$extracted" ] || fail "The downloaded package layout is invalid."
  exec "$extracted/install.sh" --from-bundle
}

if [ -z "$SCRIPT_DIR" ] || [ ! -d "$SCRIPT_DIR/src/sentryalert_diag" ]; then
  bootstrap
fi

[ "$(id -u)" = "0" ] || fail "Run this installer as root."

enter_write_mode() {
  if command -v rw >/dev/null 2>&1; then
    rw || true
  elif [ -x /opt/SentryAlert/scripts/rw ]; then
    /opt/SentryAlert/scripts/rw || true
  else
    mount / -o remount,rw 2>/dev/null || true
  fi
}

enter_readonly_mode() {
  if command -v ro >/dev/null 2>&1; then
    ro || true
  elif [ -x /opt/SentryAlert/scripts/ro ]; then
    /opt/SentryAlert/scripts/ro || true
  fi
}

enter_write_mode
trap enter_readonly_mode EXIT

version="$(tr -d '[:space:]' < "$SCRIPT_DIR/VERSION")"
[ -n "$version" ] || fail "Package version is missing."
build_date="$(tr -d '[:space:]' < "$SCRIPT_DIR/BUILD_DATE")"
build_key="$(printf '%s' "$build_date" | sha256sum | cut -c1-12)"
release_name="$version-$build_key"
release_dir="$INSTALL_ROOT/releases/$release_name"
staging="$INSTALL_ROOT/releases/.install-$release_name-$$"
was_active="no"
systemctl is-active --quiet sentryalert-diagnostics.service 2>/dev/null && was_active="yes"

mkdir -p "$INSTALL_ROOT/releases" "$DATA_ROOT"
chmod 0700 "$DATA_ROOT"
rm -rf "$staging"
mkdir -p "$staging"
cp -a "$SCRIPT_DIR/." "$staging/"
if [ -e "$release_dir" ]; then
  rm -rf "$staging"
else
  mv "$staging" "$release_dir"
fi
ln -sfn "releases/$release_name" "$INSTALL_ROOT/current.new"
mv -Tf "$INSTALL_ROOT/current.new" "$INSTALL_ROOT/current"

if [ ! -f "$DATA_ROOT/config.json" ]; then
  install -m 0600 "$release_dir/config/default.json" "$DATA_ROOT/config.json"
elif grep -q '"default_runtime_seconds"[[:space:]]*:[[:space:]]*7200' "$DATA_ROOT/config.json"; then
  sed -i \
    's/"default_runtime_seconds"[[:space:]]*:[[:space:]]*7200/"default_runtime_seconds": 300/' \
    "$DATA_ROOT/config.json"
elif grep -q '"default_runtime_seconds"[[:space:]]*:[[:space:]]*1800' "$DATA_ROOT/config.json"; then
  sed -i \
    's/"default_runtime_seconds"[[:space:]]*:[[:space:]]*1800/"default_runtime_seconds": 300/' \
    "$DATA_ROOT/config.json"
fi

install -m 0644 "$release_dir/systemd/sentryalert-diagnostics.service" \
  /etc/systemd/system/sentryalert-diagnostics.service

commands=(
  sentryalert-diag
  sentryalert-usb-diag-start
  sentryalert-usb-diag-status
  sentryalert-usb-diag-stop
  sentryalert-usb-diag-export
  sentryalert-usb-diag-resend
  sentryalert-usb-storage-check
  sentryalert-diag-version
  sentryalert-diag-update
  sentryalert-diag-uninstall
)
for command_name in "${commands[@]}"; do
  ln -sfn "$INSTALL_ROOT/current/bin/sentryalert-diag" "/usr/local/bin/$command_name"
done

systemctl daemon-reload
systemctl enable sentryalert-diagnostics.service
if [ "$was_active" = "yes" ]; then
  systemctl restart sentryalert-diagnostics.service
fi

/usr/local/bin/sentryalert-diag-version
say "Installation complete. Diagnostics have not been started."
say "Start with: sudo sentryalert-usb-diag-start"
