#!/bin/bash
# VirtualPyTest — Docker stack launcher (Linux / macOS; Windows: run inside WSL2).
#
#   ./launch.sh                 bring the full stack up (builds images on first run)
#   ./launch.sh --host-only     device controller only, joining an existing server
#   ./launch.sh --rebuild       rebuild images (after a git pull or a VITE_* change)
#   ./launch.sh --down          stop everything (data volumes kept)
#   ./launch.sh --reset         stop everything AND delete the data volumes
#   ./launch.sh --logs          follow logs
#
# First run: copies .env.example -> .env, fills every CHANGE_ME with a generated
# secret, derives the Supabase ANON/SERVICE_ROLE keys from JWT_SECRET, and sets
# PUBLIC_HOST to this machine's LAN address. Nothing to edit before the first start.
#
# The backends build from this checkout by default. Set VPT_IMAGE_TAG in .env to a
# release tag to pull them prebuilt from GHCR instead (~10 min saved on a first run).

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
ENV_FILE="$SCRIPT_DIR/.env"
HOST_ENV="$PROJECT_ROOT/backend_host/src/.env"
# docker compose v1/v2 auto-reads .env from CWD; tell it where ours lives
export COMPOSE_ENV_FILE="$ENV_FILE"

MODE=full; ACTION=up; REBUILD=false
for arg in "$@"; do
    case "$arg" in
        --host-only) MODE=host ;;
        --rebuild)   REBUILD=true ;;
        --down)      ACTION=down ;;
        --reset)     ACTION=reset ;;
        --logs)      ACTION=logs ;;
        -h|--help)   sed -n 2,17p "$0"; exit 0 ;;
        *) echo "unknown option: $arg"; sed -n 2,17p "$0"; exit 1 ;;
    esac
done

# ---------------------------------------------------------------- prerequisites
if ! command -v docker >/dev/null 2>&1; then
    echo "❌ docker not found. Install it first: ./setup/docker/install_docker.sh"; exit 1
fi
if ! docker compose version >/dev/null 2>&1; then
    echo "❌ 'docker compose' (v2 plugin) not found. Install it first: ./setup/docker/install_docker.sh"; exit 1
fi
if ! docker info >/dev/null 2>&1; then
    echo "❌ the docker daemon is not running (or your user is not in the docker group)."; exit 1
fi

case "$(uname -s)" in
    Linux)  PLATFORM=linux ;;
    Darwin) PLATFORM=macos ;;
    *) echo "❌ unsupported platform $(uname -s). On Windows run this inside WSL2."; exit 1 ;;
esac

# ------------------------------------------------------------------ .env setup
rand_hex() { openssl rand -hex "${1:-32}"; }
b64url() { openssl base64 -e -A | tr '+/' '-_' | tr -d '='; }
# HS256 JWT for a Supabase role, signed with JWT_SECRET (what `supabase start` does)
make_jwt() {
    local role="$1" secret="$2" iat exp header payload sig
    iat=$(date +%s); exp=$((iat + 10 * 365 * 24 * 3600))
    header=$(printf '{"alg":"HS256","typ":"JWT"}' | b64url)
    payload=$(printf '{"role":"%s","iss":"supabase","iat":%d,"exp":%d}' "$role" "$iat" "$exp" | b64url)
    sig=$(printf '%s.%s' "$header" "$payload" | openssl dgst -sha256 -hmac "$secret" -binary | b64url)
    printf '%s.%s.%s' "$header" "$payload" "$sig"
}
set_env() {  # set_env KEY VALUE  (in-place, portable sed)
    local key="$1" value="$2" tmp
    tmp="$(mktemp)"
    awk -v k="$key" -v v="$value" 'BEGIN{FS=OFS="="} $1==k {print k "=" v; next} {print}' "$ENV_FILE" > "$tmp" && mv "$tmp" "$ENV_FILE"
}
get_env() { grep -E "^$1=" "$ENV_FILE" | head -1 | cut -d= -f2-; }
detect_lan_ip() {
    local ip=""
    if [ "$PLATFORM" = linux ]; then
        ip=$(hostname -I 2>/dev/null | awk '{print $1}')
    else
        ip=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || true)
    fi
    echo "${ip:-localhost}"
}

if [ ! -f "$ENV_FILE" ]; then
    cp "$SCRIPT_DIR/.env.example" "$ENV_FILE"
    echo "📝 created setup/docker/.env from .env.example"
    set_env PUBLIC_HOST "$(detect_lan_ip)"
fi

# Fill secrets (also fills any CHANGE_ME a user re-introduced by hand)
JWT_SECRET="$(get_env JWT_SECRET)"
if [ "$JWT_SECRET" = "CHANGE_ME" ] || [ -z "$JWT_SECRET" ]; then
    JWT_SECRET="$(rand_hex 32)"; set_env JWT_SECRET "$JWT_SECRET"
fi
for key in API_KEY FLASK_SECRET_KEY MCP_SECRET_KEY POSTGRES_PASSWORD DASHBOARD_PASSWORD \
           PG_META_CRYPTO_KEY MINIO_SECRET_KEY GRAFANA_ADMIN_PASSWORD GRAFANA_DB_PASSWORD; do
    if [ "$(get_env "$key")" = "CHANGE_ME" ]; then set_env "$key" "$(rand_hex 24)"; fi
done
[ "$(get_env ANON_KEY)" = "CHANGE_ME" ]         && set_env ANON_KEY "$(make_jwt anon "$JWT_SECRET")"
[ "$(get_env SERVICE_ROLE_KEY)" = "CHANGE_ME" ] && set_env SERVICE_ROLE_KEY "$(make_jwt service_role "$JWT_SECRET")"

