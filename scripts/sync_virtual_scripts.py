#!/usr/bin/env python3
"""
Convert on-disk test scripts into virtual scripts, in bulk.

The disk -> virtual migration in one repeatable command (the analogue of the
labox `sync_vpt.py`). Planning happens HERE, against a local tree: the import
graph is walked, `from test_scripts.<pkg>.<mod> import ...` rewritten to the bare
form, `_script_libs` injected, the sibling .md picked up as the doc, and the
script renamed to its basename with the disk subfolder becoming its folder.

Writing then goes through POST /server/virtual-script/save with the rewritten
source. That matters twice over:
  - the server never needs the files, so a merged core+overlay tree assembled
    locally can be pushed to any environment;
  - no service-role DB credentials are needed on the operator's machine.

Nothing is written unless every requested script plans cleanly.

─────────────────────────────────────────────────────────────────────────────
RUN
─────────────────────────────────────────────────────────────────────────────
  # see what would happen — writes nothing
  python3 scripts/sync_virtual_scripts.py --dry-run --scripts gw/superping

  # a merged tree (platform core + customer overlay), then apply
  rsync -a ~/virtualpytest/test_scripts/         /tmp/vpt-stage/test_scripts/
  rsync -a ~/vpt-customer-overlay/test_scripts/  /tmp/vpt-stage/test_scripts/
  SERVER_URL=http://localhost:5109 API_KEY=<key> \
  python3 scripts/sync_virtual_scripts.py \
      --scripts-dir /tmp/vpt-stage/test_scripts --scripts gw/superping

  # whole folders
  python3 scripts/sync_virtual_scripts.py --folder gw --dry-run
  python3 scripts/sync_virtual_scripts.py --all --dry-run

See docs/agent/execution/VIRTUAL_SCRIPTS.md.
"""

import argparse
import glob
import json
import os
import sys

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from shared.src.lib.utils.script_conversion import (  # noqa: E402
    ERR_NAME_COLLISION,
    ROOT_FOLDER,
    plan_conversion,
)
from shared.src.lib.utils.script_target_rules_utils import (  # noqa: E402
    extract_script_description_from_source,
)

SERVER_URL = os.environ.get("SERVER_URL", "http://localhost:5109").rstrip("/")
TEAM_ID = os.environ.get("TEAM_ID", "7fdeb4bb-3639-4ec3-959f-b54769a219ce")
API_KEY = os.environ.get("API_KEY", "")
VERIFY_SSL = os.environ.get("VERIFY_SSL", "false").lower() in {"1", "true", "yes"}

HEADERS = {"Content-Type": "application/json"}
if API_KEY:
    HEADERS["X-API-Key"] = API_KEY
    HEADERS["Authorization"] = f"Bearer {API_KEY}"

DEFAULT_SCRIPTS_DIR = os.path.join(PROJECT_ROOT, "test_scripts")

# Same exclusion rule as backend_server/src/lib/utils/script_utils._is_discoverable_script:
# helper modules are not runnable scripts. They are still converted when a script
# imports them — just never selected directly by --folder / --all.
HELPER_PREFIXES = ("utils_", "lib_", "common_", "_")


def discover_refs(scripts_dir, folder=None):
    """Runnable script refs under scripts_dir (root + depth-1 subfolders)."""
    refs = []
    patterns = [os.path.join(scripts_dir, "*.py"), os.path.join(scripts_dir, "*", "*.py")]
    for path in sorted(p for pattern in patterns for p in glob.glob(pattern)):
        ref = os.path.relpath(path, scripts_dir)[:-3].replace("\\", "/")
        if os.path.basename(ref).startswith(HELPER_PREFIXES):
            continue
        if folder and not ref.startswith(f"{folder}/"):
            continue
        refs.append(ref)
    return refs


