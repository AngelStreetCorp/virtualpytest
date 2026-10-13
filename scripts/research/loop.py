#!/usr/bin/env python3
"""Research loop runner: one try of a task's declared loop, keep or revert, log the row.

Usage:
  loop.py spec TASK-36
  loop.py baseline TASK-36 [--no-lease]
  loop.py try TASK-36 --note "<what changed and why>" [--no-lease]
  loop.py status TASK-36

Convention: docs/agent/research/LOOP.md
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import os
import re
import secrets
import subprocess
import sys
import time
from dataclasses import dataclass, field

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
COLUMNS = ['id', 'ts', 'parent', 'kept', 'metric', 'duration_s', 'commit', 'note']
REGISTRY_HOST = os.environ.get('VPT_LEASE_HOST', 'proxmox')


@dataclass
class Spec:
    task: str
    doc: str
    metric_name: str
    higher: bool
    edit: list[str]
    run: str
    budget_min: float
    lease: list[str] = field(default_factory=list)
    results: str = ''


def find_doc(task: str, root: str = ROOT) -> str:
    hits = [p for p in sorted(glob.glob(os.path.join(root, 'docs', 'tasks', f'{task}*.md')))
            if 'handover' not in os.path.basename(p).lower()]
    if not hits:
        raise SystemExit(f'no task doc for {task} under docs/tasks/')
    return hits[0]


def parse_spec(task: str, text: str, doc: str = '') -> Spec:
    m = re.search(r'^## Loop\s*$', text, re.M)
    if not m:
        raise SystemExit(f'{task}: no "## Loop" section in {doc or "the task doc"}')
    body = text[m.end():]
    nxt = re.search(r'^#{1,3} ', body, re.M)
    if nxt:
        body = body[:nxt.start()]
    body = body.replace('```', '')
    keys: dict[str, str] = {}
    for line in body.splitlines():
        km = re.match(r'^\s*([a-z_]+)\s*:\s*(.+?)\s*$', line)
        if km:
            keys[km.group(1)] = km.group(2)
    for k in ('metric', 'edit', 'run', 'budget'):
        if k not in keys:
            raise SystemExit(f'{task}: Loop section lacks "{k}:"')
    metric = keys['metric']
    higher = True
    dm = re.search(r',\s*(higher|lower)\s*$', metric)
    if dm:
        higher = dm.group(1) == 'higher'
        metric = metric[:dm.start()].strip()
    bm = re.search(r'([\d.]+)', keys['budget'])
    if not bm:
        raise SystemExit(f'{task}: budget must be minutes, got {keys["budget"]!r}')
    return Spec(
        task=task,
        doc=doc,
        metric_name=metric,
        higher=higher,
        edit=[e.strip() for e in keys['edit'].split(',') if e.strip()],
        run=keys['run'],
        budget_min=float(bm.group(1)),
        lease=keys.get('lease', '').split(),
        results=keys.get('results') or f'docs/tasks/{task}/results.tsv',
    )


def load_spec(task: str, root: str = ROOT) -> Spec:
    doc = find_doc(task, root)
    with open(doc, encoding='utf-8') as f:
        return parse_spec(task, f.read(), os.path.relpath(doc, root))


# ---- results file ----

def read_rows(path: str) -> list[dict[str, str]]:
    if not os.path.exists(path):
        return []
    rows = []
    with open(path, encoding='utf-8') as f:
        header = None
        for line in f:
            line = line.rstrip('\n')
            if not line.strip():
                continue
            cells = line.split('\t')
            if header is None:
                header = cells
                continue
            rows.append(dict(zip(header, cells)))
    return rows


def append_row(path: str, row: dict[str, str]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    new = not os.path.exists(path) or os.path.getsize(path) == 0
    with open(path, 'a', encoding='utf-8') as f:
        if new:
            f.write('\t'.join(COLUMNS) + '\n')
        f.write('\t'.join(str(row.get(c, '')).replace('\t', ' ').replace('\n', ' ') for c in COLUMNS) + '\n')


def best_kept(rows: list[dict[str, str]], higher: bool) -> dict[str, str] | None:
    kept = [r for r in rows if r.get('kept') == 'yes' and is_number(r.get('metric', ''))]
    if not kept:
        return None
    return max(kept, key=lambda r: float(r['metric']) if higher else -float(r['metric']))


def is_number(s: str) -> bool:
    try:
        float(s)
        return True
    except ValueError:
        return False


def is_better(new: float, old: float | None, higher: bool) -> bool:
    if old is None:
        return True
    return new > old if higher else new < old


# ---- git and lease ----

def git(args: list[str], root: str = ROOT) -> str:
    return subprocess.run(['git', *args], cwd=root, capture_output=True, text=True, check=True).stdout


def dirty_outside(edit: list[str], root: str = ROOT) -> list[str]:
    out = git(['status', '--porcelain', '--untracked-files=no'], root)
    dirty = [l[3:].strip() for l in out.splitlines() if l.strip()]
    return [p for p in dirty if p not in edit]


def claim(spec: Spec, agent: str) -> str | None:
    if not spec.lease:
        return None
    provider = os.environ.get('VPT_LEASE_PROVIDER', '')
    cmd = f"~/bin/vpt-lease claim {' '.join(spec.lease)} --agent {agent} --purpose 'research {spec.task}' --ttl {int(spec.budget_min) + 10}"
    if provider:
        cmd += f" --provider {provider}"
    r = subprocess.run(['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=20', REGISTRY_HOST, cmd],
                       capture_output=True, text=True)
    if r.returncode == 3:
        raise SystemExit(f'lease busy: {r.stdout.strip() or r.stderr.strip()}')
    if r.returncode != 0:
        raise SystemExit(f'lease claim failed ({r.returncode}): {r.stderr.strip()}')
    return r.stdout.strip().split()[-1]


def release(lease_id: str | None) -> None:
    if lease_id:
        subprocess.run(['ssh', '-o', 'BatchMode=yes', REGISTRY_HOST, f'~/bin/vpt-lease release {lease_id}'],
                       capture_output=True, text=True)


# ---- one try ----

def run_once(spec: Spec, root: str = ROOT) -> tuple[float | None, float, str]:
    """Runs the spec's command. Returns (metric or None, seconds, last output line)."""
    t0 = time.time()
    try:
        r = subprocess.run(spec.run, shell=True, cwd=root, capture_output=True, text=True,
                           timeout=spec.budget_min * 60)
    except subprocess.TimeoutExpired:
        return None, time.time() - t0, 'timeout'
    sys.stdout.write(r.stdout[-4000:])
    if r.stderr.strip():
        sys.stderr.write(r.stderr[-2000:])
    lines = [l for l in r.stdout.splitlines() if l.strip()]
    mm = None
    for line in reversed(lines):
        m = re.match(r'^\s*metric\s*=\s*([-\d.]+)\s*$', line)
        if m:
            mm = float(m.group(1))
            break
    tail = lines[-1] if lines else ''
    if r.returncode != 0:
        return None, time.time() - t0, f'exit {r.returncode}: {tail[:80]}'
    return mm, time.time() - t0, tail[:80]


