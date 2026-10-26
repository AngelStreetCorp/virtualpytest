#!/usr/bin/env bash
# faq_nightly.sh — the Atlas Prepared FAQ nightly pass (TASK-152).
#
# Two steps, in order:
#
#   1. faq_review.py --apply    promotes the eligible proposed rows to live. This is the
#                              self-promotion loop: a model answer that cited a docs path becomes
#                              a stored answer, reviewed twice >= 24 h apart, then live. The pass was
#                              written in phase 9b but never scheduled, so the proposed rows stayed
#                              proposed and the loop never advanced.
#
#   2. faq_alias_backfill.py    gives the rows that have no aliases a set of validated user
#     --topup                   wordings. Every candidate is checked before it is written: it must
#                              resolve to its own row, must not shadow another row's canonical
#                              question, must not steal a query another row already wins, and must
#                              not make a TASK-163 use-case prompt match the FAQ tier. The write
#                              touches the `aliases` column only — never an answer.
#
# Step 2 is best-effort: it needs the Anthropic key (the server reads it from the lab DB's
# secrets store) and the network, and a failure there must not stop the review of step 1.
#
# The .env is sourced here rather than through a systemd EnvironmentFile, because every other
# job on this box sources it the same way.
set -uo pipefail

REPO="${REPO:-/opt/virtualpytest}"
PY="${PY:-/opt/virtualpytest/venv/bin/python3}"
cd "$REPO" || exit 1

set -a
# shellcheck disable=SC1091
. "$REPO/.env"
set +a

echo "[faq-nightly] $(date -u +%FT%TZ) promoting reviewed proposed rows"
"$PY" scripts/agent/faq_review.py --apply
review_rc=$?
echo "[faq-nightly] review pass exit=$review_rc"

echo "[faq-nightly] topping up aliases for rows that have none"
"$PY" scripts/agent/faq_alias_backfill.py --topup --candidates /tmp/faq_alias_nightly.json
topup_rc=$?
echo "[faq-nightly] alias top-up exit=$topup_rc"

# A failed review is a real failure; a failed top-up is not (it retries tomorrow).
exit "$review_rc"
