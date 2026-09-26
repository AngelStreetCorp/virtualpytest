#!/usr/bin/env python3
"""Import the public Backend Server OpenAPI specs as Postman collections.

The first run creates one collection per Server spec. Subsequent runs skip unchanged
collections. If a spec changes, use --replace-managed to import its new version
and delete only the older collection recorded in this script's local manifest. Use
--prune-managed to remove collections for specs deliberately removed from this public set.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import ssl
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
SPECS_DIR = ROOT / "docs" / "api" / "specs"
MANIFEST_PATH = ROOT / ".postman_sync_manifest.json"
API_BASE = "https://api.getpostman.com"
COLLECTION_SCHEMA = "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"


def read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.removeprefix("export ").strip()] = value.strip().strip("\"'")
    return values


def api_request(method: str, path: str, api_key: str, body: dict | None = None) -> dict:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = Request(
        f"{API_BASE}{path}",
        data=data,
        method=method,
        headers={
            "X-Api-Key": api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        # macOS Python builds may not have the system roots wired into urllib,
        # while certifi (pulled in by requests) carries the standard CA bundle.
        try:
            import certifi

            context = ssl.create_default_context(cafile=certifi.where())
        except ImportError:
            context = ssl.create_default_context()
        with urlopen(request, timeout=30, context=context) as response:
            payload = response.read()
    except HTTPError as exc:
        detail = exc.read(1000).decode("utf-8", "replace")
        raise RuntimeError(f"Postman API returned HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"Could not reach Postman API: {exc.reason}") from exc
    return json.loads(payload) if payload else {}


def write_manifest(path: Path, manifest: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workspace-id",
        default=os.getenv("POSTMAN_WORKSPACE_ID"),
        help="Postman workspace UUID (or set POSTMAN_WORKSPACE_ID)",
    )
    parser.add_argument(
        "--api-key",
        default=os.getenv("POSTMAN_API_KEY"),
        help="Postman API key (prefer POSTMAN_API_KEY in environment or project .env)",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Create/update managed Postman collections; without this flag only preview",
    )
    parser.add_argument(
        "--replace-managed",
        action="store_true",
        help="When a tracked spec changed, replace only its collection recorded in the manifest",
    )
    parser.add_argument(
        "--prune-managed",
        action="store_true",
        help="Delete tracked collections for specs removed from the public Server API set",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=MANIFEST_PATH,
        help="Local state file used to identify collections created by this script",
    )
    args = parser.parse_args()

    api_key = args.api_key or read_env_file(ROOT / ".env").get("POSTMAN_API_KEY")
    if not args.workspace_id:
        parser.error("--workspace-id or POSTMAN_WORKSPACE_ID is required")
    if not api_key:
        parser.error("--api-key, POSTMAN_API_KEY, or POSTMAN_API_KEY in project .env is required")

    # The shared public workspace exposes the Backend Server API. Direct Backend
    # Host routes are a separate service boundary and are intentionally excluded.
    spec_files = sorted(SPECS_DIR.glob("server-*.yaml")) + sorted(SPECS_DIR.glob("server-*.yml"))
    if not spec_files:
        print(f"No OpenAPI specs found in {SPECS_DIR}", file=sys.stderr)
        return 1

    manifest = {"workspace_id": args.workspace_id, "specs": {}}
    if args.manifest.exists():
        try:
            manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"Invalid manifest {args.manifest}: {exc}", file=sys.stderr)
            return 1
        if manifest.get("workspace_id") != args.workspace_id:
            print("Manifest belongs to a different Postman workspace; choose another --manifest.", file=sys.stderr)
            return 1

    # Parse only the OpenAPI info title from YAML. PyYAML is already a project
    # dependency for API docs generation; fail clearly if it is unavailable.
    try:
        import yaml
    except ImportError:
        print("PyYAML is required; install the project's backend_server requirements.", file=sys.stderr)
        return 1

    plans = []
    removed_specs = set(manifest.get("specs", {})) - {path.name for path in spec_files}
    for spec_path in spec_files:
        source = spec_path.read_text(encoding="utf-8")
        spec = yaml.safe_load(source)
        title = spec.get("info", {}).get("title") if isinstance(spec, dict) else None
        if not title:
            print(f"Skipping {spec_path.name}: OpenAPI info.title is missing", file=sys.stderr)
            continue
        digest = hashlib.sha256(source.encode("utf-8")).hexdigest()
        previous = manifest.get("specs", {}).get(spec_path.name)
        if previous and previous.get("sha256") == digest:
            plans.append((spec_path, title, digest, previous, "unchanged"))
        elif previous and not args.replace_managed:
            plans.append((spec_path, title, digest, previous, "changed; use --replace-managed"))
        else:
            plans.append((spec_path, title, digest, previous, "import"))

    print(f"Workspace: {args.workspace_id}")
    print(f"OpenAPI specs: {len(plans)}")
    for spec_path, title, _, _, action in plans:
        print(f"- {action}: {spec_path.name} → {title}")
    for filename in sorted(removed_specs):
        action = "prune managed collection" if args.prune_managed else "retained; use --prune-managed to remove"
        print(f"- {action}: {filename}")
    if not args.apply:
        print("Preview only. Add --apply to import the collections.")
        return 0

    try:
        remote = api_request(
            "GET", f"/collections?{urlencode({'workspace': args.workspace_id})}", api_key
        )
    except RuntimeError as exc:
        print(exc, file=sys.stderr)
        return 1
    existing = remote.get("collections", [])
    existing_by_name = {c.get("name"): c for c in existing}
    errors = 0

    for spec_path, title, digest, previous, action in plans:
        if action == "unchanged":
            continue
        if action == "changed; use --replace-managed":
            print(f"Unchanged remotely: {title} (spec changed; re-run with --replace-managed)")
            errors += 1
            continue
        if previous is None and title in existing_by_name:
            print(f"Skipped {title}: a same-named collection exists but is not managed by this script")
            errors += 1
            continue

        try:
            # The Postman import API expects a transport type (string), while
            # the OpenAPI version is inferred from the specification content.
            time.sleep(1.1)
            result = api_request(
                "POST",
                f"/import/openapi?{urlencode({'workspace': args.workspace_id})}",
                api_key,
                {
                    "type": "string",
                    "input": spec_path.read_text(encoding="utf-8"),
                    "options": {"schemaFaker": False},
                },
            )
            created = result.get("collections", [])
            if not created or not created[0].get("uid"):
                raise RuntimeError(f"Postman returned no collection UID for {spec_path.name}")
            collection = created[0]

            # Replace only an old collection UID this manifest says we created.
            if previous:
                api_request("DELETE", f"/collections/{previous['collection_uid']}", api_key)

            manifest.setdefault("specs", {})[spec_path.name] = {
                "title": title,
                "sha256": digest,
                "collection_uid": collection["uid"],
            }
            write_manifest(args.manifest, manifest)
            existing_by_name[collection.get("name", title)] = collection
            print(f"Imported {collection.get('name', title)} ({spec_path.name})")
        except (RuntimeError, KeyError, OSError) as exc:
            print(f"Failed {spec_path.name}: {exc}", file=sys.stderr)
            errors += 1

    if args.prune_managed and not errors:
        for filename in sorted(removed_specs):
            previous = manifest.get("specs", {}).get(filename)
            if not previous or not previous.get("collection_uid"):
                manifest.get("specs", {}).pop(filename, None)
                continue
            try:
                api_request("DELETE", f"/collections/{previous['collection_uid']}", api_key)
                manifest.get("specs", {}).pop(filename, None)
                print(f"Removed managed collection for {filename}")
            except RuntimeError as exc:
                print(f"Failed to prune {filename}: {exc}", file=sys.stderr)
                errors += 1
        write_manifest(args.manifest, manifest)

    print(f"Manifest: {args.manifest}")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
