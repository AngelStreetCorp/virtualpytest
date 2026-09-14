#!/bin/bash
# Export example_tv UI definition (+ stb variant + references) from the dev Supabase,
# reached via: ssh <alias> -> docker exec supabase_db_supabase -> psql.
# Streams CSVs to a local OUTDIR. Run with --dry-run first to preview row counts.
#
#   SUDO_PASSWORD=*** ./export_ui.sh --dry-run     # verify scope, writes nothing
#   SUDO_PASSWORD=*** ./export_ui.sh               # actually export to ./out (+ blobs/)
set -euo pipefail

SSH_ALIAS="${SSH_ALIAS:-database}"
CONTAINER="${CONTAINER:-supabase_db_supabase}"
UI_NAME="${UI_NAME:-example_tv}"
VARIANT="${VARIANT:-stb}"
OUTDIR="${OUTDIR:-./out}"
# MinIO (object storage) — reached via a separate VM that can see the bucket.
STORAGE_ALIAS="${STORAGE_ALIAS:-storage}"   # ssh alias of a host with mc + bucket access
MC_ALIAS="${MC_ALIAS:-local}"               # preconfigured mc alias on that host
MINIO_BUCKET="${MINIO_BUCKET:-virtualpytest}"
: "${SUDO_PASSWORD:?set SUDO_PASSWORD env var}"

DRY=0; [ "${1:-}" = "--dry-run" ] && DRY=1

# Run SQL inside the container. SQL comes via stdin (after the sudo password line).
# Extra psql flags passed as $2 (e.g. "-tA"). stderr -> /dev/null (suppress sudo prompt).
run_sql() {
  local sql="$1"; local flags="${2:-}"
  (printf '%s\n' "$SUDO_PASSWORD"; printf '%s\n' "$sql") \
    | ssh "$SSH_ALIAS" "sudo -S -p '' docker exec -i -e PGPASSWORD=postgres $CONTAINER \
        psql -U supabase_admin -d postgres -v ON_ERROR_STOP=1 $flags" 2>/dev/null
}

# Resolve UI id + team id.
read -r UI_ID TEAM_ID < <(run_sql \
  "SELECT id, team_id FROM userinterfaces WHERE name='$UI_NAME' LIMIT 1;" "-tA -F' '" | tr -d '\r')
[ -z "${UI_ID:-}" ] && { echo "ERROR: no UI named '$UI_NAME'"; exit 1; }
echo "UI '$UI_NAME' -> id=$UI_ID  team_id=$TEAM_ID"

TREES_SUBQ="SELECT id FROM navigation_trees WHERE userinterface_id='$UI_ID'"

# bash 3.2 (macOS) has no associative arrays — use a function instead.
where_for() {
  case "$1" in
    userinterfaces)           echo "name='$UI_NAME'";;
    navigation_trees)         echo "userinterface_id='$UI_ID'";;
    navigation_nodes)         echo "tree_id IN ($TREES_SUBQ)";;
    navigation_edges)         echo "tree_id IN ($TREES_SUBQ)";;
    userinterface_variants)   echo "userinterface_id='$UI_ID' AND name='$VARIANT'";;
    verifications_references) echo "userinterface_name='$UI_NAME' OR userinterface_id='$UI_ID'";;
  esac
}
REFS_WHERE="userinterface_name='$UI_NAME' OR userinterface_id='$UI_ID'"
ORDER="userinterfaces navigation_trees navigation_nodes navigation_edges userinterface_variants verifications_references"

if [ "$DRY" = "1" ]; then
  echo "--- DRY RUN: rows that WOULD be exported (no files written) ---"
  for t in $ORDER; do
    n=$(run_sql "SELECT count(*) FROM $t WHERE $(where_for "$t");" "-tA" | tr -d '\r ')
    printf '  %-26s %s\n' "$t" "$n"
  done
  echo "--- MinIO objects that would be copied ---"
  run_sql "SELECT DISTINCT r2_path FROM verifications_references
            WHERE $REFS_WHERE ORDER BY 1;" "-tA" | sed 's/^/  /'
  exit 0
