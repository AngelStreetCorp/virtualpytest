"""Tests for backend_server/src/lib/utils/script_utils.py — especially recursive campaign scripts."""
import pytest
import sys
import os

# Add backend_server/src to path for imports (repo root is 2 levels up from tests/backend_server/)
_test_dir = os.path.dirname(os.path.abspath(__file__))
_repo_root = os.path.normpath(os.path.join(_test_dir, "..", ".."))
_backend_src = os.path.join(_repo_root, "backend_server", "src")
# Repo root is needed too: script_utils imports `shared.src.lib...` at module load.
sys.path.insert(0, _repo_root)
sys.path.insert(0, _backend_src)


def test_normalize_script_reference():
    from lib.utils.script_utils import _normalize_script_reference as normalize

    # Basic normalization
    assert normalize("test_scripts/foo.py") == "foo.py"
    assert normalize("./foo.py") == "foo.py"
    assert normalize("/foo.py") == "foo.py"
    # Backslash to forward slash
    assert normalize("test_scripts\\foo.py") == "foo.py"
    # Strips test_scripts/ prefix
    assert normalize("test_scripts/bar/baz.py") == "bar/baz.py"
    # Empty/None
    assert normalize("") == ""
    assert normalize(None) == ""


def test_is_discoverable_script_reference():
    from lib.utils.script_utils import _is_discoverable_script_reference as is_discoverable

    # Discoverable
    assert is_discoverable("foo.py") is True
    assert is_discoverable("bar/baz.py") is True
    assert is_discoverable("test_scripts/foo.py") is True

    # NOT discoverable — executor
    assert is_discoverable("ai_testcase_executor.py") is False
    assert is_discoverable("ai_testcase_executor") is False

    # NOT discoverable — utility prefixes
    assert is_discoverable("utils_foo.py") is False
    assert is_discoverable("lib_bar.py") is False
    assert is_discoverable("_hidden.py") is False

    # NOT discoverable — pycache / dotfiles
    assert is_discoverable("__pycache__/foo.py") is False
    assert is_discoverable(".hidden.py") is False
