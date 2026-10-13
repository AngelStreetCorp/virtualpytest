#!/usr/bin/env python3
"""Token spend per product video, so the agents that make them can be compared.

One JSON line per (video, session) in token_log.jsonl next to this file:

  python3 token_log.py claude --video 25 --session <uuid> [--projects ~/.claude/projects]
      sums a Claude Code session (main transcript + its subagents), each message counted once
  python3 token_log.py mcode --video 25 --stream run.jsonl
      sums a MiniMax Code run saved with `mcode exec --output-format stream-json > run.jsonl`
  python3 token_log.py report
      one row per video: tokens, new tokens, API-equivalent $, agents

"New" tokens = everything except cache reads (input + cache writes + output): what a fresh
session per video and a short context actually move. Prices are API list prices per million
tokens, for comparison only (a subscription plan pays in quota, not dollars).
"""
import argparse
import collections
import datetime
import glob
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(HERE, 'token_log.jsonl')

# $ per million tokens: input, cache write (1 h TTL = 2x input, what Claude Code uses), cache read, output
PRICES = {
    'claude-opus-5-5': (4.00, 8.00, 0.20, 20.00),
    'claude-sonnet-5-5': (2.00, 4.00, 0.20, 10.00),
    'claude-haiku-5-5': (0.10, 0.20, 0.01, 0.50),
    'MiniMax-M3': (0.0, 0.0, 0.0, 0.0),  # flat MiniMax plan: no marginal $
}
KEYS = ('input', 'cache_write', 'cache_read', 'output')


def cost(model, t):
    p = PRICES.get(model)
    return None if p is None else sum(t[k] * p[i] for i, k in enumerate(KEYS)) / 1e6


def append(row):
    with open(LOG, 'a') as f:
        f.write(json.dumps(row) + '\n')
    print(json.dumps(row))


def claude(args):
    files = glob.glob(os.path.join(os.path.expanduser(args.projects), '*', args.session + '.jsonl'))
    if not files:
        sys.exit(f'no transcript {args.session}.jsonl under {args.projects}')
    main = files[0]
    files += glob.glob(os.path.join(main[:-6], 'subagents', '*.jsonl'))
    by_model = collections.defaultdict(collections.Counter)
    seen, ts = set(), []
    for path in files:
        for line in open(path, errors='ignore'):
            try:
                o = json.loads(line)
            except ValueError:
                continue
            if o.get('timestamp'):
                ts.append(o['timestamp'])
            m = o.get('message') or {}
            u, mid = m.get('usage'), m.get('id')
            if not u or not mid or mid in seen:
                continue
            seen.add(mid)
            t = by_model[m.get('model') or '?']
            t['input'] += u.get('input_tokens') or 0
            t['cache_write'] += u.get('cache_creation_input_tokens') or 0
            t['cache_read'] += u.get('cache_read_input_tokens') or 0
            t['output'] += u.get('output_tokens') or 0
    for model, t in by_model.items():
        if model == '<synthetic>':
            continue
        append({'video': args.video, 'agent': 'claude-code', 'model': model, 'session': args.session,
                'from': min(ts)[:16], 'to': max(ts)[:16], **{k: t[k] for k in KEYS}, 'note': args.note})


def mcode(args):
    t, model, sid, first, last = collections.Counter(), '?', '?', None, None
    for line in open(args.stream, errors='ignore'):
        try:
            o = json.loads(line)
        except ValueError:
            continue
        ms = o.get('timestampMs')
        if ms:
            first, last = first or ms, ms
        if o.get('type') != 'turn.completed':  # exec.completed repeats the last turn's usage
            continue
        u = o.get('usage') or {}
        model = (o.get('model') or {}).get('modelId', model)
        sid = o.get('sessionId', sid)
        read = u.get('cacheReadTokens') or 0
        t['cache_read'] += read
        t['input'] += (u.get('inputTokens') or 0) - read  # MiniMax's inputTokens include the cache reads
        t['output'] += u.get('outputTokens') or 0
    iso = lambda ms: datetime.datetime.utcfromtimestamp(ms / 1000).isoformat()[:16] if ms else None
    append({'video': args.video, 'agent': 'mcode', 'model': model, 'session': sid,
            'from': iso(first), 'to': iso(last), **{k: t[k] for k in KEYS}, 'note': args.note})


def report(_):
    rows = [json.loads(l) for l in open(LOG)] if os.path.exists(LOG) else []
    by_video = collections.OrderedDict()
    for r in rows:
        by_video.setdefault(r['video'], []).append(r)
    print(f"{'video':<10} {'total M':>8} {'new M':>7} {'out k':>7} {'$ API':>8}  agents")
    for video, rs in by_video.items():
        tot = sum(r[k] for r in rs for k in KEYS)
        new = sum(r[k] for r in rs for k in ('input', 'cache_write', 'output'))
        out = sum(r['output'] for r in rs)
        costs = [cost(r['model'], r) for r in rs]
        usd = '?' if None in costs else f'{sum(costs):.0f}'
        agents = ', '.join(sorted({f"{r['agent']}:{r['model']}" for r in rs}))
        print(f'{video:<10} {tot / 1e6:8.1f} {new / 1e6:7.1f} {out / 1e3:7.0f} {usd:>8}  {agents}')


p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
sub = p.add_subparsers(dest='cmd', required=True)
c = sub.add_parser('claude')
c.add_argument('--video', required=True)
c.add_argument('--session', required=True)
c.add_argument('--projects', default='~/.claude/projects')
c.add_argument('--note', default='')
m = sub.add_parser('mcode')
m.add_argument('--video', required=True)
m.add_argument('--stream', required=True)
m.add_argument('--note', default='')
sub.add_parser('report')
a = p.parse_args()
{'claude': claude, 'mcode': mcode, 'report': report}[a.cmd](a)
