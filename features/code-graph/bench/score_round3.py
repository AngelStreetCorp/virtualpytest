import json, re, sys, os
from statistics import mean, median
# usage: score_round3.py <dir with runs.json> <reference_round3.json> <agent transcripts dir>
B3 = sys.argv[1]; ref = json.load(open(sys.argv[2])); runs = json.load(open(f'{B3}/runs.json')); T = sys.argv[3]
def f1(r, a):
    r, a = set(r), set(a)
    if not r: return 1.0 if not a else 0.0
    tp = len(r & a); return 0.0 if not tp else 2*tp/(len(a)+len(r))
def parse(i):
    p = f'{T}/{i}.output'
    if not os.path.exists(p): return None
    kb, tools, last, used = 0, 0, '', False
    for line in open(p):
        try: m = json.loads(line)
        except Exception: continue
        c = (m.get('message') or {}).get('content')
        if not isinstance(c, list): continue
        for b in c:
            if b.get('type') == 'tool_use': tools += 1; used |= 'gen_code_index' in json.dumps(b.get('input'))
            elif b.get('type') == 'tool_result':
                cc = b.get('content'); kb += sum(len(x.get('text','')) for x in cc if isinstance(x, dict)) if isinstance(cc, list) else len(cc or '')
            elif b.get('type') == 'text': last = b['text']
    blocks = re.findall(r'```json\s*(\{.*?\})\s*```', last, re.S)
    if not blocks: return None
    return dict(files=json.loads(blocks[-1])['files'], kb=kb/1000, tools=tools, used=used)
out = []
for model, arms in runs.items():
    for arm, qs in arms.items():
        for q, ids in qs.items():
            for n, i in enumerate(ids, 1):
                r = parse(i)
                if r: out.append(dict(model=model, arm=arm, q=q, run=n, f1=round(f1(ref[q], r['files']), 3), **r))
json.dump(out, open(f'{B3}/results_r3.json', 'w'), indent=1)
for model in runs:
    print(f'## {model}')
    print('| Q | A F1 | B F1 | A KB med (mean) | B KB med (mean) | A calls | B calls | B used tool | n A/B |')
    for q in ['H1','H2','H3','H4','H5','all']:
        a = [r for r in out if r['model']==model and r['arm']=='A' and (q=='all' or r['q']==q)]
        b = [r for r in out if r['model']==model and r['arm']=='B' and (q=='all' or r['q']==q)]
        if not a or not b: continue
        print(f"| {q} | {mean(r['f1'] for r in a):.3f} | {mean(r['f1'] for r in b):.3f} | {median(r['kb'] for r in a):.1f} ({mean(r['kb'] for r in a):.1f}) | {median(r['kb'] for r in b):.1f} ({mean(r['kb'] for r in b):.1f}) | {mean(r['tools'] for r in a):.1f} | {mean(r['tools'] for r in b):.1f} | {sum(r['used'] for r in b)}/{len(b)} | {len(a)}/{len(b)} |")
