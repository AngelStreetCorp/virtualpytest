#!/bin/bash
# write_env.sh — fill the three .env files with everything the installers already know.
#
#   setup/local/linux/shared/write_env.sh [--public-host <ip-or-name>] [--open-mode true|false]
#                                         [--with-storage] [--with-grafana]
#
# Idempotent: only placeholder values (CHANGE_ME / your_… / empty) are replaced, anything a
# user already set is kept. Writes:
#   <root>/.env               server-side config (Supabase keys, API_KEY, URLs, storage, auth posture)
#   backend_host/src/.env     host config (SERVER_URL, HOST_URL, API_KEY, Supabase keys)
#   frontend/.env             VITE_* build-time values (SERVER_URL, GRAFANA_URL, storage URL)
# Sources: config/database/local.env (written by database/install_supabase.sh), the running
# machine's LAN address, generated secrets. Called by install_all.sh / install_core.sh;
# safe to re-run after editing anything by hand.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../../../.." && pwd)"
cd "$PROJECT_ROOT"

PUBLIC_HOST=""; OPEN_MODE="true"; WITH_STORAGE=false; WITH_GRAFANA=false
while [ $# -gt 0 ]; do
    case "$1" in
        --public-host) PUBLIC_HOST="$2"; shift 2 ;;
        --open-mode)   OPEN_MODE="$2"; shift 2 ;;
        --with-storage) WITH_STORAGE=true; shift ;;
        --with-grafana) WITH_GRAFANA=true; shift ;;
        *) echo "unknown option: $1"; exit 1 ;;
    esac
done
if [ -z "$PUBLIC_HOST" ]; then
    PUBLIC_HOST="$(hostname -I 2>/dev/null | awk '{print $1}')"
    PUBLIC_HOST="${PUBLIC_HOST:-localhost}"
fi

ROOT_ENV="$PROJECT_ROOT/.env"
HOST_ENV="$PROJECT_ROOT/backend_host/src/.env"
FE_ENV="$PROJECT_ROOT/frontend/.env"

# ------------------------------------------------------------------ helpers
# Files under /opt/virtualpytest belong to vpt_user; write through sudo when needed.
write_file() {  # write_file <path>  (content on stdin)
    local path="$1"
    if [ -w "$path" ] || { [ ! -e "$path" ] && [ -w "$(dirname "$path")" ]; }; then
        cat > "$path"
    elif id vpt_user >/dev/null 2>&1; then
        sudo -u vpt_user tee "$path" >/dev/null
    else
        sudo tee "$path" >/dev/null
    fi
}
ensure_from_example() {  # ensure_from_example <file> <example>
    [ -s "$1" ] && return 0     # an empty file counts as missing
    [ -f "$2" ] || { echo "⚠️  no $2 — cannot create $1"; return 0; }
    write_file "$1" < "$2"; echo "📝 created $1 from $(basename "$2")"
}
get_env() { { grep -E "^$2=" "$1" 2>/dev/null || true; } | head -1 | cut -d= -f2- | sed -E 's/[[:space:]]+#.*$//; s/^"(.*)"$/\1/'; }
is_placeholder() {  # true when the value is empty or a template placeholder
    local v="$1"
    [ -z "$v" ] || [[ "$v" == '${'* ]] || [[ "$v" == CHANGE_ME* ]] || [[ "$v" == your* ]] || [[ "$v" == *your_* ]] || [[ "$v" == *your-* ]] || \
    [[ "$v" == *xxxx* ]] || [[ "$v" == *YOUR_* ]] || [[ "$v" == *example.com* ]] || [[ "$v" == *"[YOUR-"* ]]
}
# set_env <file> <key> <value>: replace the live `KEY=` line (also uncomments `# KEY=` / `xKEY=`
# forms) or append. Never touches a key whose current value is not a placeholder unless FORCE=1.
set_env() {
    local file="$1" key="$2" value="$3" current tmp
    current="$(get_env "$file" "$key")"
    # Build the new content in a temp file first: piping awk's output straight into the
    # file it is reading truncates the input mid-read and leaves an empty .env behind.
    tmp="$(mktemp)"
    if grep -qE "^$key=" "$file"; then
        if [ "${FORCE:-0}" != 1 ] && ! is_placeholder "$current"; then rm -f "$tmp"; return 0; fi
        awk -v k="$key" -v v="$value" 'BEGIN{done=0} { if (!done && index($0, k "=")==1) { print k "=" v; done=1 } else print }' "$file" > "$tmp"
    elif grep -qE "^(# ?|x)$key=" "$file"; then
        awk -v k="$key" -v v="$value" 'BEGIN{done=0} { if (!done && ($0 ~ "^(# ?|x)" k "=")) { print k "=" v; done=1 } else print }' "$file" > "$tmp"
    else
        { cat "$file"; echo "$key=$value"; } > "$tmp"
    fi
    write_file "$file" < "$tmp"
    rm -f "$tmp"
}
secret() { openssl rand -hex 32; }

