"""Scan one Python file with the stdlib ast: definitions, call sites, imports, Flask routes, URL literals."""
import ast
from typing import List, Optional

from .constants import RECEIVER_MAX_CHARS, ROUTE_DECORATORS, URL_PREFIXES, WILDCARD
from .types import CallSite, Definition, FileScan, RouteDef, UrlRef


def module_name(rel_path: str) -> str:
    """'shared/src/lib/x.py' -> 'shared.src.lib.x'; package __init__ -> package."""
    parts = rel_path[:-3].split("/")
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _resolve_relative(module: str, is_package: bool, level: int, target: Optional[str]) -> str:
    base = module.split(".") if module else []
    if not is_package:
        base = base[:-1]
    if level > 1:
        base = base[: len(base) - (level - 1)]
    return ".".join(base + ([target] if target else []))


def _signature(node: ast.AST) -> str:
    try:
        return f"({ast.unparse(node.args)})"
    except Exception:
        return ""


def _str_value(node: ast.AST) -> Optional[str]:
    """Literal string, or an f-string with formatted parts replaced by '*'."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        out = []
        for v in node.values:
            if isinstance(v, ast.Constant) and isinstance(v.value, str):
                out.append(v.value)
            else:
                out.append(WILDCARD)
        return "".join(out)
    return None


def _type_name(node: Optional[ast.AST]) -> str:
    """Class named by an annotation: X, mod.X, Optional[X], 'X' -> 'X'; '' for anything else."""
    if node is None:
        return ""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value.split(".")[-1].strip("[] ")
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    if isinstance(node, ast.Subscript) and _type_name(node.value) == "Optional":
        return _type_name(node.slice)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):  # X | None
        left = _type_name(node.left)
        return left if left and left != "None" else _type_name(node.right)
    return ""


def _call_hint(node: ast.AST) -> str:
    """'call:f' for f(...) / mod.f(...) / obj.f(...): the value is whatever f returns (a class builds itself)."""
    if isinstance(node, ast.Call):
        f = node.func
        name = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else ""
        return f"call:{name}" if name else ""
    return ""


def _returns_hint(node) -> str:
    """Return type of a def: its annotation, else a single `return X(...)` shape found in its body."""
    ann = _type_name(node.returns)
    if ann and ann != "None":
        return f"class:{ann}"
    hints = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Return) and sub.value is not None:
            h = _call_hint(sub.value)
            if h:
                hints.add(h)
    return hints.pop() if len(hints) == 1 else ""


def _items_hint(hints) -> str:
    """'items:H' when every element has the same plain hint H (a list/dict/set of one class), else ''."""
    found = set(hints)
    if len(found) != 1:
        return ""
    h = found.pop()
    return f"items:{h}" if h and not h.startswith("items:") else ""


def _is_fixture(node) -> bool:
    for dec in node.decorator_list:
        target = dec.func if isinstance(dec, ast.Call) else dec
        if (isinstance(target, ast.Attribute) and target.attr == "fixture") or \
                (isinstance(target, ast.Name) and target.id == "fixture"):
            return True
    return False


def _blueprint_prefixes(tree: ast.Module) -> dict:
    """{blueprint_var: url_prefix} from `bp = Blueprint(..., url_prefix='/x')`."""
    prefixes = {}
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Assign) and isinstance(node.value, ast.Call)):
            continue
        func = node.value.func
        fname = func.id if isinstance(func, ast.Name) else getattr(func, "attr", "")
        if fname != "Blueprint":
            continue
        prefix = ""
        for kw in node.value.keywords:
            if kw.arg == "url_prefix":
                prefix = _str_value(kw.value) or ""
        for t in node.targets:
            if isinstance(t, ast.Name):
                prefixes[t.id] = prefix
    return prefixes


def _dotted(node: ast.AST) -> str:
    """'a' / 'a.b' for a name or an attribute chain of names, else ''."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted(node.value)
        return f"{base}.{node.attr}" if base else ""
    return ""


