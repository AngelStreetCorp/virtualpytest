"""score_f1.py reference.json results.json -> caller-file F1 per run, written back (empty reference: 1.0 iff the answer is empty)."""
import json, sys
ref = json.load(open(sys.argv[1])); ans = json.load(open(sys.argv[2]))
def f1(r, a):
    r, a = set(r), set(a)
    if not r: return 1.0 if not a else 0.0
    tp = len(r & a); p = tp / len(a) if a else 0; rc = tp / len(r)
    return 0.0 if tp == 0 else 2 * p * rc / (p + rc)
for run in ans:
    run['f1'] = round(f1(ref[run['q']], run['files']), 3)
    print(run['arm'], run['q'], run['run'], len(run['files']), run['f1'])
json.dump(ans, open(sys.argv[2], 'w'), indent=1)
