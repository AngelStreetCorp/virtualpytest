#!/usr/bin/env python3
"""Localize audit report (TASK-107): one command, one markdown report, flags to act on.

Runbook: docs/agent/navigation/LOCALIZE_AUDIT.md (written so a Sonnet or Haiku session can redo it).

    python3 scripts/localize/audit.py                 # print the report, save it under <set>/audits/
    python3 scripts/localize/audit.py --run-bench     # score the bench first (~10 min on vpt-pi1)

Reads, never writes the DB:
  1. Coverage   - shared/src/lib/database/localize_coverage_db.get_coverage (same as the page / MCP tool)
  2. Accuracy   - the bench's results/latest.json against the run before it (scripts/localize/bench.py)
  3. Corrections - active localize_verdicts rows per interface

Flags (each one is a line under "## Flags", empty = nothing to do):
  ZERO        an interface with screen nodes and 0 % fingerprinted and 0 % identity
  NO_LIVE     a TV / STB interface (models stb, android_tv, fire_tv*, apple_tv, tizen) with no live node
  STALE       median fingerprint age above --stale-days (default 90)
  NO_IDENTITY an android / web interface with fingerprints but no node identity
  REGRESSION  a bench kind that lost more than --drop points since the previous run
  BENCH_OLD   the latest bench run is older than 36 h (the nightly timer did not run)
  TIER2_GAP   the cheap Tier-2 check found a gap open again (playback without is_media, error
              without OCR, overlay over-firing) — scripts/localize/cheap23.py
  DUP_FP      two nodes of one tree whose stored fingerprints share the same focus and title (a recapture
              taken on the wrong screen hides as a duplicate: TASK-133 `tvguide` held a Home frame and
              won over `home_settings`). Setting states of one screen (standby fast / eco) show up too: read, don't recapture.
  OVERLAY_FP  overlay false positives on plain screens above --overlay-fp % (default 5), or any
              popup / keyboard / notification false positive (those become a Localize verdict)
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.dirname(__file__))

import bench  # noqa: E402  (same folder: set dir, env loading, team default)

TV_MODELS = ('stb', 'android_tv', 'fire_tv_fireos', 'fire_tv_vega', 'apple_tv', 'tizen', 'fx_dongle')
IDENTITY_MODELS = ('android_mobile', 'android_tablet', 'web', 'host_vnc')


def dup_fp_flags(nodes: List[Dict[str, Any]], x_tol: float = 0.03) -> List[str]:
    """`DUP_FP <ui> <a>/<b>` for two nodes of one interface with the same stored focus and title (pure).

    nodes: {userinterface_name, label, fingerprint}. Compared: same focus kind, x (and y / width) within
    `x_tol` / 0.02, and the same non-empty title. Focus `none` and nodes without a title are skipped.
    """
    def close(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
        if a.get('kind') != b.get('kind') or a.get('kind') not in ('nav', 'box'):
            return False
        if abs(a.get('x', -9) - b.get('x', 9)) > x_tol:
            return False
        if a['kind'] == 'nav':
            return abs(a.get('width', -9) - b.get('width', 9)) <= 0.02
        return abs(a.get('y', -9) - b.get('y', 9)) <= x_tol
    out: List[str] = []
    by_ui: Dict[str, List[Dict[str, Any]]] = {}
    for n in nodes:
        fp = n.get('fingerprint') or {}
        if fp.get('title') and fp.get('focus'):
            by_ui.setdefault(n['userinterface_name'], []).append(n)
    for ui, ns in by_ui.items():
        if ui.startswith('__'):
            continue
        for i, a in enumerate(ns):
            for b in ns[i + 1:]:
                fa, fb = a['fingerprint'], b['fingerprint']
                if fa['title'] == fb['title'] and close(fa['focus'], fb['focus']):
                    out.append(f"DUP_FP {ui}: {a['label']}/{b['label']}")
    return out


def load_fp_nodes(db: Any, team: str) -> List[Dict[str, Any]]:
    """Fingerprinted screen nodes of every interface (read only)."""
    uis = {u['id']: u['name'] for u in (db.table('userinterfaces').select('id,name').eq('team_id', team).execute().data or [])}
    trees = {t['id']: uis.get(t['userinterface_id']) for t in
             (db.table('navigation_trees').select('id,userinterface_id').eq('team_id', team).execute().data or [])}
    rows = db.table('navigation_nodes').select('tree_id,node_id,label,node_type,data').eq('team_id', team).execute().data or []
    seen, out = set(), []
    for r in rows:
        fp = (r.get('data') or {}).get('fingerprint')
        ui = trees.get(r['tree_id'])
        if not fp or not ui or r['node_id'] in seen or (r.get('node_type') or 'screen') in ('entry', 'action'):
            continue
        seen.add(r['node_id'])
        out.append({'userinterface_name': ui, 'label': r.get('label') or r['node_id'], 'fingerprint': fp})
    return out


def bench_runs(set_dir: str) -> List[Dict[str, Any]]:
    """Bench results, oldest first (latest.json is a copy of the newest, so it is skipped)."""
    out = []
    for p in sorted(glob.glob(os.path.join(set_dir, 'results', '20*.json'))):
        try:
            out.append(json.load(open(p)))
        except Exception:
            continue
    return out


def flags_for(coverage: List[Dict[str, Any]], runs: List[Dict[str, Any]], stale_days: float, drop: float,
              now: Optional[datetime] = None, overlay_fp: float = 5.0) -> List[str]:
    """The audit's action list (pure, unit-tested)."""
    now = now or datetime.now(timezone.utc)
    out: List[str] = []
    for r in coverage:
        if not r['screens'] or r['userinterface_name'].startswith('__'):   # CI / smoke-test fixtures
            continue
        name, models = r['userinterface_name'], set(r.get('models') or [])
        if r['fingerprinted'] == 0 and r['identity'] == 0:
            out.append(f"ZERO {name}: {r['screens']} screen nodes, none fingerprinted")
        if models & set(TV_MODELS) and not r.get('live_node'):
            out.append(f"NO_LIVE {name}: TV interface without a node flagged `live` (node editor > Live node)")
        age = (r.get('fingerprint_age_days') or {}).get('median')
        if age is not None and age > stale_days:
            out.append(f"STALE {name}: median fingerprint age {age} d (> {stale_days:g})")
        if models & set(IDENTITY_MODELS) and r['fingerprinted'] and not r['identity']:
            out.append(f"NO_IDENTITY {name}: android/web interface, recapture its nodes to store the identity")
    if runs:
        last = runs[-1]
        ran = datetime.fromisoformat(last['ran_at'])
        if (now - ran).total_seconds() > 36 * 3600:
            out.append(f"BENCH_OLD latest bench run {last['ran_at']} (> 36 h): check vpt-localize-bench.timer")
        for gap, rows in ((last.get('tier2') or {}).get('gaps_open') or {}).items():
            out.append(f"TIER2_GAP {gap}: {', '.join(rows[:5])}")
        ov = last.get('overlay') or {}
        if ov.get('fp_pct') is not None and (ov['fp_pct'] > overlay_fp or (ov.get('verdict_fp_pct') or 0) > 0):
            out.append(f"OVERLAY_FP plain screens: {ov['fp_pct']} % false positives, "
                       f"{ov.get('verdict_fp_pct')} % on verdict kinds (limit {overlay_fp:g} % / 0 %)")
        if len(runs) > 1:
            prev = runs[-2]
            for kind, v in last.get('per_kind', {}).items():
                p = (prev.get('per_kind') or {}).get(kind)
                if p and v.get('pct') is not None and p.get('pct') is not None and p['pct'] - v['pct'] > drop:
                    out.append(f"REGRESSION {kind}: {p['pct']} % -> {v['pct']} % since {prev['ran_at']}")
    return out


