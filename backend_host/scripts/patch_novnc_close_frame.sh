#!/usr/bin/env bash

# Adds the frame.close() call (noVNC commit 8edb3d282eb9ebb138b0f9a4baacb90bb4c4427e)
# to silence the "VideoFrame was garbage collected without being closed" warning.

set -euo pipefail

NOVNC_ROOT="${1:-}"

if [[ -z "$NOVNC_ROOT" ]]; then
  echo "Usage: $0 /path/to/noVNC"
  exit 1
fi

TARGET_PATH="$NOVNC_ROOT/core/util/browser.js"

if [[ ! -f "$TARGET_PATH" ]]; then
  echo "noVNC browser util not found at $TARGET_PATH" >&2
  exit 2
fi

if grep -q "frame.close()" "$TARGET_PATH"; then
  echo "noVNC browser util already patched in $TARGET_PATH"
  exit 0
fi

if ! grep -q "gotframe = true" "$TARGET_PATH"; then
  echo "noVNC version does not need this patch (no ImageDecoder code found)" >&2
  exit 0
fi

python3 - "$TARGET_PATH" <<'PY'
import sys
from pathlib import Path
path = Path(sys.argv[1])
text = path.read_text()
old = "        output: (frame) => { gotframe = true; },"
new = "        output: (frame) => { gotframe = true; frame.close(); },"
path.write_text(text.replace(old, new, 1))
PY

echo "patched $TARGET_PATH"