fi

mkdir -p "$OUTDIR"
printf 'UI_ID=%s\nTEAM_ID=%s\nUI_NAME=%s\nVARIANT=%s\n' \
  "$UI_ID" "$TEAM_ID" "$UI_NAME" "$VARIANT" > "$OUTDIR/manifest.env"

echo "--- Exporting to $OUTDIR ---"
for t in $ORDER; do
  cols=$(run_sql "SELECT string_agg(quote_ident(column_name),',' ORDER BY ordinal_position)
                    FROM information_schema.columns
                   WHERE table_schema='public' AND table_name='$t';" "-tA" | tr -d '\r')
  echo "$cols" > "$OUTDIR/$t.cols"
  run_sql "COPY (SELECT $cols FROM $t WHERE $(where_for "$t")) TO STDOUT WITH (FORMAT csv, HEADER true);" \
    > "$OUTDIR/$t.csv"
  rows=$(( $(wc -l < "$OUTDIR/$t.csv") - 1 ))
  # Sanity: header column count vs requested column count.
  hdr=$(head -1 "$OUTDIR/$t.csv" | tr ',' '\n' | wc -l | tr -d ' ')
  want=$(echo "$cols" | tr ',' '\n' | wc -l | tr -d ' ')
  flag=""; [ "$hdr" != "$want" ] && flag="  ⚠ header cols $hdr != $want"
  printf '  %-26s %s rows%s\n' "$t" "$rows" "$flag"
done

run_sql "SELECT DISTINCT r2_path FROM verifications_references
          WHERE $REFS_WHERE ORDER BY 1;" "-tA" \
  | tr -d '\r' | sed '/^$/d' > "$OUTDIR/r2_paths.txt"
echo "  r2 objects listed: $(wc -l < "$OUTDIR/r2_paths.txt")  -> $OUTDIR/r2_paths.txt"

# --- Download the MinIO objects so out/ is a self-contained bundle ---------
# Mirror by PREFIX (not by individual r2_path) so companion variants the
# verification engine uses (_binary / _greyscale, etc.) come along too.
# Prefixes: the verification references from r2_paths.txt (reference-images/<ui>,
# text-references/<ui>) PLUS navigation/<ui> — the per-node screenshot thumbnails,
# which the canvas requests via node.data.screenshot but which live under their own
# prefix (not in verifications_references).
echo "--- Downloading MinIO objects into $OUTDIR/blobs/ (via $STORAGE_ALIAS) ---"
PREFIXES=$( { sed 's#/[^/]*$##' "$OUTDIR/r2_paths.txt"; echo "navigation/$UI_NAME"; } | sort -u)
mkdir -p "$OUTDIR/blobs"
for p in $PREFIXES; do
  # Mirror the prefix on the storage host to /tmp, then stream it back as tar.
  ssh "$STORAGE_ALIAS" "
    rm -rf /tmp/ui_blobs && mkdir -p /tmp/ui_blobs/$p &&
    mc mirror --quiet --overwrite '$MC_ALIAS/$MINIO_BUCKET/$p' '/tmp/ui_blobs/$p' >/dev/null 2>&1 || true;
    tar -C /tmp/ui_blobs -cf - '$p' 2>/dev/null || true
  " | tar -C "$OUTDIR/blobs" -xf - 2>/dev/null || true
  n=$(find "$OUTDIR/blobs/$p" -type f 2>/dev/null | wc -l | tr -d ' ')
  printf '  %-40s %s files\n' "$p" "$n"
done
TOTAL=$(find "$OUTDIR/blobs" -type f 2>/dev/null | wc -l | tr -d ' ')
echo "  total objects downloaded: $TOTAL"
echo "Done. Transfer $OUTDIR/ (incl. blobs/) to the prod network, then run import_ui.sh + push_blobs.sh."
