"""Round-4 AST cross-check for the references (stdlib only, no code_index). Run from the frozen tree root:
python3 xcheck_round4.py > xcheck_round4.txt. Lists name-based call sites with receiver and enclosing function."""
import ast, sys, warnings
from collections import defaultdict
from pathlib import Path
warnings.simplefilter("ignore")
SKIP = {"node_modules", ".git", "venv", ".venv", "__pycache__"}
calls = defaultdict(list)
for p in Path('.').rglob("*.py"):
    if any(s in p.parts for s in SKIP) or p.parts[0] == 'features': continue
    try: t = ast.parse(p.read_text(errors="ignore"))
    except SyntaxError: continue
    st = []
    class V(ast.NodeVisitor):
        def _f(self, n): st.append(n.name); self.generic_visit(n); st.pop()
        visit_FunctionDef = visit_AsyncFunctionDef = _f
        def visit_Call(self, n):
            f = n.func
            nm = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else None
            if nm:
                recv = ast.unparse(f.value)[:50] if isinstance(f, ast.Attribute) else ''
                calls[nm].append((str(p), n.lineno, recv, st[-1] if st else '<module>'))
            self.generic_visit(n)
    V().visit(t)
for name in ['click_element', 'execute_command', 'normalize_script_ref', 'resolve_script_identity']:
    print(f'== {name}')
    for c in sorted(calls[name]): print(*c, sep=' | ')
print('== level 2 candidates (callers of enclosing fns of resolve_script_identity)')
for f in sorted({c[3] for c in calls['resolve_script_identity'] if c[3] != '<module>'}):
    for c in sorted(calls[f]): print(f, *c, sep=' | ')
