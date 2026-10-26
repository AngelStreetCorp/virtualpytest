"""Strict GT for functions: file does `from X import name` (anywhere) and calls name(...)."""
import ast, json, random, sys
from collections import defaultdict
from pathlib import Path
root, gp = Path(sys.argv[1]), sys.argv[2]
SKIP={"node_modules",".git","graphify-out","venv",".venv","__pycache__"}
defs=defaultdict(list); gt=defaultdict(set); lazy=defaultdict(set)
for p in root.rglob("*.py"):
    if any(s in p.parts for s in SKIP): continue
    try: t=ast.parse(p.read_text(encoding="utf-8",errors="ignore"))
    except SyntaxError: continue
    rel=str(p.relative_to(root))
    for n in t.body:
        if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)): defs[n.name].append(rel)
    top={a.asname or a.name for n in t.body if isinstance(n,ast.ImportFrom) for a in n.names}
    allimp={a.asname or a.name for n in ast.walk(t) if isinstance(n,ast.ImportFrom) for a in n.names}
    for n in ast.walk(t):
        if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id in allimp:
            gt[n.func.id].add(rel)
            if n.func.id not in top: lazy[n.func.id].add(rel)
g=json.load(open(gp)); bl=defaultdict(list)
for n in g["nodes"]: bl[n.get("label","").rstrip("()").split(".")[-1]].append(n["id"])
inc=defaultdict(set)
for e in g["links"]:
    if e["relation"] in("calls","indirect_call"): inc[e["target"]].add(e["source_file"])
names=[n for n,d in defs.items() if len(d)==1 and len(gt[n]-set(d))>=1]
random.seed(7); s=random.sample(names,min(300,len(names)))
T=TP=G=LT=LTP=0
for n in s:
    own=defs[n][0]; truth=gt[n]-{own}; got=set().union(*[inc[x] for x in bl.get(n,[])] or [set()])-{own}
    T+=len(truth); TP+=len(truth&got); G+=len(got)
    lz=lazy[n]&truth; LT+=len(lz); LTP+=len(lz&got)
print(f"functions: names={len(s)} caller-files={T} recall={TP/T:.0%} precision={TP/max(G,1):.0%}")
print(f"  of which lazy (import inside function): {LT} files, recall={LTP/max(LT,1):.0%}")
print(f"  top-level imports only: recall={(TP-LTP)/max(T-LT,1):.0%}")
