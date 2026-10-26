"""Code reference tool for coding agents: who calls / imports / hits X, from an in-memory stdlib-ast index.

The index is built in the background when the server starts and rebuilt when the checkout's version moves
(features/code-graph/lib/code_index). See docs/agent/Graphify.md.
"""
import importlib
from typing import Any, Dict

_query = importlib.import_module('features.code-graph.lib.code_index.query')
_store = importlib.import_module('features.code-graph.lib.code_index.store')


def _text(text: str, is_error: bool = False) -> Dict[str, Any]:
    return {"content": [{"type": "text", "text": text}], "isError": is_error}


class CodeRefsTools:
    """Who calls, imports or hits a function, method, module or /server/ /host/ URL in this repo"""

    def __init__(self):
        _store.warm()  # build in the background at server start: the first agent call does not wait

    def code_refs(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Who calls a Python function or method, who imports a module, which frontend/Python code hits a Flask route: the complete answer in one call. Use it first instead of grep.

        It is built from the AST of every .py file, so the caller list is complete and comments, strings and
        def lines are already excluded: do not grep to confirm it. Callers come grouped by file with line,
        enclosing function, receiver text and a certainty tag (local, self, import-resolved, type-resolved,
        name-match-unique, name-match-ambiguous). type-resolved = the receiver's class is known from an assignment
        (x = Cls(...)), an annotation, a function's return type or a pytest fixture; 'Class.method' keeps exactly those
        calls (subclasses included) and drops calls typed as another class. Injected calls such as deps.call_host() or env.call_host() are real callers of the
        injected function; they are tagged ambiguous only because the receiver's type is unknown. A grep for 'X('
        shows more hits than the callers: the output lists them under "text-only mentions" (comments, docstrings,
        strings, longer names like fake_X), so there is nothing left to re-check. When several functions share the
        name, it prints the narrower queries (Class.method, module.func, a route's URL) - use one of those.
        Frontend .ts/.tsx/.js URL literals are indexed too: for a route, query its URL or module.handler and the
        answer lists every frontend and Python file that hits it; no frontend grep is needed. A route handler also
        lists those URL refs. depth=2 lists, per file, the functions it calls that call X (what breaks two levels
        up). Keep tests included (the default); include_tests=false prints which test files it hid. Only
        TypeScript function names are not indexed (grep those).

        Example: code_refs(name='call_host', depth=2)

        Args:
            params: {
                'name': str (REQUIRED - function or method name, 'Class.method', 'module_leaf.func', a dotted module like 'shared.src.lib.utils.build_url_utils', or a URL like '/server/control/navigate')
                'depth': int (OPTIONAL - 2 also lists the callers of each calling function; default 1)
                'include_tests': bool (OPTIONAL - false drops test files; default true, tests are flagged)
                'max_files': int (OPTIONAL - cap on files listed per section; default 60)
            }

        Returns:
            Compact text: definitions, callers by file, route links, optional depth-2 callers
        """
        name = (params.get('name') or '').strip()
        if not name:
            return _text("name is required", True)
        text = _query.code_refs(
            _store.get_index(), name,
            depth=params.get('depth') or 1,
            include_tests=params.get('include_tests', True) is not False,
            max_files=params.get('max_files') or 60,
        )
        return _text(text)