def report(coverage: List[Dict[str, Any]], runs: List[Dict[str, Any]], corrections: Dict[str, int],
           flags: List[str]) -> str:
    now = datetime.now(timezone.utc).isoformat(timespec='minutes')
    with_screens = [r for r in coverage if r['screens']]
    screens = sum(r['screens'] for r in with_screens)
    named = sum(r['fingerprinted'] for r in with_screens)
    lines = [f"# Localize audit {now}", '',
             f"Coverage: {named}/{screens} screen nodes fingerprinted "
             f"({round(100.0 * named / screens, 1) if screens else 0} %) across {len(with_screens)} interfaces; "
             f"{sum(1 for r in with_screens if r.get('live_node'))} with a live node; "
             f"{sum(1 for r in with_screens if r['identity'])} with a device identity.", '']
    if runs:
        last = runs[-1]
        prev = runs[-2] if len(runs) > 1 else None
        lines += [f"Accuracy (bench, Jev off): **{last['accuracy']} %** of {last['samples']} samples, run {last['ran_at']}"
                  + (f" (previous {prev['accuracy']} % on {prev['ran_at']})" if prev else ''), '',
                  '| kind | % | n | previous % | left to Jev |', '|---|---|---|---|---|']
        for k, v in last.get('per_kind', {}).items():
            p = ((prev or {}).get('per_kind') or {}).get(k, {}).get('pct', '—')
            lines.append(f"| {k} | {v['pct']} | {v['n']} | {p} | {v.get('awaits_jev', 0)} |")
        lines.append('')
        ov, t2 = last.get('overlay'), last.get('tier2')
        if ov:
            lines += [f"Overlay calibration: {ov['fp_pct']} % false positives on {ov['plain']} plain screens "
                      f"({ov['verdict_fp_pct']} % on popup / keyboard / notification); recall "
                      + ', '.join(f"{k} {v} %" for k, v in ov['recall'].items()), '']
        if t2:
            lines += [f"Cheap Tier-2 check: {t2['reachable']}/{t2['frames']} frames, "
                      + ', '.join(f"{f} {v['ok']}/{v['n']}" for f, v in t2['fields'].items())
                      + f"; gaps open: {', '.join(t2['gaps_open']) or 'none'}", '']
    else:
        lines += ['Accuracy: no bench run found (run `bench.py nightly` first).', '']
    # one line per subject (an interface or a bench kind) with every flag it has
    grouped: Dict[str, List[str]] = {}
    for f in flags:
        code, rest = f.split(' ', 1)
        subject, _, why = rest.partition(': ')
        grouped.setdefault(subject, []).append(f"{code} ({why})" if code in ('REGRESSION', 'STALE', 'BENCH_OLD', 'TIER2_GAP', 'OVERLAY_FP') else code)
    lines += ['## Flags', ''] + ([f"- {k}: {', '.join(v)}" for k, v in grouped.items()] or ['- none']) + ['']
    lines += ['## Coverage per interface', '', '| interface | screens | fingerprinted % | identity % | live node | median age d | corrections |',
              '|---|---|---|---|---|---|---|']
    for r in with_screens:
        age = (r.get('fingerprint_age_days') or {}).get('median', '—')
        lines.append(f"| {r['userinterface_name']} | {r['screens']} | {r['fingerprinted_pct']} | {r['identity_pct']} | "
                     f"{(r.get('live_node') or {}).get('label', '—')} | {age} | {corrections.get(r['userinterface_name'], 0)} |")
    return '\n'.join(lines) + '\n'


