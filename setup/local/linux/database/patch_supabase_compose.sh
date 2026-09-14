#!/bin/bash
#
# VirtualPyTest - Patch Supabase docker-compose to reduce RAM usage.
#
# By default (VPT_SUPABASE_MINIMAL=1), this disables services that commonly spawn
# large beam.smp processes (Erlang/Elixir), such as realtime and analytics/logflare.
#
# This script is intended to be called:
# - During install (before `supabase start`)
# - Via systemd ExecStartPre on each service start
#
# Usage:
#   ./patch_supabase_compose.sh [/data/supabase]
#
set -euo pipefail

SUPABASE_DATA_DIR="${1:-/data/supabase}"

if [[ "${VPT_SUPABASE_MINIMAL:-1}" != "1" ]]; then
  echo "ℹ️  VPT_SUPABASE_MINIMAL!=1, skipping Supabase compose patch."
  exit 0
fi

compose_candidates=(
  "$SUPABASE_DATA_DIR/supabase/docker-compose.yml"
  "$SUPABASE_DATA_DIR/supabase/docker-compose.yaml"
  "$SUPABASE_DATA_DIR/docker-compose.yml"
  "$SUPABASE_DATA_DIR/docker-compose.yaml"
)

COMPOSE_FILE=""
for c in "${compose_candidates[@]}"; do
  if [[ -f "$c" ]]; then
    COMPOSE_FILE="$c"
    break
  fi
done

if [[ -z "$COMPOSE_FILE" ]]; then
  # Supabase CLI installs have no compose file: the service set comes from supabase/config.toml
  echo "ℹ️  No Supabase docker-compose file under $SUPABASE_DATA_DIR (CLI install) — nothing to patch"
  exit 0
fi

echo "🧩 Patching Supabase compose for minimal mode: $COMPOSE_FILE"
backup="$COMPOSE_FILE.bak.$(date +%Y%m%d%H%M%S)"
cp "$COMPOSE_FILE" "$backup"
echo "🗄️  Backup: $backup"

# Services to disable (beam.smp heavy):
# - realtime: Supabase realtime subscriptions
# - analytics/logflare: logging/analytics stack (often Elixir)
#
# This removes the entire service block from the `services:` section and also
# drops references in `depends_on` lists/maps.
awk '
BEGIN {
  in_services=0;
  skip=0;
  remove["realtime"]=1;
  remove["analytics"]=1;
  remove["logflare"]=1;
}

function is_top_level(line) {
  return (line ~ /^[^[:space:]#]/);
}

{
  # Enter services section
  if ($0 ~ /^services:[[:space:]]*$/) {
    in_services=1;
    skip=0;
    print;
    next;
  }

  # Leave services section when a new top-level key starts
  if (in_services && is_top_level($0) && $0 !~ /^services:/) {
    in_services=0;
    skip=0;
  }

  # Drop depends_on references to removed services (common compose shapes)
  # - depends_on:
  #     - realtime
  # - depends_on:
  #     realtime:
  #       condition: service_healthy
  if ($0 ~ /^[[:space:]]+-[[:space:]]+(realtime|analytics|logflare)[[:space:]]*$/) {
    next;
  }
  if ($0 ~ /^[[:space:]]+(realtime|analytics|logflare):[[:space:]]*$/ && $0 !~ /^  (realtime|analytics|logflare):[[:space:]]*$/) {
    next;
  }

  if (in_services) {
    # Detect a service key at indent 2: "  name:"
    if (match($0, /^  ([A-Za-z0-9_-]+):[[:space:]]*$/, m)) {
      svc=m[1];
      if (remove[svc] == 1) {
        skip=1;
        next;
      } else {
        skip=0;
        print;
        next;
      }
    }

    if (skip == 1) {
      next;
    }
  }

  print;
}
' "$backup" > "$COMPOSE_FILE"

echo "✅ Supabase compose patched (disabled: realtime, analytics, logflare)"
echo "   To restore full stack: set VPT_SUPABASE_MINIMAL=0 and restore from backup if needed."

