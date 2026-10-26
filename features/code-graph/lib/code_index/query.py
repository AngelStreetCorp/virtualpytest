"""Answer one code_refs question from a built CodeIndex, as compact text (fewer tokens than grep)."""
import fnmatch
import re
from collections import defaultdict
from typing import Dict, List, Optional, Tuple

from .constants import (
    DEFAULT_MAX_FILES, MENTION_MAX_LISTED, NARROW_MAX, FEATURE_PREFIX, FLASK_PARAM_RE, MAX_DEPTH, RES_ORDER, SIGNATURE_MAX_CHARS,
    TEST_PREFIXES, URL_PREFIXES, WILDCARD,
)
from .types import CallSite, CodeIndex, Definition, RouteDef, UrlRef


# --- helpers ----------------------------------------------------------------
def _is_test(path: str) -> bool:
    name = path.rsplit("/", 1)[-1]
    return path.startswith(TEST_PREFIXES) or "/tests/" in path or name.startswith("test_")


def _flags(path: str) -> str:
    out = []
    if _is_test(path):
        out.append("test")
    if path.startswith(FEATURE_PREFIX):
        out.append("feature")
    return f" ({','.join(out)})" if out else ""


def _rank(tag: str) -> int:
    return RES_ORDER.index(tag) if tag in RES_ORDER else len(RES_ORDER)