# Device configuration for the host container
if [ ! -f "$HOST_ENV" ]; then
    cp "$PROJECT_ROOT/backend_host/src/.env.example" "$HOST_ENV"
    echo "📝 created backend_host/src/.env from its .env.example (VNC desktop capture enabled,"
    echo "   physical devices disabled — edit it to add DEVICE1_* and re-run ./launch.sh)"
fi

PUBLIC_HOST="$(get_env PUBLIC_HOST)"

# ---------------------------------------------------------------- compose args
if [ "$MODE" = host ]; then
    COMPOSE=(docker compose -f "$SCRIPT_DIR/docker-compose.host.yml" -f "$SCRIPT_DIR/docker-compose.$PLATFORM.yml")
else
    COMPOSE=(docker compose -f "$SCRIPT_DIR/docker-compose.yml" -f "$SCRIPT_DIR/docker-compose.$PLATFORM.yml")
fi

case "$ACTION" in
    down)  "${COMPOSE[@]}" down; exit 0 ;;
    reset) echo "⚠️  deleting containers AND data volumes (database, captures, MinIO, Grafana)"
           read -r -p "type 'yes' to continue: " ans; [ "$ans" = yes ] || exit 1
           "${COMPOSE[@]}" down -v; exit 0 ;;
    logs)  exec "${COMPOSE[@]}" logs -f ;;
esac

# ------------------------------------------------------------------------- up
echo "🚀 VirtualPyTest ($MODE stack, $PLATFORM) — PUBLIC_HOST=$PUBLIC_HOST"

# Prebuilt images from GHCR unless VPT_IMAGE_TAG=local (the default) or --rebuild was
# passed. All three are pullable: the frontend takes its VITE_* at runtime (its entrypoint
# writes dist/config.js from the environment), so one image serves any PUBLIC_HOST.
IMAGE_TAG="$(get_env VPT_IMAGE_TAG)"
if [ "$REBUILD" = true ] || [ -z "$IMAGE_TAG" ] || [ "$IMAGE_TAG" = local ]; then
    # --pull: re-fetch base images (python:3.11-slim, node:22-alpine, etc.) even if cached.
    # Separate "build" then "up -d" (no --build) so all parallel builds fully export to
    # Docker's image store before compose tries to create any container. The previous
    # "up -d --build" had a race: compose started containers while builds were still
    # exporting their image tarballs, causing "no such image" for the fastest service.
    [ "$REBUILD" = true ] && "${COMPOSE[@]}" build --pull
    "${COMPOSE[@]}" build
    "${COMPOSE[@]}" up -d
else
    echo "📦 pulling backend images tagged '$IMAGE_TAG' (set VPT_IMAGE_TAG=local in .env to build instead)"
    # docker-compose.host.yml defines backend_host only — asking for backend_server there
    # is a hard error, not a no-op.
    if [ "$MODE" = host ]; then PULL=(backend_host); else PULL=(backend_server backend_host frontend); fi
    if ! "${COMPOSE[@]}" pull "${PULL[@]}"; then
        echo "⚠️  pull failed for tag '$IMAGE_TAG' — falling back to building from this checkout"
        "${COMPOSE[@]}" build
        "${COMPOSE[@]}" up -d
    else
        "${COMPOSE[@]}" up -d
    fi
fi

# Wait for the API
if [ "$MODE" = host ]; then
    HEALTH="http://localhost:6109/host/health"
else
    HEALTH="http://localhost:5109/server/health"
fi
echo "⏳ waiting for $HEALTH ..."
for i in $(seq 1 90); do
    if curl -fs "$HEALTH" >/dev/null 2>&1; then echo "✅ up"; break; fi
    sleep 5
    if [ "$i" -eq 90 ]; then
        echo "❌ not healthy after 7.5 min. Inspect with: ./launch.sh --logs"
        "${COMPOSE[@]}" ps; exit 1
    fi
done

echo ""
"${COMPOSE[@]}" ps --format 'table {{.Name}}\t{{.Status}}'
echo ""
if [ "$MODE" = host ]; then
    echo "🎮 Host API      http://$PUBLIC_HOST:6109      noVNC http://$PUBLIC_HOST:6080/vnc_lite.html"
else
    echo "🌐 Web UI        http://$PUBLIC_HOST:5073"
    echo "🖥️  Server API    http://$PUBLIC_HOST:5109"
    echo "🎮 Host API      http://$PUBLIC_HOST:6109      noVNC http://$PUBLIC_HOST:6080/vnc_lite.html"
    echo "📊 Grafana       http://$PUBLIC_HOST:3000      (admin / see GRAFANA_ADMIN_PASSWORD in setup/docker/.env)"
    echo "🗄️  Supabase      http://$PUBLIC_HOST:$(get_env SUPABASE_API_PORT)     Studio login: $(get_env DASHBOARD_USERNAME) / DASHBOARD_PASSWORD in .env"
    echo "📦 MinIO console http://$PUBLIC_HOST:9001      ($(get_env MINIO_ACCESS_KEY) / MINIO_SECRET_KEY in .env)"
    if [ "$(get_env SERVER_OPEN_MODE)" = "true" ]; then
        echo ""
        echo "🚨 OPEN MODE: no login, every API call is accepted. Do not expose $PUBLIC_HOST to"
        echo "   the internet as-is. To enforce login see the auth block in setup/docker/.env."
    fi
fi
