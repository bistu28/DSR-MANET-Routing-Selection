#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 /path/to/ns-3.48" >&2
  exit 2
fi

NS3_ROOT=$1
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
PATCH_FILE="$SCRIPT_DIR/ns3-3.48-dsr.patch"
HEADER_SOURCE="$SCRIPT_DIR/src/dsr/model/stage2-dsr-event-sink.h"
DRIVER_SOURCE="$SCRIPT_DIR/scratch/dsr_manet_dataset.cc"
EXPECTED_COMMIT="d2add90b452d600cfb4859baed8e9ea633519447"
EXPECTED_PATCH_SHA256="931131e837a4e305ee42f664865311e95003f65a526954d1af2ea0b50ea30922"
EXPECTED_HEADER_SHA256="03e537ff857878604539445727690a9fa39faad690e878b6e2cd2606013377d5"
EXPECTED_DRIVER_SHA256="f356bbf3be16122208a9c39ab79570a1c09e3bfe57f551b24c679475fd70623a"

sha256_file() {
  python3 - "$1" <<'PY'
import hashlib
import pathlib
import sys

digest = hashlib.sha256(pathlib.Path(sys.argv[1]).read_bytes()).hexdigest()
print(digest)
PY
}

require_hash() {
  local file=$1
  local expected=$2
  local actual
  actual=$(sha256_file "$file")
  if [[ "$actual" != "$expected" ]]; then
    echo "SHA-256 mismatch for $file: expected $expected, got $actual" >&2
    exit 1
  fi
}

copy_if_absent_or_identical() {
  local source=$1
  local destination=$2
  local expected=$3
  if [[ -e "$destination" ]]; then
    require_hash "$destination" "$expected"
  else
    mkdir -p "$(dirname -- "$destination")"
    cp "$source" "$destination"
    require_hash "$destination" "$expected"
  fi
}

require_hash "$PATCH_FILE" "$EXPECTED_PATCH_SHA256"
require_hash "$HEADER_SOURCE" "$EXPECTED_HEADER_SHA256"
require_hash "$DRIVER_SOURCE" "$EXPECTED_DRIVER_SHA256"

actual_commit=$(git -C "$NS3_ROOT" rev-parse HEAD)
if [[ "$actual_commit" != "$EXPECTED_COMMIT" ]]; then
  echo "NS-3 source commit mismatch: expected $EXPECTED_COMMIT, got $actual_commit" >&2
  exit 1
fi

if git -C "$NS3_ROOT" apply --reverse --check "$PATCH_FILE" 2>/dev/null; then
  echo "DSR patch already applied."
elif git -C "$NS3_ROOT" apply --check "$PATCH_FILE"; then
  git -C "$NS3_ROOT" apply "$PATCH_FILE"
  echo "Applied DSR source patch."
else
  echo "NS-3 source does not match the clean pinned baseline or the complete patched state." >&2
  exit 1
fi

copy_if_absent_or_identical \
  "$HEADER_SOURCE" \
  "$NS3_ROOT/src/dsr/model/stage2-dsr-event-sink.h" \
  "$EXPECTED_HEADER_SHA256"
copy_if_absent_or_identical \
  "$DRIVER_SOURCE" \
  "$NS3_ROOT/scratch/dsr_manet_dataset.cc" \
  "$EXPECTED_DRIVER_SHA256"

echo "Verified NS-3.48 DSR instrumentation source at $NS3_ROOT"
