"""Round-4 scorer for MiniMax `mcode exec --output-format stream-json` transcripts.
usage: score_round4.py <dir with {Q}_{arm}_{n}.jsonl> <reference_round4.json> <results_round4_minimax.json>"""
import json, re, sys, os, glob
from statistics import mean, median
D, REF, OUT = sys.argv[1:4]
ref = json.load(open(REF))
def f1(r, a):
    r, a = set(r), set(a)
    tp = len(r & a)
    return 0.0 if not tp else 2 * tp / (len(a) + len(r))
def parse(p):
    kb, tools, used, final, t0, t1, status, errs = 0, 0, False, '', None, None, None, 0
    for line in open(p):
        try: m = json.loads(line)
        except Exception: continue
        ts = m.get('timestampMs'); t0 = t0 or ts; t1 = ts or t1
        it = m.get('item') or {}
        if m['type'] == 'item.completed' and it.get('type') == 'tool_call':
            tc = it.get('toolCall') or {}
            tools += 1
            if 'gen_code_index' in json.dumps(tc.get('input')): used = True
            for x in (tc.get('output') or {}).get('content') or []:
                kb += len(x.get('text', ''))
        elif m['type'] == 'item.completed' and it.get('type') == 'agent_message':
            final = it.get('content') or final
        elif m['type'] == 'exec.completed':
            status = (m.get('result') or {}).get('status'); final = (m.get('result') or {}).get('output') or final
    blocks = re.findall(r'```json\s*(\{.*?\})\s*```', final, re.S)
    files = None
    if blocks:
        try: files = json.loads(blocks[-1])['files']
        except Exception: pass
    return dict(files=files, kb=kb / 1000, tools=tools, used=used, secs=((t1 - t0) / 1000) if t0 else None, status=status)
res = []
for p in sorted(glob.glob(f'{D}/*.jsonl')):
    q, arm, n = os.path.basename(p)[:-6].split('_')
    r = parse(p)
    r.update(q=q, arm=arm, run=int(n), f1=round(f1(ref[q], r['files']), 3) if r['files'] is not None else 0.0, parsed=r['files'] is not None)
    res.append(r)
json.dump(res, open(OUT, 'w'), indent=1)
def row(label, a, b):
    if not a or not b: return
    m = lambda xs, k: f"{median(x[k] for x in xs):.1f} ({mean(x[k] for x in xs):.1f})"
    print(f"| {label} | {mean(r['f1'] for r in a):.3f} | {mean(r['f1'] for r in b):.3f} | {m(a,'kb')} | {m(b,'kb')} | {mean(r['tools'] for r in a):.1f} | {mean(r['tools'] for r in b):.1f} | {m(a,'secs')} | {m(b,'secs')} | {sum(r['used'] for r in b)}/{len(b)} | {sum(not r['parsed'] for r in res_all if r['arm'] in ('A','B') and r['q']==a[0]['q'] ) if False else ''} |")
res_all = res
res = [r for r in res if r['parsed']]  # as in round 3: runs without a json block are excluded from the stats (listed in the unparsed column)
print('| Q | A F1 | B F1 | A KB med (mean) | B KB med (mean) | A calls | B calls | A s | B s | B ran CLI | unparsed |')
print('|---|---|---|---|---|---|---|---|---|---|---|')
for q in ['R1', 'R2', 'R3', 'R4', 'R5', 'all']:
    sel = lambda arm: [r for r in res if r['arm'] == arm and (q == 'all' or r['q'] == q)]
    row(q, sel('A'), sel('B'))
