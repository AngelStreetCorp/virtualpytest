#!/usr/bin/env python3
"""coverage_report.py — TASK-27 step 4h: how much of the canonical apps the dataset covers.

The same function as ``GET /server/training-samples/coverage`` (``lib/dataset_coverage.py``,
definitions there): per app, per platform and one global exhaustiveness percentage
(screens with at least ``k`` labelled ``screen-id`` samples / visible screens). Read-only.

Environment: the DB (``SUPABASE_*``); nothing loads a ``.env``.

Usage
-----
    python3 features/ai-dataset/scripts/coverage_report.py --team <uuid> [--k 3] [--json] [--all-missing]
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
from typing import Any, Dict, List, Optional

_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.normpath(os.path.join(_SCRIPT_DIR, "..", "..", ".."))
if os.path.isdir(os.path.join(_REPO_ROOT, "shared")) and _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

coverage = importlib.import_module('features.ai-dataset.lib.dataset_coverage')

MISSING_SHOWN = 15


def format_report(report: Dict[str, Any], all_missing: bool = False) -> str:
    k = report['k']
    g = report['global']
    lines = [f"Coverage (k={k}) team={report.get('team_id')}",
             f"GLOBAL exhaustiveness: {g['exhaustiveness_pct']}%  "
             f"({g['screens_gek']}/{g['screens']} screens with >={k} samples; "
             f">=1: {g['screens_ge1']}; eval-verified rows: {g['eval_verified']})",
             '', 'Per platform:']
    for p in report['platforms']:
        b = p.get('banner') or {}
        lines.append(f"  {p['platform']:10s} apps={','.join(p['apps'])}  screens={p['screens']} "
                     f">=1={p['screens_ge1']} >={k}={p['screens_gek']} ({p['pct_gek']}%) "
                     f"eval-verified={p['eval_verified']}  banner rows={b.get('rows', 0)} "
                     f"labelled={b.get('labelled', 0)}")
    lines += ['', f"{'app':12s} {'platform':8s} {'screens':>7s} {'rows':>5s} {'>=1':>4s} {'>=' + str(k):>4s} "
                  f"{'%':>6s} {'labelled':>8s} {'seeded':>6s} {'eval':>5s} {'focus':>5s}"]
    for a in report['apps']:
        lines.append(f"{a['name']:12s} {a['platform']:8s} {a['screens']:7d} {a['node_rows']:5d} "
                     f"{a['screens_ge1']:4d} {a['screens_gek']:4d} {a['pct_gek']:6.1f} "
                     f"{a['screen_id_labelled']:8d} {a['seeded_rows']:6d} {a['eval_verified']:5d} "
                     f"{a['focus']['labelled']:5d}")
    for a in report['apps']:
        missing = a['missing_screens']
        shown = missing if all_missing else missing[:MISSING_SHOWN]
        lines.append('')
        lines.append(f"{a['name']}: {len(missing)} missing screen(s) (no labelled sample), "
                     f"{len(a['thin_screens'])} below k")
        if shown:
            lines.append('  missing: ' + ', '.join(m['label'] for m in shown) +
                         ('' if len(shown) == len(missing) else f" ... (+{len(missing) - len(shown)}, --all-missing)"))
        # Step 4k: the screen groups (group -> member nodes, focus states with >=1 sample).
        for grp in a.get('groups') or []:
            if len(grp.get('states') or []) > 1:
                lines.append(f"  group {grp['label']}: {grp['samples']} sample(s), "
                             f"{grp['states_covered']}/{grp['states_total']} focus states covered: " +
                             ', '.join(f"{st['label']} ({st['samples']})" for st in grp['states']))
        if a['offtree_labels']:
            lines.append('  off-tree labels: ' + ', '.join(a['offtree_labels']))
        if a['stale_labels']:
            lines.append(f"  labels on nodes no longer in the tree: {len(a['stale_labels'])}")
    if report.get('canonical_missing'):
        lines += ['', 'canonical apps absent from this team: ' + ', '.join(report['canonical_missing'])]
    if report.get('banner_by_platform'):
        lines += ['', 'banner rows by platform (no userinterface on banner rows): ' +
                  ', '.join(f"{p}={c.get('rows', 0)}" for p, c in report['banner_by_platform'].items())]
    others = report.get('not_in_scope') or []
    lines += ['', f"Not in scope ({len(others)}):"]
    for o in others:
        lines.append(f"  {o['name']:28s} {o['platform']:15s} screens={o['screens']:3d}  {o['reason']}")
    return '\n'.join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    p = argparse.ArgumentParser(description='TASK-27 step 4h: dataset coverage of the canonical apps (read-only).')
    p.add_argument('--team', required=True, help='team id')
    p.add_argument('--k', type=int, default=coverage.DEFAULT_K, help='distinct samples a screen needs (default 3)')
    p.add_argument('--json', action='store_true', help='print the report as JSON')
    p.add_argument('--all-missing', action='store_true', help='list every missing screen')
    args = p.parse_args(argv)
    report = coverage.build_coverage(args.team, args.k)
    print(json.dumps(report, indent=2) if args.json else format_report(report, args.all_missing))
    return 0


if __name__ == '__main__':
    sys.exit(main())