# ------------------------------------------------------------------ files exist
ensure_from_example "$ROOT_ENV" "$PROJECT_ROOT/.env.example"
ensure_from_example "$HOST_ENV" "$PROJECT_ROOT/backend_host/src/.env.example"
ensure_from_example "$FE_ENV"   "$PROJECT_ROOT/frontend/.env.example"

# ------------------------------------------------------------------ secrets (shared)
API_KEY="$(get_env "$ROOT_ENV" API_KEY)"
if is_placeholder "$API_KEY"; then API_KEY="$(secret)"; fi
set_env "$ROOT_ENV" API_KEY "$API_KEY"
FORCE=1 set_env "$HOST_ENV" API_KEY "$API_KEY"          # host and server MUST share it
set_env "$ROOT_ENV" FLASK_SECRET_KEY "$(secret)"
set_env "$ROOT_ENV" MCP_SECRET_KEY "vpt_mcp_$(secret)"
set_env "$ROOT_ENV" AUTO_SIGN_ENABLED "false"

# ------------------------------------------------------------------ Supabase
DB_LOCAL_ENV="$PROJECT_ROOT/config/database/local.env"
if [ -f "$DB_LOCAL_ENV" ]; then
    # shellcheck disable=SC1090
    SB_URL="$(get_env "$DB_LOCAL_ENV" SUPABASE_URL)"
    SB_ANON="$(get_env "$DB_LOCAL_ENV" SUPABASE_ANON_KEY)"
    SB_SERVICE="$(get_env "$DB_LOCAL_ENV" SUPABASE_SERVICE_ROLE_KEY)"
    SB_JWT="$(get_env "$DB_LOCAL_ENV" SUPABASE_JWT_SECRET)"
    SB_DB_URI="$(get_env "$DB_LOCAL_ENV" VIRTUALPYTEST_DB_URI)"
    for pair in "SUPABASE_URL=${SB_URL:-http://localhost:54321}" "SUPABASE_ANON_KEY=$SB_ANON" \
                "SUPABASE_SERVICE_ROLE_KEY=$SB_SERVICE" "SUPABASE_JWT_SECRET=$SB_JWT" \
                "SUPABASE_DB_URI=${SB_DB_URI:-postgresql://postgres:postgres@localhost:54322/postgres}"; do
        k="${pair%%=*}"; v="${pair#*=}"
        [ -n "$v" ] && ! is_placeholder "$v" && { FORCE=1 set_env "$ROOT_ENV" "$k" "$v"; }
    done
    for k in SUPABASE_URL SUPABASE_ANON_KEY SUPABASE_SERVICE_ROLE_KEY; do
        v="$(get_env "$ROOT_ENV" "$k")"; [ -n "$v" ] && FORCE=1 set_env "$HOST_ENV" "$k" "$v"
    done
    echo "🗄️  Supabase values taken from $DB_LOCAL_ENV"
else
    echo "ℹ️  no config/database/local.env (database not installed on this machine) — set SUPABASE_* in .env by hand"
fi

# ------------------------------------------------------------------ auth posture
FORCE=1 set_env "$ROOT_ENV" SERVER_OPEN_MODE "$OPEN_MODE"

# ------------------------------------------------------------------ URLs
FORCE=1 set_env "$ROOT_ENV" SERVER_URL "http://$PUBLIC_HOST:5109"
set_env "$ROOT_ENV" SERVER_PORT "5109"
set_env "$ROOT_ENV" SERVER_NAME "vpt-$(hostname -s 2>/dev/null || echo server)"
FORCE=1 set_env "$HOST_ENV" SERVER_URL "http://localhost:5109"
FORCE=1 set_env "$HOST_ENV" HOST_URL "http://$PUBLIC_HOST:6109"
FORCE=1 set_env "$HOST_ENV" HOST_API_URL "http://localhost:6109"
set_env "$HOST_ENV" HOST_BIND_IP "0.0.0.0"          # listen on every interface: the UI reaches the host at HOST_URL
set_env "$HOST_ENV" HOST_NAME "$(hostname -s 2>/dev/null || echo host1)"
# browser-facing VNC page: keep the port/path the example gives, swap the address
vnc="$(get_env "$HOST_ENV" HOST_VNC_STREAM_PATH)"
if [[ "$vnc" == *localhost* ]] && [ "$PUBLIC_HOST" != localhost ]; then
    FORCE=1 set_env "$HOST_ENV" HOST_VNC_STREAM_PATH "${vnc//localhost/$PUBLIC_HOST}"
