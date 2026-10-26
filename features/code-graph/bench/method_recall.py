"""Methods: unique, distinctive names (>=14 chars, not dunder), callers via obj.name(...)."""
import ast, json, random, sys
from collections import defaultdict
from pathlib import Path
root, gp = Path(sys.argv[1]), sys.argv[2]
SKIP={"node_modules",".git","graphify-out","venv",".venv","__pycache__"}
defs=defaultdict(list); gt=defaultdict(set); selfc=defaultdict(set)
for p in root.rglob("*.py"):
    if any(s in p.parts for s in SKIP): continue
    try: t=ast.parse(p.read_text(encoding="utf-8",errors="ignore"))
    except SyntaxError: continue
    rel=str(p.relative_to(root))
    for n in ast.walk(t):
        if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef)): defs[n.name].append(rel)
        if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute):
            gt[n.func.attr].add(rel)
            if isinstance(n.func.value,ast.Name) and n.func.value.id in("self","cls"): selfc[n.func.attr].add(rel)
g=json.load(open(gp)); bl=defaultdict(list)
for n in g["nodes"]:
    if n.get("label","").startswith("."): bl[n["label"].rstrip("()")[1:]].append(n["id"])
inc=defaultdict(set)
for e in g["links"]:
    if e["relation"] in("calls","indirect_call"): inc[e["target"]].add(e["source_file"])
names=[n for n,d in defs.items() if len(d)==1 and len(n)>=14 and n in bl and len(gt[n]-set(d))>=1]
random.seed(7); s=random.sample(names,min(300,len(names)))
T=TP=G=0; ST=STP=0
for n in s:
    own=defs[n][0]; truth=gt[n]-{own}; got=set().union(*[inc[x] for x in bl[n]])-{own}
    T+=len(truth); TP+=len(truth&got); G+=len(got)
    own_self = n in selfc and own in selfc[n]
    if own_self: ST+=1; STP+= own in set().union(*[inc[x] for x in bl[n]])
print(f"methods, cross-file callers: names={len(s)} caller-files={T} recall={TP/T:.0%} precision={TP/max(G,1):.0%}")
print(f"methods, same-file self.x() calls resolved: {STP}/{ST} = {STP/max(ST,1):.0%}")
