#!/bin/bash
# Docs path checker — every repo path a doc names must exist.
#
#   scripts/docs/check_paths.sh                 # default scope (see SCOPE below)
#   scripts/docs/check_paths.sh docs setup README.md   # explicit files/dirs
#
# Scans markdown (prose, backticks and fenced code blocks) for tokens that look like repo paths
# (setup/…, docs/…, scripts/…, backend_*/…, frontend/…, shared/…, infra/…,
# test_scripts/…, features/…) and fails when the target does not exist.
# Tokens containing glob / template characters (* < > { } $ … NN) are ignored.
# Runs in CI (regression.yml → docs-paths). Exit 1 on any missing path.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

# Scope grows as folders are brought up to date (TASK-15 §5).
SCOPE=("$@")
if [ ${#SCOPE[@]} -eq 0 ]; then
    SCOPE=(README.md docs/README.md docs/INDEX.md docs/get-started docs/user-guide docs/faq docs/features
           setup/README.md setup/docker/README.md setup/docker/supabase setup/proxmox/README.md
           setup/proxmox/node/README.md setup/proxmox/vm/README.md setup/local/linux/install_all.md
           setup/local/linux/launch_core.md setup/local/windows/README.md setup/local/macos/README.md)
fi
# Files that exist only at runtime (generated / git-ignored) but are legitimately documented.
GENERATED='^(setup/docker/\.env|setup/docker/hetzner_custom/config\.env|backend_host/src/\.env|frontend/\.env|frontend/\.env\.local|frontend/\.env\.production|frontend/public/brand/.*|frontend/public/analytics/.*|frontend/node_modules/?|frontend/dist/?|venv/?|\.env)$'

PREFIXES='setup|docs|scripts|backend_server|backend_host|frontend|shared|infra|test_scripts|test_campaign|features'

files=()
for s in "${SCOPE[@]}"; do
    [ -e "$s" ] || { echo "⚠️  scope entry not found: $s"; continue; }
    if [ -d "$s" ]; then
        while IFS= read -r f; do files+=("$f"); done < <(find "$s" -name '*.md' -type f | sort)
    else
        files+=("$s")
    fi
done

missing=0; checked=0
for f in "${files[@]}"; do
    # tokens starting with a known top-level dir (backticks, prose, code blocks)
    while IFS= read -r tok; do
        # strip trailing punctuation and a leading ./ ; skip absolute (VM) paths and templates
        tok="${tok#./}"; tok="${tok%%[),.:;]}"
        case "$tok" in /*|*'*'*|*'<'*|*'>'*|*'{'*|*'}'*|*'$'*|*'…'*|*NN*|*XXXX*) continue ;; esac
        # a path may be given with a :line suffix
        path="${tok%%:*}"
        checked=$((checked + 1))
        if [[ "$path" =~ $GENERATED ]]; then continue; fi
        # accept repo-root paths and paths relative to the doc's own directory
        if [ ! -e "$path" ] && [ ! -e "$(dirname "$f")/$path" ]; then
            echo "❌ $f → \`$tok\`"
            missing=$((missing + 1))
        fi
    done < <(grep -oE '(^|[[:space:]`"'"'"'(=])\.?/?('"$PREFIXES"')/[A-Za-z0-9_./-]+' "$f" | sed -E 's/^[[:space:]`"'"'"'(=]//' | sort -u)

    # relative markdown links: [text](./other.md#anchor), [text](../dir/file.md)
    while IFS= read -r link; do
        link="${link%%#*}"; [ -z "$link" ] && continue
        case "$link" in http*|mailto:*|/*) continue ;; esac
        checked=$((checked + 1))
        if [ ! -e "$(dirname "$f")/$link" ]; then
            echo "❌ $f → link ($link)"
            missing=$((missing + 1))
        fi
    done < <(grep -oE '\]\([^) ]+\)' "$f" | sed -E 's/^\]\(//; s/\)$//' | grep -E '\.(md|html|json|yaml|yml|sh|py)(#|$)' | sort -u)
done

echo ""
echo "checked $checked path references in ${#files[@]} files — $missing missing"
[ "$missing" -eq 0 ]
