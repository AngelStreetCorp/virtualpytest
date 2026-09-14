"""Unit tests for disk-script -> virtual-script conversion.

Covers the rewrite rules in shared/src/lib/utils/script_conversion.py:
  - find_local_imports across all three `test_scripts.*` import forms
  - rewrite_source_for_virtual: import rewriting, _script_libs merge/insert,
    sys.path bootstrap handling, formatting preservation
  - plan_conversion: helper recursion, ordering, cycles, depth, collisions
  - the contract that actually matters: extract_script_libs() can read back
    whatever rewrite_source_for_virtual() writes

Pure functions only — no DB, no HTTP. Repo root is 2 levels up from tests/shared/.
"""
import ast
import os
import sys
import textwrap

import pytest

_test_dir = os.path.dirname(os.path.abspath(__file__))
_repo_root = os.path.normpath(os.path.join(_test_dir, "..", ".."))
if _repo_root not in sys.path:
    sys.path.insert(0, _repo_root)

from shared.src.lib.utils.script_conversion import (  # noqa: E402
    ERR_NAME_COLLISION,
    ERR_UNSUPPORTED_IMPORT,
    ConversionError,
    find_local_imports,
    plan_conversion,
    ref_to_name_and_folder,
    rewrite_source_for_virtual,
)
from shared.src.lib.utils.script_target_rules_utils import (  # noqa: E402
    extract_script_libs,
    extract_script_target_rules_from_source,
)


def _write(tmp_path, rel, source):
    path = tmp_path / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(source), encoding="utf-8")
    return path


# --- ref_to_name_and_folder --------------------------------------------------

def test_ref_splits_folder_from_basename():
    assert ref_to_name_and_folder("gw/superping") == ("superping", "gw")
    assert ref_to_name_and_folder("goto") == ("goto", "(Root)")
    assert ref_to_name_and_folder("a/b/c") == ("c", "a/b")


# --- find_local_imports ------------------------------------------------------

def test_finds_all_three_import_forms():
    source = """
        from test_scripts.gw.utils_a import x
        from test_scripts.gw import utils_b
        import test_scripts.gw.utils_c as c
        from shared.src.lib.executors.script_decorators import script
        import os
    """
    found = find_local_imports(textwrap.dedent(source))
    assert ("gw", "utils_a", "from_module") in found
    assert ("gw", "utils_b", "from_package") in found
    assert ("gw", "utils_c", "import") in found
    assert len(found) == 3


def test_finds_imports_nested_inside_a_function():
    source = """
        def run():
            from test_scripts.gw.utils_a import x
            return x
    """
    assert find_local_imports(textwrap.dedent(source)) == [("gw", "utils_a", "from_module")]


# --- rewrite_source_for_virtual ---------------------------------------------

def test_rewrites_from_module_import_and_keeps_formatting():
    source = (
        "from test_scripts.gw.utils_gw_network import (\n"
        "    get_default_interface,  # trailing comment\n"
        "    ping_via_interface,\n"
        ")\n"
        "\n"
        "VALUE = 1\n"
    )
    rewritten, warnings = rewrite_source_for_virtual(source, ["utils_gw_network"])
    assert "from utils_gw_network import (" in rewritten
    assert "test_scripts" not in rewritten
    # The parenthesized list, its comment and the blank line survive verbatim.
    assert "    get_default_interface,  # trailing comment\n" in rewritten
    assert "\nVALUE = 1\n" in rewritten
    assert warnings == []


def test_rewrites_from_package_import():
    rewritten, _ = rewrite_source_for_virtual(
        "from test_scripts.gw import utils_a, utils_b as b\n", [])
    assert "import utils_a" in rewritten
    assert "import utils_b as b" in rewritten


def test_rewrites_aliased_dotted_import():
    rewritten, _ = rewrite_source_for_virtual(
        "import test_scripts.gw.utils_a as helper\n", [])
    assert "import utils_a as helper" in rewritten


def test_refuses_dotted_import_without_alias():
    # The call sites use the dotted path; rewriting the import line alone would
    # produce a NameError at run time, so this must fail loudly.
    with pytest.raises(ConversionError) as excinfo:
        rewrite_source_for_virtual("import test_scripts.gw.utils_a\n", [])
    assert excinfo.value.code == ERR_UNSUPPORTED_IMPORT


# --- _script_libs round trip (the coupling that matters) ---------------------

def test_inserted_script_libs_is_readable_by_extract_script_libs():
    source = "import os\nfrom test_scripts.gw.utils_a import x\n\nVALUE = 1\n"
    rewritten, _ = rewrite_source_for_virtual(source, ["utils_a"])
    assert extract_script_libs(rewritten) == ["utils_a"]


