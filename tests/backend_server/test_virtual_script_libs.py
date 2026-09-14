"""Unit tests for virtual-script shared libraries (`_script_libs`).

Covers:
  - extract_script_libs(source): present / absent / multiple / malformed.
  - resolve_virtual_script_libs(root_source, fetch): recursion, dedupe, cycles.

Pure functions only — no DB, no device, no HTTP. Repo root is 2 levels up from
tests/backend_server/ (same bootstrap as test_script_utils.py).
"""
import os
import sys

_test_dir = os.path.dirname(os.path.abspath(__file__))
_repo_root = os.path.normpath(os.path.join(_test_dir, "..", ".."))
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)


# --- extract_script_libs -----------------------------------------------------

def _extract(source):
    from shared.src.lib.utils.script_target_rules_utils import extract_script_libs
    return extract_script_libs(source)


def test_extract_script_libs_absent():
    assert _extract("x = 1\n") == []
    assert _extract("") == []
    assert _extract("_script_description = 'hi'\n") == []


def test_extract_script_libs_present_single():
    assert _extract('_script_libs = ["helpers"]\n') == ["helpers"]


def test_extract_script_libs_multiple():
    src = '_script_libs = ["a", "b", "c"]\n'
    assert _extract(src) == ["a", "b", "c"]


def test_extract_script_libs_tuple_and_main_attr():
    assert _extract('_script_libs = ("a", "b")\n') == ["a", "b"]
    assert _extract('main._script_libs = ["x"]\n') == ["x"]


def test_extract_script_libs_dedupe_and_trim():
    assert _extract('_script_libs = ["a", " a ", "b", "a"]\n') == ["a", "b"]


def test_extract_script_libs_malformed_returns_empty():
    # Non-list value, non-string entries, and unparseable source all -> []
    assert _extract('_script_libs = "a"\n') == []
    assert _extract('_script_libs = [1, 2, 3]\n') == []
    assert _extract("def (:\n") == []  # syntax error


# --- resolve_virtual_script_libs ---------------------------------------------

def _resolve(root_source, sources):
    """sources: {name: source} fake DB; fetch returns None for unknown names."""
    from shared.src.lib.executors.script_executor import resolve_virtual_script_libs
    return resolve_virtual_script_libs(root_source, lambda name: sources.get(name))


def test_resolve_flat():
    sources = {"a": "print('a')\n", "b": "print('b')\n"}
    result = _resolve('_script_libs = ["a", "b"]\n', sources)
    assert result == {"a": "print('a')\n", "b": "print('b')\n"}


def test_resolve_recursive():
    sources = {
        "a": '_script_libs = ["b"]\nprint("a")\n',
        "b": '_script_libs = ["c"]\nprint("b")\n',
        "c": 'print("c")\n',
    }
    result = _resolve('_script_libs = ["a"]\n', sources)
    assert set(result.keys()) == {"a", "b", "c"}


def test_resolve_dedupe():
    # Both a and b depend on shared -> fetched once.
    sources = {
        "a": '_script_libs = ["shared"]\n',
        "b": '_script_libs = ["shared"]\n',
        "shared": "SHARED = 1\n",
    }
    result = _resolve('_script_libs = ["a", "b"]\n', sources)
    assert list(result.keys()).count("shared") == 1
    assert set(result.keys()) == {"a", "b", "shared"}


def test_resolve_cycle_safe():
    # a -> b -> a  must terminate.
    sources = {
        "a": '_script_libs = ["b"]\n',
        "b": '_script_libs = ["a"]\n',
    }
    result = _resolve('_script_libs = ["a"]\n', sources)
    assert set(result.keys()) == {"a", "b"}


def test_resolve_missing_lib_skipped():
    sources = {"a": "print('a')\n"}
    result = _resolve('_script_libs = ["a", "does_not_exist"]\n', sources)
    assert result == {"a": "print('a')\n"}


def test_resolve_no_libs():
    assert _resolve("x = 1\n", {}) == {}
