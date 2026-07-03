#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPOSITORY_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
VERSION="$(tr -d '[:space:]' < "$SCRIPT_DIR/VERSION")"
OUTPUT="$REPOSITORY_ROOT/dist/diagnostics"
TEMPORARY="$(mktemp -d)"
PACKAGE_NAME="sentryalert-diagnostics-$VERSION"

trap 'rm -rf "$TEMPORARY"' EXIT
rm -rf "$OUTPUT"
mkdir -p "$OUTPUT" "$TEMPORARY/$PACKAGE_NAME"
cp -a "$SCRIPT_DIR/." "$TEMPORARY/$PACKAGE_NAME/"
printf '%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" > "$TEMPORARY/$PACKAGE_NAME/BUILD_DATE"
rm -rf "$TEMPORARY/$PACKAGE_NAME/tests" "$TEMPORARY/$PACKAGE_NAME/__pycache__"
chmod 0755 \
  "$TEMPORARY/$PACKAGE_NAME/install.sh" \
  "$TEMPORARY/$PACKAGE_NAME/update.sh" \
  "$TEMPORARY/$PACKAGE_NAME/uninstall.sh" \
  "$TEMPORARY/$PACKAGE_NAME/bin/sentryalert-diag"

COPYFILE_DISABLE=1 tar \
  --no-xattrs \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  -C "$TEMPORARY" \
  -czf "$OUTPUT/$PACKAGE_NAME.tar.gz" \
  "$PACKAGE_NAME"
cp "$TEMPORARY/$PACKAGE_NAME/install.sh" "$OUTPUT/install.sh"
sed "s/@RELEASE_REF@/v$VERSION/" "$OUTPUT/install.sh" > "$OUTPUT/install.sh.pinned"
mv "$OUTPUT/install.sh.pinned" "$OUTPUT/install.sh"
chmod 0755 "$OUTPUT/install.sh"
(
  cd "$OUTPUT"
  sha256sum "$PACKAGE_NAME.tar.gz" install.sh > checksums.txt
)
printf 'Release assets created in %s\n' "$OUTPUT"