class _Visitor(ast.NodeVisitor):
    def __init__(self, scan: FileScan, prefixes: dict, is_package: bool):
        self.scan = scan
        self.prefixes = prefixes
        self.is_package = is_package
        self.classes: List[str] = []
        self.funcs: List[str] = []
        self.scopes: List[dict] = [{}]   # local name -> receiver hint, innermost last

    # --- scopes -------------------------------------------------------------
    def _enclosing(self) -> str:
        if not self.funcs:
            return self.classes[-1] if self.classes else "<module>"
        owner = self.classes[-1] + "." if self.classes else ""
        return owner + self.funcs[-1]

    def visit_ClassDef(self, node: ast.ClassDef):
        bases = tuple(b for b in (_type_name(x) for x in node.bases) if b)
        self.scan.definitions.append(Definition(node.name, self.scan.file, node.lineno, "class", bases=bases))
        self.classes.append(node.name)
        self.generic_visit(node)
        self.classes.pop()

    def _visit_func(self, node):
        in_class = bool(self.classes) and not self.funcs
        self.scan.definitions.append(Definition(
            node.name, self.scan.file, node.lineno,
            "method" if in_class else "function",
            self.classes[-1] if in_class else None,
            _signature(node),
            bool(self.funcs),
            _returns_hint(node),
            _is_fixture(node),
        ))
        self._collect_routes(node)
        scope = {}
        args = node.args
        for a in args.posonlyargs + args.args + args.kwonlyargs:
            t = _type_name(a.annotation)
            scope[a.arg] = f"class:{t}" if t else f"param:{a.arg}"
        self.funcs.append(node.name)
        self.scopes.append(scope)
        self.generic_visit(node)
        self.scopes.pop()
        self.funcs.pop()

    visit_FunctionDef = visit_AsyncFunctionDef = _visit_func

    # --- imports ------------------------------------------------------------
    def visit_Import(self, node: ast.Import):
        for a in node.names:
            self.scan.imported_modules.append(a.name)
            self.scan.imported_names[(a.asname or a.name).split(".")[0]] = a.name

    def visit_ImportFrom(self, node: ast.ImportFrom):
        mod = node.module or ""
        if node.level:
            mod = _resolve_relative(self.scan.module, self.is_package, node.level, node.module)
        self.scan.imported_modules.append(mod)
        for a in node.names:
            self.scan.imported_names[a.asname or a.name] = f"{mod}.{a.name}" if mod else a.name

    # --- receiver hints -----------------------------------------------------
    def _lookup(self, name: str) -> str:
        for scope in reversed(self.scopes):
            if name in scope:
                return scope[name]
        return ""

    def _value_hint(self, value: ast.AST) -> str:
        """What an assigned value is: a container of one class ('items:H'), else the same as a receiver."""
        if isinstance(value, ast.Dict):
            return _items_hint(self._expr_hint(v) for v in value.values) if None not in value.keys else ""
        if isinstance(value, (ast.List, ast.Tuple, ast.Set)):
            return _items_hint(self._expr_hint(e) for e in value.elts)
        if isinstance(value, (ast.ListComp, ast.SetComp, ast.GeneratorExp)):
            return _items_hint([self._expr_hint(value.elt)])
        if isinstance(value, ast.DictComp):
            return _items_hint([self._expr_hint(value.value)])
        return self._expr_hint(value)

    @staticmethod
    def _elem(hint: str) -> str:
        """Hint of one element of a container with this hint."""
        if hint.startswith("items:"):
            return hint[len("items:"):]
        return f"elem:{hint}" if hint.startswith(("selfattr:", "attr:")) else ""

    def _expr_hint(self, value: ast.AST) -> str:
        """What an expression is, from the file alone: a local name, self.x, y.x, d[k], d.get(k), getattr(o, "x"), f()."""
        if isinstance(value, ast.Name):
            return self._lookup(value.id)
        if isinstance(value, ast.Attribute):
            if isinstance(value.value, ast.Name) and value.value.id == "self" and self.classes:
                return f"selfattr:{self.classes[-1]}.{value.attr}"
            inner = self._expr_hint(value.value)
            return f"attr:{inner}|{value.attr}" if inner and not inner.startswith("items:") else ""
        if isinstance(value, ast.Subscript):
            return self._elem(self._expr_hint(value.value))
        if isinstance(value, ast.Call):
            f = value.func
            if isinstance(f, ast.Name) and f.id == "getattr" and len(value.args) >= 2 \
                    and isinstance(value.args[1], ast.Constant) and isinstance(value.args[1].value, str):
                obj = value.args[0]
                if isinstance(obj, ast.Name) and obj.id == "self" and self.classes:
                    obj_hint = f"class:{self.classes[-1]}"
                else:
                    obj_hint = self._expr_hint(obj)
                return f"attr:{obj_hint}|{value.args[1].value}" if obj_hint and not obj_hint.startswith("items:") else ""
            if isinstance(f, ast.Attribute) and f.attr == "get":  # d.get(k) on a container of one class
                elem = self._elem(self._expr_hint(f.value))
                if elem:
                    return elem
        return _call_hint(value)

    def _iter_hint(self, node: ast.AST) -> str:
        """Hint of the items a `for` loop over `node` yields."""
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and not node.args \
                and node.func.attr in ("values", "items"):
            return self._elem(self._value_hint(node.func.value))
        return self._elem(self._value_hint(node))

    def _bind_loop_target(self, target: ast.AST, hint: str, items: bool):
        if items and isinstance(target, ast.Tuple) and len(target.elts) == 2:
            self._bind(target.elts[1], hint)  # for key, value in d.items()
        elif not items:
            self._bind(target, hint)

    def visit_For(self, node: ast.For):
        self.visit(node.iter)
        is_items = isinstance(node.iter, ast.Call) and isinstance(node.iter.func, ast.Attribute) \
            and node.iter.func.attr == "items" and not node.iter.args
        self._bind_loop_target(node.target, self._iter_hint(node.iter), is_items)
        for stmt in node.body + node.orelse:
            self.visit(stmt)

    visit_AsyncFor = visit_For

    def visit_If(self, node: ast.If):
        self.visit(node.test)
        narrowed = self._isinstance_narrowing(node.test)
        saved = self.scopes[-1].get(narrowed[0]) if narrowed else None
        if narrowed:
            self.scopes[-1][narrowed[0]] = narrowed[1]
        for stmt in node.body:
            self.visit(stmt)
        if narrowed:
            if saved is None:
                self.scopes[-1].pop(narrowed[0], None)
            else:
                self.scopes[-1][narrowed[0]] = saved
        for stmt in node.orelse:
            self.visit(stmt)

    @staticmethod
    def _isinstance_narrowing(test: ast.AST):
        """('x', 'class:Cls') for `if isinstance(x, Cls)` (one class, no tuple)."""
        if isinstance(test, ast.Call) and isinstance(test.func, ast.Name) and test.func.id == "isinstance" \
                and len(test.args) == 2 and isinstance(test.args[0], ast.Name):
            cls = _type_name(test.args[1]) if isinstance(test.args[1], (ast.Name, ast.Attribute)) else ""
            if cls:
                return test.args[0].id, f"class:{cls}"
        return None

    def _bind(self, target: ast.AST, hint: str):
        if not hint:
            return
        if isinstance(target, ast.Name):
            self.scopes[-1][target.id] = hint
        elif isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name) \
                and target.value.id == "self" and self.classes:
            self.scan.attr_hints[f"{self.classes[-1]}.{target.attr}"] = hint

    def visit_Assign(self, node: ast.Assign):
        self.generic_visit(node)
        hint = self._value_hint(node.value)
        for t in node.targets:
            self._bind(t, hint)

    def visit_AnnAssign(self, node: ast.AnnAssign):
        self.generic_visit(node)
        t = _type_name(node.annotation)
        self._bind(node.target, f"class:{t}" if t else (self._value_hint(node.value) if node.value else ""))

    def visit_withitem(self, node: ast.withitem):
        self.generic_visit(node)
        if node.optional_vars is not None:  # `with Cls(...) as x`: assume __enter__ returns self
            self._bind(node.optional_vars, self._value_hint(node.context_expr))

    # --- calls, urls --------------------------------------------------------
    def visit_Call(self, node: ast.Call):
        f = node.func
        if isinstance(f, ast.Attribute) and f.attr == "register_blueprint" and node.args:
            prefix = None
            for kw in node.keywords:
                if kw.arg == "url_prefix":
                    prefix = _str_value(kw.value)
            child = _dotted(node.args[0])
            if child:
                self.scan.registrations.append((_dotted(f.value), child, prefix))
        if isinstance(f, ast.Name):
            self.scan.calls.append(CallSite(f.id, self.scan.file, node.lineno, self._enclosing()))
        elif isinstance(f, ast.Attribute):
            try:
                receiver = ast.unparse(f.value)[:RECEIVER_MAX_CHARS]
            except Exception:
                receiver = "?"
            self.scan.calls.append(CallSite(f.attr, self.scan.file, node.lineno, self._enclosing(), receiver,
                                            receiver_hint=self._expr_hint(f.value)))
        self.generic_visit(node)

    def visit_Constant(self, node: ast.Constant):
        if isinstance(node.value, str) and node.value.startswith(URL_PREFIXES):
            self.scan.urls.append(UrlRef(node.value.split("?")[0], self.scan.file, node.lineno))

    def visit_JoinedStr(self, node: ast.JoinedStr):
        value = _str_value(node)
        if value and value.startswith(URL_PREFIXES):
            self.scan.urls.append(UrlRef(value.split("?")[0], self.scan.file, node.lineno))
        # do not descend: the constant parts would be recorded twice

    # --- flask routes -------------------------------------------------------
    def _collect_routes(self, node):
        for dec in node.decorator_list:
            if not (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute)):
                continue
            if dec.func.attr not in ROUTE_DECORATORS or not dec.args:
                continue
            path = _str_value(dec.args[0])
            if path is None:
                continue
            bp = dec.func.value.id if isinstance(dec.func.value, ast.Name) else ""
            methods = ""
            for kw in dec.keywords:
                if kw.arg == "methods":
                    try:
                        methods = ",".join(ast.literal_eval(kw.value))
                    except Exception:
                        methods = ""
            if dec.func.attr != "route":
                methods = dec.func.attr.upper()
            full = (self.prefixes.get(bp, "") + path) if path.startswith("/") or not path else path
            self.scan.routes.append(RouteDef(full, node.name, self.scan.file, node.lineno, methods, bp, path))


def scan_python(rel_path: str, source: str) -> Optional[FileScan]:
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return None
    scan = FileScan(file=rel_path, module=module_name(rel_path))
    scan.blueprints = _blueprint_prefixes(tree)
    _Visitor(scan, scan.blueprints, rel_path.endswith("__init__.py")).visit(tree)
    return scan
