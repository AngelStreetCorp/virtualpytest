#!/bin/bash
# Run the production channel-banner analysis on one image, through the AI gateway.
#
# The model is whatever the vision.banner AI route resolves to (Settings -> AI);
# the host only needs SERVER_URL (+ API_KEY) — it holds no provider key (TASK-30).
#
# Usage: backend_host/scripts/test_banner.sh /path/to/frame.jpg

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
IMAGE="${1:?usage: test_banner.sh <image.jpg>}"

cd "$PROJECT_ROOT" || exit 1
set -a
for env_file in "$PROJECT_ROOT/.env" "$PROJECT_ROOT/backend_host/src/.env"; do
    [ -f "$env_file" ] && . "$env_file"
done
set +a

if [ -z "$SERVER_URL" ]; then
    echo "❌ Error: SERVER_URL not set (.env) — the banner call goes through the server AI gateway"
    exit 1
fi

python3 -c '
import json, sys
from shared.src.lib.utils.ai_utils import analyze_channel_banner_ai
print(json.dumps(analyze_channel_banner_ai(sys.argv[1], "test_banner"), indent=2))
' "$IMAGE"
