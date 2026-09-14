#!/bin/bash

# VirtualPyTest - Reverse Proxy Smoke Test (Nginx)

set -e

BASE_URL="${1:-http://127.0.0.1}"

echo "🧪 Testing VirtualPyTest Reverse Proxy"
echo "   Base URL: $BASE_URL"
echo ""

echo "1️⃣ Nginx config test..."
if command -v nginx >/dev/null 2>&1; then
    nginx -t
elif [ -x "/usr/sbin/nginx" ]; then
    sudo /usr/sbin/nginx -t
else
    echo "❌ nginx not found (checked PATH and /usr/sbin/nginx)"
    exit 1
fi

echo ""
echo "2️⃣ HTTP route checks..."

check_url() {
    local path="$1"
    local url="${BASE_URL}${path}"
    local code
    code=$(curl -s -o /dev/null -w "%{http_code}" "$url" || true)
    if [ "$code" = "200" ] || [ "$code" = "301" ] || [ "$code" = "302" ]; then
        echo "✅ $path -> $code"
    else
        echo "⚠️  $path -> $code (service may be down)"
    fi
}

check_url "/"
check_url "/server/"
check_url "/host/"
check_url "/grafana/"

echo ""
echo "✅ Proxy smoke test completed"