def build_plans(refs, scripts_dir, include_helpers, strip_bootstrap):
    """Plan every ref, with a batch-wide basename collision check.

    Virtual-script names are global per team and `_script_libs` resolves by bare
    name, so two folders producing the same basename would shadow each other.
    """
    units, errors, claimed, seen = [], [], {}, set()

    for ref in refs:
        plan = plan_conversion(
            ref, scripts_dir,
            include_helpers=include_helpers,
            strip_syspath_bootstrap=strip_bootstrap,
        )
        errors.extend({"ref": e["ref"], "code": e["code"], "message": e["message"]}
                      for e in plan.errors)
        for unit in plan.units:
            owner = claimed.setdefault(unit.vs_name, unit.disk_ref)
            if owner != unit.disk_ref:
                errors.append({
                    "ref": unit.disk_ref, "code": ERR_NAME_COLLISION,
                    "message": f"also produced by '{owner}' — rename one first",
                })
            if unit.disk_ref in seen:
                continue
            seen.add(unit.disk_ref)
            units.append(unit)

    return units, errors


def print_plan(units, errors):
    if units:
        width = max(len(u.disk_ref) for u in units)
        print(f"\n{len(units)} unit(s) to write (helpers first):\n")
        for unit in units:
            kind = "lib " if unit.is_helper else "    "
            libs = f"libs={','.join(unit.libs)}" if unit.libs else ""
            doc = "doc" if unit.doc else "   "
            print(f"  {kind}{unit.disk_ref.ljust(width)}  ->  "
                  f"{unit.vs_name} @{unit.folder}  {doc}  {libs}")
            for warning in unit.warnings:
                print(f"      WARNING: {warning}")

    if errors:
        print(f"\n{len(errors)} error(s):\n")
        for error in errors:
            print(f"  [{error['code']}] {error['ref']}: {error['message']}")


def fetch_existing_ids():
    """{virtual_script_name: dev_row_id} for this team.

    /save rejects a duplicate name with 409 unless the row `id` is supplied, so
    re-running the sync has to pass the existing id to mean "update". The list
    endpoint returns one entry per name based on the canonical dev row, which is
    exactly the row convert/sync owns.
    """
    response = requests.get(
        f"{SERVER_URL}/server/virtual-script/list?team_id={TEAM_ID}",
        headers=HEADERS, verify=VERIFY_SSL, timeout=60,
    )
    if response.status_code != 200:
        sys.exit(f"ERROR: could not list virtual scripts — "
                 f"HTTP {response.status_code}: {response.text[:300]}")
    scripts = (response.json() or {}).get("scripts") or []
    return {s["name"]: s["id"] for s in scripts if s.get("name") and s.get("id")}


