#!/bin/bash
# Push the exported MinIO objects (out/blobs/) to the DESTINATION object store.
# Run on any host with `mc` that can reach the destination (e.g. the prod storage VM).
#
# Pick ONE credential source:
#   A) ENV_FILE — read MINIO_* (or CLOUDFLARE_R2_*) from a deployment .env:
#        ENV_FILE=/opt/virtualpytest/.env OUTDIR=./out ./push_blobs.sh
#   B) MC_ALIAS — reuse an already-configured mc alias on this host:
#        MC_ALIAS=local MINIO_BUCKET=virtualpytest OUTDIR=./out ./push_blobs.sh
#   C) discrete vars:
#        PROD_MINIO_ENDPOINT=http://host:9000 PROD_MINIO_ACCESS=ak PROD_MINIO_SECRET=sk \
#        PROD_BUCKET=virtualpytest OUTDIR=./out ./push_blobs.sh
set -euo pipefail

OUTDIR="${OUTDIR:-./out}"
command -v mc >/dev/null || { echo "ERROR: mc (MinIO client) not installed"; exit 1; }
[ -d "$OUTDIR/blobs" ] || { echo "ERROR: no $OUTDIR/blobs (run export_ui.sh first)"; exit 1; }

env_val() { grep -E "^$2=" "$1" 2>/dev/null | tail -1 | cut -d= -f2- | tr -d '"'"'"'\r'; }
# Treat unconfigured placeholders (e.g. CLOUDFLARE_R2_ACCESS_KEY_ID=your_r2_...) as empty.
real() { case "$1" in your_*|YOUR_*|""|changeme*|"<"*) return 1;; *) return 0;; esac; }

# Read object-store creds from one .env file into PROD_MINIO_* (prefer MINIO_*, else R2_*).
load_creds() {  # $1 = env file
  local ep ak sk bk
  ep="$(env_val "$1" MINIO_ENDPOINT)"; ak="$(env_val "$1" MINIO_ACCESS_KEY)"
  sk="$(env_val "$1" MINIO_SECRET_KEY)"; bk="$(env_val "$1" MINIO_BUCKET)"
  if ! { real "$ep" && real "$ak" && real "$sk"; }; then
    ep="$(env_val "$1" CLOUDFLARE_R2_ENDPOINT)"; ak="$(env_val "$1" CLOUDFLARE_R2_ACCESS_KEY_ID)"
    sk="$(env_val "$1" CLOUDFLARE_R2_SECRET_ACCESS_KEY)"
  fi
  real "$ep" && real "$ak" && real "$sk" || return 1
  PROD_MINIO_ENDPOINT="$ep"; PROD_MINIO_ACCESS="$ak"; PROD_MINIO_SECRET="$sk"
  [ -n "$bk" ] && PROD_BUCKET="${PROD_BUCKET:-$bk}"
}

# Deployment .env location AND which keys are populated vary per VM. Pick the first
# candidate that yields usable creds. Skipped when MC_ALIAS / explicit creds are given.
ENV_CANDIDATES="${ENV_CANDIDATES:-/opt/virtualpytest/.env /shared/code/virtualpytest/.env ./.env}"
if [ -z "${MC_ALIAS:-}" ] && [ -z "${PROD_MINIO_ENDPOINT:-}" ]; then
  if [ -n "${ENV_FILE:-}" ]; then
    [ -r "$ENV_FILE" ] || { echo "ERROR: ENV_FILE not readable: $ENV_FILE" >&2; exit 1; }
    load_creds "$ENV_FILE" || { echo "ERROR: no usable MINIO_*/CLOUDFLARE_R2_* creds in $ENV_FILE" >&2; exit 1; }
    echo "Using ENV_FILE for MinIO: $ENV_FILE"
  else
    for f in $ENV_CANDIDATES; do
      [ -r "$f" ] || continue
      if load_creds "$f"; then echo "Using ENV_FILE for MinIO: $f"; break; fi
    done
  fi
fi

PROD_BUCKET="${PROD_BUCKET:-virtualpytest}"

if [ -n "${MC_ALIAS:-}" ]; then
  ALIAS="$MC_ALIAS"
  mc ls "$ALIAS" >/dev/null 2>&1 || { echo "ERROR: mc alias '$ALIAS' not configured here" >&2; exit 1; }
else
  : "${PROD_MINIO_ENDPOINT:?need ENV_FILE, MC_ALIAS, or PROD_MINIO_ENDPOINT}"
  : "${PROD_MINIO_ACCESS:?need MinIO access key}"
  : "${PROD_MINIO_SECRET:?need MinIO secret key}"
  ALIAS="vptdst"
  mc alias set "$ALIAS" "$PROD_MINIO_ENDPOINT" "$PROD_MINIO_ACCESS" "$PROD_MINIO_SECRET" >/dev/null
fi

mc mb -p "$ALIAS/$PROD_BUCKET" >/dev/null 2>&1 || true   # create bucket if missing

# `cp --recursive` (not `mirror`) — preserves reference-images/<ui>/... paths so they match
# r2_path, and avoids mirror's destination diff-scan which can stall against some MinIO setups.
echo "Pushing $(find "$OUTDIR/blobs" -type f | wc -l | tr -d ' ') objects -> $ALIAS/$PROD_BUCKET/ ..."
mc cp --recursive "$OUTDIR/blobs/" "$ALIAS/$PROD_BUCKET/"
echo "Done."