def test_script_libs_merges_with_an_existing_declaration():
    source = '_script_libs = ["already"]\nfrom test_scripts.gw.utils_a import x\n'
    rewritten, _ = rewrite_source_for_virtual(source, ["utils_a"])
    assert extract_script_libs(rewritten) == ["already", "utils_a"]


def test_script_libs_merge_handles_the_main_attribute_form():
    source = 'def main():\n    pass\n\nmain._script_libs = ["already"]\n'
    rewritten, _ = rewrite_source_for_virtual(source, ["utils_a"])
    assert extract_script_libs(rewritten) == ["already", "utils_a"]


def test_no_script_libs_inserted_when_there_are_no_local_imports():
    source = "import os\n\nVALUE = 1\n"
    rewritten, _ = rewrite_source_for_virtual(source, [])
    assert "_script_libs" not in rewritten


def test_script_args_and_target_rules_survive_the_rewrite():
    source = (
        "from test_scripts.gw.utils_a import x\n"
        "_script_args = ['--target:str:google.com', '--count:int:5']\n"
        "_target_rules = {'target_type': 'host', 'host_os': 'all'}\n"
    )
    rewritten, _ = rewrite_source_for_virtual(source, ["utils_a"])
    assert "_script_args = ['--target:str:google.com', '--count:int:5']" in rewritten
    assert extract_script_target_rules_from_source(rewritten) == {
        'target_type': 'host', 'host_os': 'all',
    }


# --- sys.path bootstrap ------------------------------------------------------

def test_bootstrap_is_commented_out_when_nothing_reuses_it():
    source = (
        "import os, sys\n"
        "current_dir = os.path.dirname(os.path.abspath(__file__))\n"
        "project_root = os.path.dirname(os.path.dirname(current_dir))\n"
        "if project_root not in sys.path:\n"
        "    sys.path.insert(0, project_root)\n"
        "\nVALUE = 1\n"
    )
    rewritten, _ = rewrite_source_for_virtual(source, [])
    assert "# [virtual] project_root = " in rewritten
    assert "\nVALUE = 1\n" in rewritten


def test_project_root_used_later_is_rederived_from_cwd():
    # __file__ math is off by one from the test_scripts/ root, but the executor
    # always runs with cwd=<project root>, so the value is recoverable.
    source = (
        "import os, sys\n"
        "current_dir = os.path.dirname(os.path.abspath(__file__))\n"
        "project_root = os.path.dirname(os.path.dirname(current_dir))\n"
        "if project_root not in sys.path:\n"
        "    sys.path.insert(0, project_root)\n"
        "\nTMP = os.path.join(project_root, 'tmp')\n"
    )
    rewritten, _ = rewrite_source_for_virtual(source, [])
    assert "project_root = os.getcwd()" in rewritten
    assert "# [virtual] project_root = os.path.dirname" in rewritten
    # No live __file__ reference remains (the commented-out block still shows the
    # original text, so this has to be checked on the AST, not the raw string).
    tree = ast.parse(rewritten)
    assert not [n for n in ast.walk(tree) if isinstance(n, ast.Name) and n.id == "__file__"]
    # And it still runs: project_root resolves, TMP builds.
    namespace = {}
    exec(compile(rewritten, "<t>", "exec"), namespace)
    assert namespace["TMP"] == os.path.join(os.getcwd(), "tmp")


def test_current_dir_used_later_is_refused_not_rewritten():
    # "my own folder" has no virtual-script equivalent — a sibling data file
    # simply is not there. Must warn, never silently convert.
    source = (
        "import os, sys\n"
        "current_dir = os.path.dirname(os.path.abspath(__file__))\n"
        "project_root = os.path.dirname(os.path.dirname(current_dir))\n"
        "if project_root not in sys.path:\n"
        "    sys.path.insert(0, project_root)\n"
        "\nCONFIG = os.path.join(current_dir, 'profiles.json')\n"
    )
    rewritten, warnings = rewrite_source_for_virtual(source, [])
    assert "os.getcwd()" not in rewritten
    assert "current_dir = os.path.dirname" in rewritten
    assert "# [virtual]" not in rewritten


def test_bootstrap_strip_can_be_disabled():
    source = (
        "import os, sys\n"
        "project_root = os.path.dirname(os.path.abspath(__file__))\n"
        "if project_root not in sys.path:\n"
        "    sys.path.insert(0, project_root)\n"
    )
    rewritten, _ = rewrite_source_for_virtual(source, [], strip_syspath_bootstrap=False)
    assert "# [virtual]" not in rewritten


# --- plan_conversion ---------------------------------------------------------

