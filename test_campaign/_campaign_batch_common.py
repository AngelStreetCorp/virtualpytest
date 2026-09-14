#!/usr/bin/env python3
"""Shared helpers for batch campaign scripts."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from shared.src.lib.executors.campaign_executor import CampaignExecutor
from shared.src.lib.utils.script_target_rules_utils import (
    extract_script_target_rules_from_path,
    normalize_host_os_constraints,
)


def parse_common_args(default_ui: str, description: str) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument(
        "userinterface_name",
        nargs="?",
        default=default_ui,
        help=f"User interface name (default: {default_ui})",
    )
    parser.add_argument("--host", default="auto", help="Host name (default: auto)")
    parser.add_argument("--device", default="auto", help="Device name (default: auto)")
    parser.add_argument(
        "--timeout-minutes",
        type=int,
        default=120,
        help="Campaign timeout in minutes (default: 120)",
    )
    parser.add_argument(
        "--stop-on-failure",
        action="store_true",
        help="Stop at first failure (default is continue on failure)",
    )
    parser.add_argument(
        "--include-script",
        action="append",
        default=[],
        help="Add one script path relative to project root, e.g. test_scripts/tv/fullzap.py",
    )
    parser.add_argument(
        "--include-dir",
        action="append",
        default=[],
        help="Add one script directory relative to project root, e.g. test_scripts/gw",
    )
    parser.add_argument(
        "--exclude-script",
        action="append",
        default=[],
        help="Exclude one script path relative to project root",
    )
    parser.add_argument(
        "--password",
        default="",
        help="Password forwarded to all scripts in the campaign",
    )
    # parse_known_args captures unknown flags (e.g. --password) to forward to scripts
    known, extra = parser.parse_known_args()
    known.extra_script_params = _parse_extra_params(extra)
    return known


def _parse_extra_params(extra: List[str]) -> Dict[str, str]:
    """Convert leftover CLI tokens like ['--password', 'secret'] into {'password': 'secret'}."""
    params: Dict[str, str] = {}
    i = 0
    while i < len(extra):
        token = extra[i]
        if token.startswith("--"):
            key = token.lstrip("-")
            if i + 1 < len(extra) and not extra[i + 1].startswith("--"):
                params[key] = extra[i + 1]
                i += 2
            else:
                params[key] = "true"
                i += 1
        else:
            i += 1
    return params


def _normalize_relative_path(relative_path: str) -> str:
    return str(Path(relative_path).as_posix()).lstrip("/")


def discover_scripts(relative_dir: str) -> List[str]:
    scripts_dir = PROJECT_ROOT / relative_dir
    if not scripts_dir.is_dir():
        raise FileNotFoundError(f"Directory not found: {scripts_dir}")

    scripts: List[str] = []
    for path in sorted(scripts_dir.glob("*.py")):
        if path.name.startswith("_"):
            continue
        scripts.append(_normalize_relative_path(f"{relative_dir}/{path.name}"))

    return scripts


def resolve_scripts(
    include_dirs: Sequence[str],
    include_scripts: Sequence[str],
    exclude_scripts: Sequence[str],
) -> List[str]:
    """Resolve a final ordered script list from include/exclude selectors."""
    resolved: List[str] = []
    seen = set()

    for relative_dir in include_dirs:
        for script in discover_scripts(relative_dir):
            if script not in seen:
                resolved.append(script)
                seen.add(script)

    for script_name in include_scripts:
        normalized = _normalize_relative_path(script_name)
        script_path = PROJECT_ROOT / normalized
        if not script_path.is_file():
            raise FileNotFoundError(f"Script not found: {script_path}")
        if script_path.suffix != ".py":
            raise ValueError(f"Script is not a Python file: {script_path}")
        if normalized not in seen:
            resolved.append(normalized)
            seen.add(normalized)

    excluded = {_normalize_relative_path(item) for item in exclude_scripts}
    return [script for script in resolved if script not in excluded]


def build_campaign_config(
    campaign_id: str,
    campaign_name: str,
    campaign_description: str,
    scripts: List[str],
    args: argparse.Namespace,
    script_os_constraints: Optional[Dict[str, List[str]]] = None,
) -> Dict[str, Any]:
    script_os_constraints = script_os_constraints or {}
    extra_params = getattr(args, 'extra_script_params', {}) or {}
    # Forward known params that individual scripts also accept
    if getattr(args, 'password', None):
        extra_params['password'] = args.password
    script_configurations: List[Dict[str, Any]] = []
    for script_name in scripts:
        item: Dict[str, Any] = {
            "script_name": script_name,
            "script_type": "batch",
            "description": f"Batch execution: {script_name}",
            "parameters": {**extra_params},
        }
        os_constraints = script_os_constraints.get(script_name)
        if os_constraints:
            item["os"] = os_constraints
        script_configurations.append(item)

    return {
        "campaign_id": campaign_id,
        "name": campaign_name,
        "description": campaign_description,
        "userinterface_name": args.userinterface_name,
        "host": args.host,
        "device": args.device,
        "execution_config": {
            "continue_on_failure": not args.stop_on_failure,
            "timeout_minutes": args.timeout_minutes,
            "parallel": False,
        },
        "script_configurations": script_configurations,
    }


def build_script_os_constraints(scripts: List[str]) -> Dict[str, List[str]]:
    """Derive host OS constraints from script-level `_target_rules`."""
    constraints: Dict[str, List[str]] = {}
    for script_name in scripts:
        script_path = PROJECT_ROOT / script_name
        target_rules = extract_script_target_rules_from_path(str(script_path))
        host_os = normalize_host_os_constraints(target_rules)
        if host_os:
            constraints[script_name] = host_os
    return constraints


def describe_script_selection(
    include_dirs: Sequence[str],
    include_scripts: Sequence[str],
    exclude_scripts: Sequence[str],
) -> str:
    parts: List[str] = []
    if include_dirs:
        parts.append(f"dirs={len(include_dirs)}")
    if include_scripts:
        parts.append(f"scripts={len(include_scripts)}")
    if exclude_scripts:
        parts.append(f"excluded={len(exclude_scripts)}")
    return ", ".join(parts) if parts else "no selectors"


def execute_batch_campaign(
    campaign_id: str,
    campaign_name: str,
    campaign_description: str,
    default_ui: str,
    cli_description: str,
    include_dirs: Optional[Sequence[str]] = None,
    include_scripts: Optional[Sequence[str]] = None,
    exclude_scripts: Optional[Sequence[str]] = None,
    script_os_constraints: Optional[Dict[str, List[str]]] = None,
) -> int:
    args = parse_common_args(default_ui=default_ui, description=cli_description)
    base_include_dirs = list(include_dirs or [])
    base_include_scripts = list(include_scripts or [])
    base_exclude_scripts = list(exclude_scripts or [])

    selected_include_dirs = base_include_dirs + list(args.include_dir)
    selected_include_scripts = base_include_scripts + list(args.include_script)
    selected_exclude_scripts = base_exclude_scripts + list(args.exclude_script)

    if not selected_include_dirs and not selected_include_scripts:
        print("ERROR: no scripts selected")
        return 2

    try:
        scripts = resolve_scripts(
            include_dirs=selected_include_dirs,
            include_scripts=selected_include_scripts,
            exclude_scripts=selected_exclude_scripts,
        )
    except (FileNotFoundError, ValueError) as err:
        print(f"ERROR: {err}")
        return 2

    if not scripts:
        print("ERROR: selection resolved to zero Python scripts")
        return 2

    print(f"Starting {campaign_name}")
    print(
        "Selection: "
        f"{describe_script_selection(selected_include_dirs, selected_include_scripts, selected_exclude_scripts)}"
    )
    print(f"Discovered scripts: {len(scripts)}")
    print(f"Failure mode: {'stop on first failure' if args.stop_on_failure else 'continue on failure'}")

    campaign_config = build_campaign_config(
        campaign_id=campaign_id,
        campaign_name=campaign_name,
        campaign_description=campaign_description,
        scripts=scripts,
        args=args,
        script_os_constraints=script_os_constraints or build_script_os_constraints(scripts),
    )

    executor = CampaignExecutor()
    result = executor.execute_campaign(campaign_config)

    success = bool(result.get("success"))
    total = int(result.get("total_scripts", len(scripts)))
    passed = int(result.get("successful_scripts", 0))
    failed = int(result.get("failed_scripts", max(0, total - passed)))
    skipped = int(result.get("skipped_scripts", 0))

    print("=" * 72)
    print(f"SUMMARY total={total} passed={passed} skipped={skipped} failed={failed}")
    if success:
        print("Campaign finished successfully")
        return 0

    print(f"Campaign failed: {result.get('error', 'unknown error')}")
    return 1


if __name__ == "__main__":
    print("This helper is not meant to be executed directly.")
    sys.exit(2)