def main() -> int:
    ap = argparse.ArgumentParser(description='Localize audit report')
    ap.add_argument('--set', default=bench.DEFAULT_SET)
    ap.add_argument('--team', default=bench.DEFAULT_TEAM)
    ap.add_argument('--stale-days', type=float, default=90.0)
    ap.add_argument('--drop', type=float, default=3.0, help='points a bench kind may lose before REGRESSION')
    ap.add_argument('--overlay-fp', type=float, default=5.0, help='overlay false-positive %% on plain screens before OVERLAY_FP')
    ap.add_argument('--run-bench', action='store_true', help='score the existing set first (bench.py run)')
    a = ap.parse_args()
    bench._env()
    if a.run_bench:
        bench.run(a.set, a.team)
    from shared.src.lib.database.localize_coverage_db import get_coverage
    coverage = get_coverage(a.team)
    corrections = {r['userinterface_name']: r.get('corrections', 0) for r in coverage}
    runs = bench_runs(a.set)
    flags = flags_for(coverage, runs, a.stale_days, a.drop, overlay_fp=a.overlay_fp)
    flags += dup_fp_flags(load_fp_nodes(bench._db(), a.team))
    text = report(coverage, runs, corrections, flags)
    out_dir = os.path.join(a.set, 'audits')
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"{datetime.now().strftime('%Y-%m-%d_%H%M')}.md")
    open(path, 'w').write(text)
    print(text)
    print(f"saved: {path}")
    return 0


if __name__ == '__main__':
    sys.exit(main())
