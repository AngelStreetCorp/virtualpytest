"""Ground truth: Python files (and enclosing functions) that call a given name, via stdlib ast."""
import ast
import json
import sys
from pathlib import Path

SKIP = {"node_modules", ".git", "graphify-out", "venv", ".venv", "__pycache__"}


def callers(root: Path, name: str):
    hits = {}
    for p in root.rglob("*.py"):
        if any(part in SKIP for part in p.parts):
            continue
        try:
            tree = ast.parse(p.read_text(encoding="utf-8", errors="ignore"))
        except SyntaxError:
            continue
        stack = []

        class V(ast.NodeVisitor):
            def _fn(self, node):
                stack.append(node.name)
                self.generic_visit(node)
                stack.pop()

            visit_FunctionDef = visit_AsyncFunctionDef = _fn

            def visit_Call(self, node):
                f = node.func
                n = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else None
                if n == name:
                    hits.setdefault(str(p.relative_to(root)), set()).add(stack[-1] if stack else "<module>")
                self.generic_visit(node)

        V().visit(tree)
    return {k: sorted(v) for k, v in sorted(hits.items())}


if __name__ == "__main__":
    root, name = Path(sys.argv[1]), sys.argv[2]
    res = callers(root, name)
    print(json.dumps({"name": name, "file_count": len(res), "files": res}, indent=1))
