import ast, sys, warnings, re
from collections import defaultdict
from pathlib import Path
warnings.simplefilter("ignore")
root = Path('.')
SKIP = {"node_modules", ".git", "venv", ".venv", "__pycache__"}
calls = defaultdict(list)   # name -> (file, line, receiver, enclosing)
for p in root.rglob("*.py"):
    if any(s in p.parts for s in SKIP): continue
    try: t = ast.parse(p.read_text(errors="ignore"))
    except SyntaxError: continue
    rel = str(p); st = []
    class V(ast.NodeVisitor):
        def _f(self, n): st.append(n.name); self.generic_visit(n); st.pop()
        visit_FunctionDef = visit_AsyncFunctionDef = _f
        def visit_Call(self, n):
            f = n.func
            nm = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else None
            if nm:
                recv = ast.unparse(f.value)[:50] if isinstance(f, ast.Attribute) else ''
                calls[nm].append((rel, n.lineno, recv, st[-1] if st else '<module>'))
            self.generic_visit(n)
    V().visit(t)
print("== .start() receivers in files that mention RunStore / LeagueRunner")
for cls in ['RunStore', 'LeagueRunner']:
    files = {c[0] for c in calls['start'] if cls in Path(c[0]).read_text(errors='ignore')}
    for c in calls['start']:
        if c[0] in files: print(cls, c)
print("== clear_unified_cache"); [print(c) for c in calls['clear_unified_cache']]
print("== H5 level1 (get_device_segment_duration)")
l1 = calls['get_device_segment_duration']; [print(c) for c in l1]
fns = {c[3] for c in l1 if c[3] != '<module>'}
print("== H5 level2 candidates by name:", sorted(fns))
for f in sorted(fns):
    for c in calls[f]: print(f, c)
