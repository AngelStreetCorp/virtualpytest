"""BUG-0672: a queued run of a file script named without ".py" must not be treated as a DB campaign."""

import ast
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_PATH = _ROOT / 'backend_host/src/services/deployment_scheduler.py'
_SOURCE = _PATH.read_text()


def _load_helper():
    tree = ast.parse(_SOURCE)
    node = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == '_is_file_script')
    namespace = {'Path': Path, '__file__': str(_PATH)}
    exec(compile(ast.Module([node], []), str(_PATH), 'exec'), namespace)
    return namespace['_is_file_script']


def test_file_script_without_py_suffix_is_recognised():
    is_file = _load_helper()
    assert is_file('vpt/smoke_ui')
    assert is_file('vpt/smoke_ui.py')
    assert is_file('test_scripts/vpt/smoke_ui')


def test_unknown_and_escaping_names_are_not_file_scripts():
    is_file = _load_helper()
    assert not is_file('no_such_campaign')
    assert not is_file('../backend_host/src/services/deployment_scheduler')


def test_scheduler_falls_back_to_file_script_before_raising():
    assert source_index('_is_file_script(resolved_script_name)') < source_index('no DB campaign found')


def source_index(text):
    return _SOURCE.index(text, _SOURCE.index('db_campaign = None'))