def _snake_tokens(name: str) -> List[str]:
    return [t for t in re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", name).lower().split("_") if t]


def _module_of(rel_file: str) -> str:
    parts = rel_file[:-3].split("/")
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _fmt_def(d: Definition) -> str:
    owner = f"{d.owner}." if d.owner else ""
    sig = d.signature if len(d.signature) <= SIGNATURE_MAX_CHARS else d.signature[:SIGNATURE_MAX_CHARS] + "…)"
    return f"  {d.file}:{d.line} {d.kind} {owner}{d.name}{sig}"


# --- what a grep would add: text-only mentions ------------------------------
def _text_mentions(index: CodeIndex, name: str) -> List[str]:
    """Grep hits for `name(` that are not calls of `name`: comments/docstrings/strings, longer names.

    Listed so an agent can see why a grep shows more hits than the callers, without re-grepping (found at build time)."""
    text_hits = [f"{f}:{ln}" for f, ln in index.text_hits.get(name, ())]
    longer = {t: set(fs) for t, fs in index.longer_names.get(name, {}).items()}
    callers = {c.file for c in index.calls.get(name, [])}
    if not text_hits and not longer:
        return []
    out = [f"text-only mentions (a grep for '{name}(' also hits these; they are not calls of {name}):"]
    only = [h for h in text_hits if h.rsplit(":", 1)[0] not in callers]
    if only:
        shown = ", ".join(only[:MENTION_MAX_LISTED]) + (" …" if len(only) > MENTION_MAX_LISTED else "")
        out.append(f"  in files with no call ({len(only)} lines): {shown}")
    if len(text_hits) > len(only):
        out.append(f"  + {len(text_hits) - len(only)} comment/docstring lines inside caller files")
    if longer:
        out.append("  other names ending in it: " + ", ".join(
            f"{n} ({len(fs)} files)" for n, fs in sorted(longer.items())))
    return out


def _narrow_hints(index: CodeIndex, defs: List[Definition]) -> str:
    """Several non-test defs share the name: the narrower queries, a route handler's URL first."""
    routes = {(r.file, r.handler): r for r in index.routes}
    hints = []
    for d in defs:
        r = routes.get((d.file, d.name)) if not d.owner else None
        if r:
            hints.append(f"{r.path} (route of {_module_of(d.file).rsplit('.', 1)[-1]}.{d.name})")
        elif d.owner:
            hints.append(f"{d.owner}.{d.name}")
        elif not d.nested:
            hints.append(f"{_module_of(d.file).rsplit('.', 1)[-1]}.{d.name}")
    hints = list(dict.fromkeys(hints))
    if len(hints) < 2:
        return ""
    more = f" … +{len(hints) - NARROW_MAX}" if len(hints) > NARROW_MAX else ""
    return "narrower queries: " + " | ".join(hints[:NARROW_MAX]) + more


# --- Class.method / module.func plausibility --------------------------------
def _receiver_fits_class(receiver: str, cls: str) -> bool:
    """`self.device.navigation_executor` / `nav_executor` / `NavigationExecutor` fit NavigationExecutor."""
    if not receiver:
        return False
    last = receiver.rsplit(".", 1)[-1].split("(")[0].split("[")[0]
    if last == cls:
        return True
    want, got = _snake_tokens(cls), _snake_tokens(last)
    if not got or len(got) < len(want):
        return False
    tail = got[-len(want):]
    return all(g.startswith(w) or w.startswith(g) for g, w in zip(tail, want))


def _lineage(index: CodeIndex, cls: str) -> set:
    """cls, its bases and the classes derived from it (by name): a call typed as any of them can reach cls's method."""
    bases = {}
    for name, ds in index.defs.items():
        for d in ds:
            if d.kind == "class":
                bases.setdefault(name, set()).update(d.bases)
    up, todo = set(), [cls]
    while todo:
        c = todo.pop()
        if c not in up:
            up.add(c)
            todo.extend(bases.get(c, ()))
    down, todo = set(), [cls]
    while todo:
        c = todo.pop()
        if c not in down:
            down.add(c)
            todo.extend(n for n, bs in bases.items() if c in bs)
    return up | down


def _filter_class(calls: List[CallSite], cls: str, defs: List[Definition],
                  lineage: Optional[set] = None) -> Tuple[List[CallSite], List[CallSite]]:
    lineage = lineage or {cls}
    owners = {d.owner for d in defs}
    unique_here = len(owners) == 1 and cls in owners
    kept, dropped = [], []
    for c in calls:
        owner = c.enclosing.split(".")[0]
        if c.receiver in ("self", "cls") and owner == cls:
            kept.append(c)
        elif c.receiver_type:  # the receiver's class is known: trust it over the name
            (kept if c.receiver_type in lineage else dropped).append(c)
        elif unique_here or _receiver_fits_class(c.receiver, cls):
            kept.append(c)
        else:
            dropped.append(c)
    return kept, dropped


def _same_module(imported: str, full: str) -> bool:
    """'routes.x' (path-relative import) is 'backend_server.src.routes.x'."""
    return bool(imported) and (imported == full or full.endswith("." + imported))


def _filter_module(index: CodeIndex, calls: List[CallSite], module: str, defs: List[Definition]):
    """Calls that reach `module`'s function: in its file, imported from it, or via `module.func()`."""
    files = {d.file for d in defs}
    leaf = module.rsplit(".", 1)[-1]
    kept, dropped = [], []
    for c in calls:
        imports = index.imported_names.get(c.file, {})
        if not c.receiver:
            ok = c.file in files or _same_module(imports.get(c.name, ""), f"{module}.{c.name}")
        else:
            ok = _same_module(imports.get(c.receiver, ""), module) or c.receiver.rsplit(".", 1)[-1] == leaf
        (kept if ok else dropped).append(c)
    return kept, dropped


def _resolve_qualifier(index: CodeIndex, qual: str, name: str):
    """'X.y' -> ('class', X, defs) | ('module', module, defs) | None."""
    defs = index.defs.get(name, [])
    by_class = [d for d in defs if d.owner == qual]
    if by_class:
        return "class", qual, by_class
    for d in defs:
        mod = _module_of(d.file)
        if mod == qual or mod.endswith("." + qual):
            return "module", mod, [x for x in defs if _module_of(x.file) == mod]
    return None


# --- routes ↔ URL literals --------------------------------------------------
def _segments(path: str) -> List[str]:
    return FLASK_PARAM_RE.sub(WILDCARD, path).strip("/").split("/")


def _seg_match(a: str, b: str) -> bool:
    if a == b or a == WILDCARD or b == WILDCARD:
        return True
    if WILDCARD in a and fnmatch.fnmatchcase(b, a):
        return True
    return WILDCARD in b and fnmatch.fnmatchcase(a, b)


def _url_matches(route_path: str, url: str) -> bool:
    r = _segments(route_path)
    candidates = [_segments(url)]
    if url.endswith("/") and len(url) > 1:
        candidates.append(candidates[0] + [WILDCARD])  # '/server/x/' + id
    return any(len(u) == len(r) and all(_seg_match(x, y) for x, y in zip(r, u)) for u in candidates)


def _route_links(index: CodeIndex, routes: List[RouteDef], include_tests: bool, max_files: int) -> List[str]:
    lines = []
    for r in routes:
        refs = [u for u in index.urls if u.file != r.file and _url_matches(r.path, u.path)
                and (include_tests or not _is_test(u.file))]
        methods = f" [{r.methods}]" if r.methods else ""
        lines.append(f"route {r.path}{methods} -> {r.file}:{r.line} {r.handler}  <- {len(refs)} refs in "
                     f"{len({u.file for u in refs})} files")
        lines.extend(_fmt_url_refs(refs, max_files))
    return lines


def _fmt_url_refs(refs: List[UrlRef], max_files: int) -> List[str]:
    by_file: Dict[str, List[UrlRef]] = defaultdict(list)
    for u in refs:
        by_file[u.file].append(u)
    out = []
    for i, f in enumerate(sorted(by_file, key=lambda p: (not p.startswith("frontend/"), p))):
        if i >= max_files:
            out.append(f"  … {len(by_file) - max_files} more files (raise max_files)")
            break
        lits = sorted({u.path for u in by_file[f]})
        out.append(f"  {f}{_flags(f)}: L{','.join(str(u.line) for u in by_file[f])}  {' '.join(lits)}")
    return out


# --- callers ----------------------------------------------------------------
def _group_by_file(calls: List[CallSite]) -> Dict[str, List[CallSite]]:
    by_file: Dict[str, List[CallSite]] = defaultdict(list)
    for c in calls:
        by_file[c.file].append(c)
    return by_file


def _fmt_calls(calls: List[CallSite]) -> str:
    """'L12,L15 fn_a; L40 Cls.m via self.x' — same enclosing+receiver merged."""
    merged: Dict[Tuple[str, str], List[int]] = defaultdict(list)
    for c in sorted(calls, key=lambda c: c.line):
        merged[(c.enclosing, c.receiver)].append(c.line)
    parts = []
    for (enc, recv), lines in merged.items():
        via = f" via {recv}" if recv else ""
        parts.append(f"L{',L'.join(map(str, lines))} {enc}{via}")
    return "; ".join(parts)


def _fmt_callers(calls: List[CallSite], max_files: int) -> List[str]:
    by_file = _group_by_file(calls)
    best = {f: min(_rank(c.resolution) for c in cs) for f, cs in by_file.items()}
    order = sorted(by_file, key=lambda f: (best[f], f))
    out = []
    for i, f in enumerate(order):
        if i >= max_files:
            out.append(f"  … {len(order) - max_files} more files (raise max_files)")
            break
        tags = sorted({c.resolution for c in by_file[f]}, key=_rank)
        out.append(f"  {f} [{','.join(tags)}]{_flags(f)}: {_fmt_calls(by_file[f])}")
    return out


def _tag_summary(calls: List[CallSite]) -> str:
    counts: Dict[str, int] = defaultdict(int)
    for c in calls:
        counts[c.resolution] += 1
    return ", ".join(f"{t} {n}" for t, n in sorted(counts.items(), key=lambda kv: _rank(kv[0])))


def _callers_of(index: CodeIndex, name: str, qual: Optional[str], include_tests: bool):
    """(kept calls, dropped calls, note) for a bare name or 'Qualifier.name'."""
    calls = [c for c in index.calls.get(name, []) if include_tests or not _is_test(c.file)]
    if not qual:
        return calls, [], ""
    resolved = _resolve_qualifier(index, qual, name)
    if not resolved:
        return calls, [], f"note: '{qual}' is neither a class nor a module defining {name}; showing every call of {name}"
    kind, target, defs = resolved
    if kind == "class":
        kept, dropped = _filter_class(calls, target, index.defs.get(name, []), _lineage(index, target))
        why = (f"kept calls whose receiver is a {target} (its type from an assignment, annotation, return type or "
               f"fixture; else self in {target} or a receiver named like it)")
    else:
        kept, dropped = _filter_module(index, calls, target, defs)
        why = f"kept calls in {target}, imported from it, or via its module name"
    return kept, dropped, why


def _dropped_note(dropped: List[CallSite]) -> str:
    if not dropped:
        return ""
    recv: Dict[str, int] = defaultdict(int)
    for c in dropped:
        recv[c.receiver or "<bare>"] += 1
    top = ", ".join(f"{r}×{n}" for r, n in sorted(recv.items(), key=lambda kv: -kv[1])[:5])
    return (f"dropped {len(dropped)} calls in {len({c.file for c in dropped})} files with other receivers "
            f"({top}); query the bare name to see them")


# --- depth 2 ----------------------------------------------------------------
def _callers_of_def(index: CodeIndex, file: str, enclosing: str) -> List[CallSite]:
    """Callers of the function a call sits in: a method by class, a nested def in its own file,
    a module function by import."""
    owner, _, fn = enclosing.rpartition(".")
    calls = index.calls.get(fn, [])
    here = [d for d in index.defs.get(fn, []) if d.file == file]
    if owner and any(d.owner == owner for d in here):
        return _filter_class(calls, owner, index.defs.get(fn, []), _lineage(index, owner))[0]
    if any(d.kind == "function" and not d.nested for d in here):
        return _filter_module(index, calls, _module_of(file), here)[0]
    if any(d.nested for d in here):
        return [u for u in calls if u.file == file]
    return calls
def _depth2(index: CodeIndex, calls: List[CallSite], include_tests: bool, max_files: int) -> List[str]:
    """Grouped by the level-2 file (the answer's shape): `path <- fn_a L3,L9; fn_b L40`."""
    handlers = {(r.file, r.handler): r for r in index.routes}
    seen, routes, lonely = set(), [], []
    by_file: Dict[str, Dict[str, List[int]]] = defaultdict(lambda: defaultdict(list))
    for c in sorted(calls, key=lambda c: (c.file, c.line)):
        if c.enclosing == "<module>" or (c.file, c.enclosing) in seen:
            continue
        seen.add((c.file, c.enclosing))
        if (c.file, c.enclosing.rpartition(".")[2]) in handlers:
            routes.append(c.enclosing)
            continue
        up = [u for u in _callers_of_def(index, c.file, c.enclosing)
              if (include_tests or not _is_test(u.file)) and not (u.file == c.file and u.enclosing == c.enclosing)]
        if not up:
            lonely.append(c.enclosing)
        for u in up:
            by_file[u.file][c.enclosing].append(u.line)
    out = [f"depth 2: {len(by_file)} files call the {len(seen)} calling functions"]
    for i, f in enumerate(sorted(by_file)):
        if i >= max_files:
            out.append(f"  … {len(by_file) - max_files} more files (raise max_files)")
            break
        fns = "; ".join(f"{fn} L{',L'.join(map(str, sorted(set(ls))))}" for fn, ls in by_file[f].items())
        out.append(f"  {f}{_flags(f)} <- {fns}")
    if routes:
        out.append(f"  route handlers, reached over HTTP (query their URL): {len(routes)}: {', '.join(sorted(set(routes)))}")
    if lonely:
        out.append(f"  no repo callers: {len(lonely)}: {', '.join(sorted(set(lonely)))}")
    return out


# --- entry point ------------------------------------------------------------
def code_refs(index: CodeIndex, name: str, depth: int = 1, include_tests: bool = True,
              max_files: int = DEFAULT_MAX_FILES) -> str:
    name = (name or "").strip()
    depth = max(1, min(int(depth or 1), MAX_DEPTH))
    max_files = max(1, int(max_files or DEFAULT_MAX_FILES))
    version = index.git_head[:9] if re.fullmatch(r"[0-9a-f]{40}", index.git_head) else index.git_head
    head = f"code_refs {name} | index {index.files_scanned} files @{version or 'no-version'}"
    if not name:
        return head + "\nerror: name is required"

    # URL: routes that serve it + every literal that hits it
    if name.startswith(URL_PREFIXES):
        routes = [r for r in index.routes if _url_matches(r.path, name)]
        refs = [u for u in index.urls if _url_matches(name, u.path) and (include_tests or not _is_test(u.file))]
        lines = [head, f"routes ({len(routes)}):"]
        lines += [f"  {r.path} [{r.methods or 'GET'}] -> {r.file}:{r.line} {r.handler}" for r in routes]
        lines.append(f"url refs: {len(refs)} in {len({u.file for u in refs})} files")
        lines += _fmt_url_refs(refs, max_files)
        return "\n".join(lines)

    # Module: who imports it
    if name in index.module_files:
        files = [f for f in index.importers.get(name, []) if include_tests or not _is_test(f)]
        lines = [head, f"module {name} -> {index.module_files[name]}", f"importers ({len(files)}):"]
        for i, f in enumerate(files):
            if i >= max_files:
                lines.append(f"  … {len(files) - max_files} more files (raise max_files)")
                break
            lines.append(f"  {f}{_flags(f)}")
        return "\n".join(lines)

    qual, _, base = name.rpartition(".")
    defs = index.defs.get(base, [])
    if qual:
        resolved = _resolve_qualifier(index, qual, base)
        if resolved:
            defs = resolved[2]
    if not defs and base not in index.calls:
        return head + f"\nno definition or call of '{base}' in the repo (TypeScript symbols: use grep)"

    real_defs = [d for d in defs if not _is_test(d.file)]
    fakes = len(defs) - len(real_defs)
    lines = [head, f"defs ({len(real_defs)}{f', +{fakes} in tests' if fakes else ''}):"] + [_fmt_def(d) for d in real_defs]
    if not qual:
        hint = _narrow_hints(index, real_defs)
        if hint:
            lines.append(hint)
    calls, dropped, why = _callers_of(index, base, qual or None, include_tests)
    if why:
        lines.append(why)
    lines.append(f"callers: {len({c.file for c in calls})} files, {len(calls)} calls [{_tag_summary(calls)}]")
    lines += _fmt_callers(calls, max_files)
    if not include_tests:
        hidden = sorted({c.file for c in _callers_of(index, base, qual or None, True)[0]} - {c.file for c in calls})
        if hidden:
            lines.append(f"tests hidden (include_tests=false): {len(hidden)} files with callers: {', '.join(hidden)}")
    note = _dropped_note(dropped)
    if note:
        lines.append(note)
    if not qual:
        lines += _text_mentions(index, base)

    def_files = {d.file for d in defs}
    routes = [r for r in index.routes if r.handler == base and r.file in def_files]
    if routes:
        lines += _route_links(index, routes, include_tests, max_files)
    if depth >= 2:
        lines += _depth2(index, calls, include_tests, max_files)
    return "\n".join(lines)
