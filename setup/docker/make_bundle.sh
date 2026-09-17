#!/bin/bash
# Build the standalone Docker bundle — the release asset a user downloads instead of
# cloning the repo.
#
#   ./setup/docker/make_bundle.sh [--tag <release-tag>] [--out <dir>]
#
# The clone is ~330 MB of git history to reach ~4 MB of files. The stack bind-mounts
# config out of the checkout (the Supabase Envoy + init SQL, setup/db's schema, the
# Grafana dashboards and entrypoint, the shipped test scripts), so those paths have to
# exist — but nothing else does.
#
# The bundle therefore keeps the SAME relative layout the compose files expect, which is
# why no compose path has to change and why `./setup/docker/launch.sh` works identically
# inside it:
#
#   vpt-docker-<tag>/
#     setup/docker/…          compose files, launch.sh, Supabase config, grafana entrypoint
#     setup/db/…              the schema db-init applies
#     infra/monitoring/grafana/dashboards/…
#     backend_host/src/.env.example    device config (launch.sh copies it to .env)
#     test_scripts/ test_campaign/     the shipped tests
#     README.md               three commands
#
# Deliberately excluded: setup/docker/.env (secrets, per install), hetzner_custom (a
# legacy dev variant nothing in the compose references), and the repo's git history.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

TAG=""
OUT_DIR="$PROJECT_ROOT/dist"
while [ $# -gt 0 ]; do
    case "$1" in
        --tag) TAG="$2"; shift 2 ;;
        --out) OUT_DIR="$2"; shift 2 ;;
        -h|--help) sed -n 2,6p "$0"; exit 0 ;;
        *) echo "unknown option: $1"; exit 1 ;;
    esac
done
if [ -z "$TAG" ]; then
    TAG="$(git -C "$PROJECT_ROOT" describe --tags --exact-match 2>/dev/null || echo "dev-$(date -u +%Y%m%d)")"
fi

NAME="vpt-docker-$TAG"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
ROOT="$STAGE/$NAME"

echo "📦 building $NAME"

# --- the paths the compose files actually mount -----------------------------------
mkdir -p "$ROOT/setup/docker" "$ROOT/backend_host/src" "$ROOT/infra/monitoring/grafana"

# setup/docker, minus the live .env and the legacy dev variant
for item in docker-compose.yml docker-compose.linux.yml docker-compose.macos.yml \
            docker-compose.host.yml .env.example launch.sh install_docker.sh README.md \
            grafana scripts supabase installers; do
    cp -R "$SCRIPT_DIR/$item" "$ROOT/setup/docker/"
done
rm -f "$ROOT/setup/docker/.env"

cp -R "$PROJECT_ROOT/setup/db" "$ROOT/setup/"
cp -R "$PROJECT_ROOT/infra/monitoring/grafana/dashboards" "$ROOT/infra/monitoring/grafana/"
cp "$PROJECT_ROOT/backend_host/src/.env.example" "$ROOT/backend_host/src/.env.example"
cp -R "$PROJECT_ROOT/test_scripts" "$ROOT/"
cp -R "$PROJECT_ROOT/test_campaign" "$ROOT/"

# Nothing generated or secret travels with the bundle.
find "$ROOT" -name '.env' -delete
find "$ROOT" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
find "$ROOT" -name '*.pyc' -delete 2>/dev/null || true

# --- the bundle's own README ------------------------------------------------------
cat > "$ROOT/README.md" << EOF
# VirtualPyTest — standalone Docker bundle ($TAG)

The whole platform on this machine: web UI, server API, one device controller with a
browser and a VNC desktop, Supabase (Postgres + auth + REST + Studio), MinIO, Redis and
Grafana.

## Run it

\`\`\`bash
./setup/docker/install_docker.sh   # only if Docker is not installed yet
./setup/docker/launch.sh
\`\`\`

\`launch.sh\` generates every secret, detects this machine's address, pulls the prebuilt
backend images for $TAG, builds the frontend, applies the schema and prints the URLs.
Nothing to edit first.

## Adding a real device

\`backend_host/src/.env\` is **the only file you edit.** It ships with the browser and VNC
desktop enabled and physical devices off — every \`DEVICE1_*\` line is prefixed with \`x\`
to disable it. Drop the \`x\`, set your device's address, and re-run \`./setup/docker/launch.sh\`.

## Notes

- Requires 4 CPU / 8 GB RAM / 30 GB free disk, and Linux or macOS (Windows: use WSL2).
- The stack starts in **open mode**: no login, every API call accepted. Keep it on a
  trusted network, or enable login — \`launch.sh\` prints the warning and points at the docs.
- Full documentation: https://github.com/AngelStreetCorp/virtualpytest
EOF

# --- pack ------------------------------------------------------------------------
mkdir -p "$OUT_DIR"
TARBALL="$OUT_DIR/$NAME.tar.gz"
rm -f "$TARBALL"
tar -czf "$TARBALL" -C "$STAGE" "$NAME"

echo "✅ $TARBALL"
echo "   $(du -h "$TARBALL" | cut -f1) · $(find "$ROOT" -type f | wc -l | tr -d ' ') files"