def save_unit(unit, existing_ids, promote=None):
    """Write one unit via /server/virtual-script/save, then optionally promote."""
    payload = {
        "name": unit.vs_name,
        "source": unit.source,
        "doc": unit.doc,
        "folder": None if unit.folder == ROOT_FOLDER else unit.folder,
        # The route derives target_rules and the description fallback from the
        # source itself; only an explicit description is worth sending.
        "description": extract_script_description_from_source(unit.source),
    }
    existing_id = existing_ids.get(unit.vs_name)
    if existing_id:
        payload["id"] = existing_id

    response = requests.post(
        f"{SERVER_URL}/server/virtual-script/save?team_id={TEAM_ID}",
        headers=HEADERS, json=payload, verify=VERIFY_SSL, timeout=60,
    )
    if response.status_code != 200:
        return None, f"HTTP {response.status_code}: {response.text[:300]}"

    body = response.json()
    if not body.get("success"):
        return None, body.get("error") or "save failed"

    body["action"] = "updated" if existing_id else "created"
    script_id = (body.get("script") or {}).get("id") or body.get("id")
    if script_id:
        existing_ids[unit.vs_name] = script_id

    if promote and script_id:
        promote_response = requests.post(
            f"{SERVER_URL}/server/virtual-script/{script_id}/promote?team_id={TEAM_ID}",
            headers=HEADERS, json={"target_env": promote}, verify=VERIFY_SSL, timeout=60,
        )
        if promote_response.status_code != 200:
            return body, f"saved, but promote to {promote} failed: {promote_response.text[:200]}"

    return body, None


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--scripts", nargs="+", metavar="REF",
                           help="script refs, e.g. gw/superping (no .py)")
    selection.add_argument("--folder", metavar="NAME",
                           help="every runnable script in this subfolder")
    selection.add_argument("--all", action="store_true",
                           help="every runnable script under --scripts-dir")
    parser.add_argument("--scripts-dir", default=DEFAULT_SCRIPTS_DIR,
                        help=f"tree to read from (default: {DEFAULT_SCRIPTS_DIR})")
    parser.add_argument("--dry-run", action="store_true", help="plan only, write nothing")
    parser.add_argument("--json", action="store_true", help="emit the plan as JSON")
    parser.add_argument("--promote", choices=["test", "prod"],
                        help="promote each converted script after writing it")
    parser.add_argument("--no-helpers", action="store_true",
                        help="do not convert imported helper modules (rarely what you want)")
    parser.add_argument("--keep-bootstrap", action="store_true",
                        help="leave the sys.path bootstrap block in place")
    parser.add_argument("--force", action="store_true",
                        help="write even when a script carries warnings (it will very "
                             "likely fail at run time — fix the warning instead)")
    args = parser.parse_args()

    scripts_dir = os.path.abspath(args.scripts_dir)
    if not os.path.isdir(scripts_dir):
        sys.exit(f"ERROR: {scripts_dir} is not a directory")

    if args.scripts:
        refs = [r[:-3] if r.endswith(".py") else r for r in args.scripts]
    else:
        refs = discover_refs(scripts_dir, args.folder)
    if not refs:
        sys.exit("ERROR: nothing selected")

    units, errors = build_plans(
        refs, scripts_dir,
        include_helpers=not args.no_helpers,
        strip_bootstrap=not args.keep_bootstrap,
    )

    if args.json:
        print(json.dumps({
            "scripts_dir": scripts_dir,
            "requested": refs,
            "units": [{
                "disk_ref": u.disk_ref, "name": u.vs_name, "folder": u.folder,
                "libs": u.libs, "has_doc": bool(u.doc), "is_helper": u.is_helper,
                "warnings": u.warnings,
            } for u in units],
            "errors": errors,
        }, indent=2))
    else:
        print_plan(units, errors)

    if errors:
        print("\nNothing written — fix the errors above first "
              "(a partial conversion fails at import time with a confusing error).\n")
        return 1

    warned = [u for u in units if u.warnings]
    if warned and not args.force:
        names = ", ".join(u.disk_ref for u in warned)
        print(f"\nNothing written — {len(warned)} script(s) carry warnings: {names}\n"
              "These convert cleanly but will misbehave at run time (paths derived from\n"
              "__file__ resolve to the test_scripts/ root once materialized). Fix them,\n"
              "or re-run with --force if you know the path is not used.\n")
        return 1

    if args.dry_run:
        print("\n--dry-run: nothing written.\n")
        return 0

    print(f"\nWriting to {SERVER_URL} (team {TEAM_ID})\n")
    existing_ids = fetch_existing_ids()
    failures = 0
    for unit in units:
        # Helpers are libraries, not runnable scripts — promoting them would create
        # prod rows nothing executes. _script_libs falls back to dev anyway.
        body, error = save_unit(unit, existing_ids,
                                promote=args.promote if not unit.is_helper else None)
        if body is None:
            print(f"  FAILED   {unit.vs_name}: {error}")
            failures += 1
            # Stop at the first failure: a script written without its library is
            # worse than nothing.
            break
        status = "updated" if body.get("action") == "updated" else "created"
        note = f"  ({error})" if error else ""
        print(f"  {status:<8} {unit.vs_name} @{unit.folder}{note}")

    print()
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