fi
FORCE=1 set_env "$FE_ENV" VITE_SERVER_URL "http://$PUBLIC_HOST:5109"
FORCE=1 set_env "$FE_ENV" VITE_DEV_MODE "false"
if [ "$WITH_GRAFANA" = true ]; then
    FORCE=1 set_env "$ROOT_ENV" GRAFANA_URL "http://localhost:3000"
    FORCE=1 set_env "$FE_ENV" VITE_GRAFANA_URL "http://$PUBLIC_HOST:3000"
    set_env "$ROOT_ENV" GRAFANA_ADMIN_USER "admin"
    set_env "$ROOT_ENV" GRAFANA_ADMIN_PASSWORD "$(openssl rand -hex 12)"
fi

# ------------------------------------------------------------------ storage (MinIO + Redis from storage/install_storage.sh)
# This file is where the MinIO and Redis passwords are decided; install_minio.sh and
# install_redis.sh configure the services from these values rather than carrying their
# own. Both are generated per install — they used to be one fixed literal in a public repo,
# i.e. the same credential on every deployment in the world.
#
# An install that already has a value keeps it: `set_env` without FORCE only replaces a
# placeholder, and the two reads below recover an existing password so a re-run cannot
# leave the service and the .env disagreeing.
if [ "$WITH_STORAGE" = true ]; then
    MINIO_SECRET="$(get_env "$ROOT_ENV" MINIO_SECRET_KEY)"
    if is_placeholder "$MINIO_SECRET"; then MINIO_SECRET="$(secret)"; fi

    REDIS_PASS="$(get_env "$ROOT_ENV" REDIS_PASSWORD)"
    if is_placeholder "$REDIS_PASS"; then
        # Installs made before REDIS_PASSWORD existed carry it only inside REDIS_URL.
        REDIS_PASS="$(get_env "$ROOT_ENV" REDIS_URL | sed -nE 's|^redis://[^:]*:([^@]+)@.*|\1|p')"
        if is_placeholder "$REDIS_PASS"; then REDIS_PASS="$(secret)"; fi
    fi

    for pair in "MINIO_ENDPOINT=http://localhost:9000" "MINIO_ACCESS_KEY=admin" \
                "MINIO_BUCKET=virtualpytest" "MINIO_PUBLIC_URL=http://$PUBLIC_HOST:9000"; do
        set_env "$ROOT_ENV" "${pair%%=*}" "${pair#*=}"
        set_env "$HOST_ENV" "${pair%%=*}" "${pair#*=}"
    done
    # Server, host and the MinIO service itself must agree, like API_KEY does.
    FORCE=1 set_env "$ROOT_ENV" MINIO_SECRET_KEY "$MINIO_SECRET"
    FORCE=1 set_env "$HOST_ENV" MINIO_SECRET_KEY "$MINIO_SECRET"
    # install_redis.sh reads this; REDIS_URL is what the app uses.
    FORCE=1 set_env "$ROOT_ENV" REDIS_PASSWORD "$REDIS_PASS"
    # Only (re)write the URL while it is still the shipped placeholder: on a fleet install
    # it points at the storage VM, not localhost, and that must survive a re-run.
    case "$(get_env "$ROOT_ENV" REDIS_URL)" in
        ""|*CHANGE_ME*) FORCE=1 set_env "$ROOT_ENV" REDIS_URL "redis://:$REDIS_PASS@localhost:6379/0" ;;
    esac
    set_env "$FE_ENV" VITE_CLOUDFLARE_R2_PUBLIC_URL "http://$PUBLIC_HOST:9000/virtualpytest"
fi

echo "✅ .env files written (PUBLIC_HOST=$PUBLIC_HOST, SERVER_OPEN_MODE=$OPEN_MODE)"
echo "   $ROOT_ENV · $HOST_ENV · $FE_ENV"