def test_plan_converts_helper_first_and_names_by_basename(tmp_path):
    _write(tmp_path, "gw/entry.py", """
        from test_scripts.gw.utils_a import helper
        def main():
            return helper()
    """)
    _write(tmp_path, "gw/utils_a.py", "def helper():\n    return 1\n")
    _write(tmp_path, "gw/entry.md", "# Entry\n")

    plan = plan_conversion("gw/entry", str(tmp_path))

    assert plan.errors == []
    assert [u.vs_name for u in plan.units] == ["utils_a", "entry"]  # dependency order
    helper_unit, entry_unit = plan.units
    assert helper_unit.is_helper and helper_unit.folder == "gw"
    assert entry_unit.folder == "gw" and entry_unit.libs == ["utils_a"]
    assert entry_unit.doc == "# Entry\n"
    assert helper_unit.doc is None
    assert extract_script_libs(entry_unit.source) == ["utils_a"]


def test_plan_recurses_through_helper_of_helper(tmp_path):
    _write(tmp_path, "gw/entry.py", "from test_scripts.gw.utils_a import a\n")
    _write(tmp_path, "gw/utils_a.py", "from test_scripts.gw.utils_b import b\na = b\n")
    _write(tmp_path, "gw/utils_b.py", "b = 1\n")

    plan = plan_conversion("gw/entry", str(tmp_path))

    assert plan.errors == []
    assert [u.vs_name for u in plan.units] == ["utils_b", "utils_a", "entry"]


def test_plan_survives_an_import_cycle(tmp_path):
    _write(tmp_path, "gw/entry.py", "from test_scripts.gw.utils_a import a\n")
    _write(tmp_path, "gw/utils_a.py", "from test_scripts.gw.entry import e\na = 1\n")

    plan = plan_conversion("gw/entry", str(tmp_path))

    assert plan.errors == []
    assert {u.vs_name for u in plan.units} == {"entry", "utils_a"}


def test_plan_reports_a_missing_helper(tmp_path):
    _write(tmp_path, "gw/entry.py", "from test_scripts.gw.utils_missing import x\n")

    plan = plan_conversion("gw/entry", str(tmp_path))

    assert not plan.ok
    assert any(e["code"] == "not_found" for e in plan.errors)


def test_plan_refuses_a_basename_collision(tmp_path):
    # Two folders contributing the same basename would shadow each other, since
    # _script_libs resolves virtual scripts by bare name.
    _write(tmp_path, "gw/entry.py", """
        from test_scripts.gw.shared_utils import a
        from test_scripts.web.shared_utils import b
    """)
    _write(tmp_path, "gw/shared_utils.py", "a = 1\n")
    _write(tmp_path, "web/shared_utils.py", "b = 2\n")

    plan = plan_conversion("gw/entry", str(tmp_path))

    assert any(e["code"] == ERR_NAME_COLLISION for e in plan.errors)


def test_plan_respects_max_depth(tmp_path):
    _write(tmp_path, "gw/entry.py", "from test_scripts.gw.utils_a import a\n")
    _write(tmp_path, "gw/utils_a.py", "from test_scripts.gw.utils_b import b\na = 1\n")
    _write(tmp_path, "gw/utils_b.py", "b = 1\n")

    plan = plan_conversion("gw/entry", str(tmp_path), max_depth=1)

    assert any(e["code"] == "depth_exceeded" for e in plan.errors)


def test_plan_can_skip_helpers(tmp_path):
    _write(tmp_path, "gw/entry.py", "from test_scripts.gw.utils_a import a\n")
    _write(tmp_path, "gw/utils_a.py", "a = 1\n")

    plan = plan_conversion("gw/entry", str(tmp_path), include_helpers=False)

    assert [u.vs_name for u in plan.units] == ["entry"]
    # The import is still rewritten and declared — the lib just isn't converted here.
    assert plan.units[0].libs == ["utils_a"]


def test_plan_warns_when_a_path_is_built_from_file(tmp_path):
    _write(tmp_path, "gw/entry.py", """
        import os, sys
        current_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.dirname(os.path.dirname(current_dir))
        if project_root not in sys.path:
            sys.path.insert(0, project_root)

        CONFIG = os.path.join(current_dir, 'profiles.json')
    """)

    plan = plan_conversion("gw/entry", str(tmp_path))

    assert plan.errors == []
    assert any("current_dir" in w for w in plan.units[0].warnings)


def test_plan_rejects_a_ref_escaping_the_scripts_dir(tmp_path):
    plan = plan_conversion("../../etc/passwd", str(tmp_path))
    assert any(e["code"] == "not_found" for e in plan.errors)
