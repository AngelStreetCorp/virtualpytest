#!/usr/bin/env python3
"""
Import a legacy script_identity_map.json into the executable_identity table.

The TCnnn prefix and display name used to live in two hand-edited JSON files
(test_scripts/script_identity_map.json for the server, its twin under
frontend/public/data/ for the browser — BUG-0066). They are now DB rows,
editable from the Test Cases page. This is the one-shot cutover: it reads an
existing map and POSTs it to /server/script-identity/import.

Idempotent — re-running skips refs that already have a row, unless --overwrite.

─────────────────────────────────────────────────────────────────────────────
RUN
─────────────────────────────────────────────────────────────────────────────
  SERVER_URL=http://localhost:5109 \
  API_KEY=<key> \
  python3 scripts/import_script_identity_map.py --dry-run

  # a customer's map, from wherever it lives
  python3 scripts/import_script_identity_map.py \
      --file ../vpt-customer-<name>/test_scripts/script_identity_map.json
"""

import argparse
import json
import os
import sys

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

SERVER_URL = os.environ.get("SERVER_URL", "http://localhost:5109").rstrip("/")
TEAM_ID = os.environ.get("TEAM_ID", "7fdeb4bb-3639-4ec3-959f-b54769a219ce")
API_KEY = os.environ.get("API_KEY", "")
VERIFY_SSL = os.environ.get("VERIFY_SSL", "false").lower() in {"1", "true", "yes"}

HEADERS = {"Content-Type": "application/json"}
if API_KEY:
    HEADERS["X-API-Key"] = API_KEY
    HEADERS["Authorization"] = f"Bearer {API_KEY}"

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_FILE = os.path.join(PROJECT_ROOT, "test_scripts", "script_identity_map.json")


def normalize_ref(raw: str) -> str:
    """Mirror shared/src/lib/utils/script_identity_utils.normalize_script_ref."""
    ref = (raw or "").strip().replace("\\", "/")
    if ref.startswith("./"):
        ref = ref[2:]
    for prefix in ("test_scripts/", "test_campaign/"):
        if ref.startswith(prefix):
            ref = ref[len(prefix):]
    if ref.endswith(".py"):
        ref = ref[:-3]
    return ref.strip("/")


def load_entries(path: str, kind: str) -> dict:
    with open(path, "r", encoding="utf-8") as handle:
        raw = json.load(handle)

    container = "campaigns" if kind == "campaign" else "scripts"
    entries = raw.get(container) if isinstance(raw, dict) else None
    if not isinstance(entries, dict):
        sys.exit(f"ERROR: {path} has no '{container}' object")

    normalized = {}
    for key, value in entries.items():
        ref = normalize_ref(key)
        if ref and isinstance(value, dict):
            normalized[ref] = {
                "prefix": (value.get("prefix") or "").strip() or None,
                "display_name": (value.get("display_name") or "").strip() or None,
            }
    return normalized


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--file", default=DEFAULT_FILE,
                        help=f"identity map to import (default: {DEFAULT_FILE})")
    parser.add_argument("--kind", default="script", choices=["script", "campaign"])
    parser.add_argument("--dry-run", action="store_true",
                        help="print what would be sent, POST nothing")
    parser.add_argument("--overwrite", action="store_true",
                        help="replace rows that already exist (default: skip them)")
    args = parser.parse_args()

    if not os.path.exists(args.file):
        sys.exit(f"ERROR: {args.file} not found")

    entries = load_entries(args.file, args.kind)
    if not entries:
        sys.exit(f"ERROR: no usable entries in {args.file}")

    width = max(len(ref) for ref in entries)
    print(f"\n{len(entries)} entries from {args.file}\n")
    for ref in sorted(entries):
        entry = entries[ref]
        print(f"  {ref.ljust(width)}  [{entry['prefix'] or '-'}]  {entry['display_name'] or '-'}")

    if args.dry_run:
        print("\n--dry-run: nothing sent.\n")
        return 0

    url = f"{SERVER_URL}/server/script-identity/import?team_id={TEAM_ID}"
    print(f"\nPOST {url}")
    response = requests.post(
        url,
        headers=HEADERS,
        json={"scripts": entries, "kind": args.kind, "overwrite": args.overwrite},
        verify=VERIFY_SSL,
        timeout=60,
    )

    if response.status_code != 200:
        print(f"ERROR: HTTP {response.status_code}: {response.text[:500]}")
        return 1

    result = response.json()
    print(f"\n  imported : {result.get('imported', 0)}")
    print(f"  skipped  : {result.get('skipped', 0)}"
          f"{'' if args.overwrite else '  (already present — use --overwrite to replace)'}")

    for conflict in result.get("conflicts") or []:
        print(f"  WARNING  : prefix {conflict['prefix']} on '{conflict['script_ref']}' "
              f"is also used by '{conflict['used_by']}'")
    for failure in result.get("failed") or []:
        print(f"  FAILED   : {failure.get('script_ref')} — {failure.get('error')}")

    print()
    return 0 if result.get("success") else 1


if __name__ == "__main__":
    sys.exit(main())
