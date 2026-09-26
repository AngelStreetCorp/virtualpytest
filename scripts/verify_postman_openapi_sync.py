#!/usr/bin/env python3
"""Verify OpenAPI route coverage and managed collection imports in Postman."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

import yaml

from generate_api_route_specs import HTTP_METHODS, ROOT, SPECS, normalize_path, server_routes
from sync_postman_openapi import MANIFEST_PATH, api_request, read_env_file


def count_requests(items: list | None) -> int:
    total = 0
    for item in items or []:
        if isinstance(item.get("request"), dict):
            total += 1
        total += count_requests(item.get("item"))
    return total


def postman_pairs(items: list | None) -> set[tuple[str, str]]:
    pairs = set()
    for item in items or []:
        request = item.get("request")
        if isinstance(request, dict):
            url = request.get("url", "")
            raw = url if isinstance(url, str) else url.get("raw", "")
            if raw.startswith("{{"):
                raw = re.sub(r"^\{\{[^}]+\}\}", "", raw)
            elif "://" in raw:
                raw = urlsplit(raw).path
            path = raw.split("?", 1)[0]
            path = re.sub(r":([A-Za-z_][\w]*)", r"{\1}", path)
            pairs.add((normalize_path(path), request.get("method", "GET").upper()))
        pairs.update(postman_pairs(item.get("item")))
    return pairs


def spec_operations() -> tuple[set[tuple[str, str]], int, dict[str, tuple[str, int, str, set[tuple[str, str]]]]]:
    pairs: set[tuple[str, str]] = set()
    operation_count = 0
    by_file = {}
    for path in sorted(SPECS.glob("server-*.yaml")) + sorted(SPECS.glob("server-*.yml")):
        content = path.read_text(encoding="utf-8")
        document = yaml.safe_load(content) or {}
        title = document.get("info", {}).get("title", "")
        count = 0
        file_pairs: set[tuple[str, str]] = set()
        for route, operations in (document.get("paths") or {}).items():
            for method in operations:
                method = method.upper()
                if method not in HTTP_METHODS:
                    continue
                pairs.add((normalize_path(route), method))
                file_pairs.add((normalize_path(route), method))
                count += 1
        operation_count += count
        by_file[path.name] = (title, count, hashlib.sha256(content.encode("utf-8")).hexdigest(), file_pairs)
    return pairs, operation_count, by_file


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workspace-id",
        default=os.getenv("POSTMAN_WORKSPACE_ID", "4e7a465c-a542-4440-8903-48787f03942a"),
        help="Postman workspace UUID (defaults to VirtualPyTest's shared workspace)",
    )
    parser.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    args = parser.parse_args()

    api_key = os.getenv("POSTMAN_API_KEY") or read_env_file(ROOT / ".env").get("POSTMAN_API_KEY")
    if not api_key:
        parser.error("POSTMAN_API_KEY is required in the environment or project .env")
    if not args.manifest.exists():
        parser.error(f"Postman sync manifest not found: {args.manifest}; run the sync script first")

    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    if manifest.get("workspace_id") != args.workspace_id:
        parser.error("manifest belongs to a different workspace")
    route_pairs, _, spec_files = spec_operations()
    expected_routes = {
        (normalize_path(record["path"]), record["method"])
        for record in server_routes()
    }
    uncovered = expected_routes - route_pairs
    stale = route_pairs - expected_routes

    errors = []
    if uncovered:
        errors.append(f"{len(uncovered)} registered route/method pairs are missing from OpenAPI specs")
    if stale:
        errors.append(f"{len(stale)} spec route/method pairs do not match the current route registries")
    if set(manifest.get("specs", {})) != set(spec_files):
        missing = set(spec_files) - set(manifest.get("specs", {}))
        extra = set(manifest.get("specs", {})) - set(spec_files)
        if missing:
            errors.append(f"manifest missing specs: {', '.join(sorted(missing))}")
        if extra:
            errors.append(f"manifest contains removed specs: {', '.join(sorted(extra))}")

    remote = api_request(
        "GET",
        f"/collections?workspace={args.workspace_id}",
        api_key,
    )
    remote_by_uid = {item.get("uid"): item for item in remote.get("collections", [])}
    request_total = 0
    operation_total = 0
    for filename, (title, expected_count, digest, expected_pairs) in sorted(spec_files.items()):
        operation_total += expected_count
        entry = manifest.get("specs", {}).get(filename)
        if not entry:
            continue
        if entry.get("sha256") != digest or entry.get("title") != title:
            errors.append(f"manifest is stale for {filename}; regenerate and sync")
            continue
        uid = entry.get("collection_uid")
        if uid not in remote_by_uid:
            errors.append(f"Postman collection is missing: {title}")
            continue
        remote_title = remote_by_uid[uid].get("name")
        if remote_title != title:
            errors.append(f"Postman collection title mismatch: expected {title}, got {remote_title}")
        detail = api_request("GET", f"/collections/{uid}", api_key).get("collection", {})
        actual_count = count_requests(detail.get("item"))
        actual_pairs = postman_pairs(detail.get("item"))
        request_total += actual_count
        if actual_count != expected_count:
            errors.append(f"{title}: OpenAPI has {expected_count} operations, Postman has {actual_count} requests")
        if actual_pairs != expected_pairs:
            errors.append(
                f"{title}: Postman route mismatch ({len(expected_pairs - actual_pairs)} missing, "
                f"{len(actual_pairs - expected_pairs)} unexpected)"
            )
        print(f"{title}: {actual_count}/{expected_count} requests")

    print(f"Server route inventory: {len(expected_routes)} registered pairs, {len(uncovered)} missing, {len(stale)} stale")
    print(f"Managed collections: {len(manifest.get('specs', {}))}/{len(spec_files)}; Postman workspace total: {len(remote.get('collections', []))}")
    print(f"Requests: {request_total}/{operation_total}")
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print("Postman route coverage and collection imports verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