def do_try(spec: Spec, note: str, baseline: bool, use_lease: bool, root: str = ROOT) -> dict[str, str]:
    outside = dirty_outside(spec.edit, root)
    if outside:
        raise SystemExit(f'refusing: files outside edit are modified: {", ".join(outside)}')
    diff = git(['diff', '--', *spec.edit], root).strip()
    if baseline and diff:
        raise SystemExit('baseline needs a clean edit file; commit or revert first')
    if not baseline and not diff:
        raise SystemExit('nothing changed in the edit files; make the change, then try')
    results = os.path.join(root, spec.results)
    rows = read_rows(results)
    best = best_kept(rows, spec.higher)
    if not baseline and best is None:
        raise SystemExit('no baseline yet: run `loop.py baseline` first')
    agent = os.environ.get('VPT_LEASE_AGENT') or f'{os.uname().nodename.split(".")[0]}:research-{spec.task}'
    lease_id = claim(spec, agent) if use_lease else None
    try:
        metric, seconds, tail = run_once(spec, root)
    finally:
        release(lease_id)
    row = {
        'id': secrets.token_hex(3),
        'ts': dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H:%MZ'),
        'parent': best['id'] if best else '-',
        'kept': 'no',
        'metric': '' if metric is None else f'{metric:g}',
        'duration_s': f'{seconds:.0f}',
        'commit': '',
        'note': note if metric is not None else f'{note} [error: {tail}]',
    }
    if metric is None:
        if not baseline:
            git(['checkout', '--', *spec.edit], root)
        append_row(results, row)
        print(f'error: no metric ({tail}); reverted' if not baseline else f'error: no metric ({tail})')
        return row
    old = float(best['metric']) if best else None
    if baseline or is_better(metric, old, spec.higher):
        row['kept'] = 'yes'
        if not baseline:
            git(['add', '--', *spec.edit], root)
            git(['commit', '-q', '-m', f'loop({spec.task}): kept {spec.metric_name} {metric:g} — {note}'], root)
            row['commit'] = git(['rev-parse', '--short', 'HEAD'], root).strip()
        else:
            row['commit'] = git(['rev-parse', '--short', 'HEAD'], root).strip()
        verdict = 'baseline' if baseline else f'kept ({old:g} → {metric:g})'
    else:
        git(['checkout', '--', *spec.edit], root)
        verdict = f'reverted ({metric:g} vs best {old:g})'
    append_row(results, row)
    print(f'{spec.task}: {verdict}; {spec.metric_name}={metric:g}; {seconds:.0f}s; row {row["id"]} parent {row["parent"]}')
    return row


def status(spec: Spec, root: str = ROOT) -> str:
    rows = read_rows(os.path.join(root, spec.results))
    best = best_kept(rows, spec.higher)
    kept = sum(1 for r in rows if r.get('kept') == 'yes')
    lines = [f'{spec.task}: {spec.metric_name} ({"higher" if spec.higher else "lower"} is better)',
             f'  tries {len(rows)}, kept {kept}, best {best["metric"] if best else "-"} (row {best["id"] if best else "-"})']
    if rows:
        last = rows[-1]
        lines.append(f'  last {last["ts"]} metric {last["metric"] or "error"} {"kept" if last["kept"] == "yes" else "reverted"}: {last["note"]}')
    return '\n'.join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('cmd', choices=['spec', 'baseline', 'try', 'status'])
    ap.add_argument('task')
    ap.add_argument('--note', default='')
    ap.add_argument('--no-lease', action='store_true')
    a = ap.parse_args(argv)
    spec = load_spec(a.task)
    if a.cmd == 'spec':
        for k, v in vars(spec).items():
            print(f'{k:12} {v}')
        return 0
    if a.cmd == 'status':
        print(status(spec))
        return 0
    if a.cmd == 'try' and not a.note:
        ap.error('--note is required for try: say what changed and why')
    do_try(spec, a.note or 'baseline', a.cmd == 'baseline', not a.no_lease)
    return 0


if __name__ == '__main__':
    sys.exit(main())
