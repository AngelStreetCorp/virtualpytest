"""fold_temp_trees.py: temporary acceptance-tree samples filed under stb-testop (TASK-27, 2026-10-04).

Run: pytest tests/backend_server/test_ai_dataset_fold_temp_trees.py -v
"""
import importlib.util
import os
import sys

import pytest

_REPO_ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
sys.path.insert(0, _REPO_ROOT)

from shared.src.lib.ai.screen_groups import ScreenGroups  # noqa: E402

pytestmark = pytest.mark.unit


def _load():
    path = os.path.join(_REPO_ROOT, "features", "ai-dataset", "scripts", "fold_temp_trees.py")
    spec = importlib.util.spec_from_file_location("fold_temp_trees_under_test", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


fold = _load()
STB = ScreenGroups({
    "s-home": {"node_id": "s-home", "label": "home", "members": [
        {"node_id": "s-home", "label": "home", "focus": None},
        {"node_id": "s-home-apps", "label": "home_apps", "focus": "apps"}]},
    "s-live": {"node_id": "s-live", "label": "live", "members": [{"node_id": "s-live", "label": "live", "focus": None}]},
})
ACC = "acceptance-stb4-tv-20261003-1758-stb"


def _row(rid, truth, family="screen-id", ui=ACC, **kw):
    return {"id": rid, "family": family, "userinterface": ui, "ground_truth": truth, "label_source": "run",
            "eval_version": None, "triage": None, **kw}


def test_aliases_name_the_acceptance_copies():
    assert fold.canonical_for(ACC, "stb-testop") == "stb-testop"
    assert fold.canonical_for("qa-anchor-check-stb", "stb-testop") == "stb-testop"
    assert fold.canonical_for("stb-testop", "stb-testop") is None and fold.canonical_for("youtube-web", "stb-testop") is None


def test_a_label_is_repointed_by_node_name_then_group_name():
    by_node = {"node_id": "a-home", "label": "home", "node": "a-home-apps", "node_label": "home_apps", "focus": "apps"}
    assert fold.remap_label(by_node, STB) == {"node_id": "s-home", "label": "home", "node": "s-home-apps",
                                              "node_label": "home_apps", "focus": "apps"}
    by_group = {"node_id": "a-live", "label": "live"}
    assert fold.remap_label(by_group, STB)["node_id"] == "s-live"
    assert fold.remap_label({"node_id": None, "label": "popup"}, STB) == {"node_id": None, "label": "popup"}
    assert fold.remap_label({"node_id": "a-x", "label": "netflix_profile"}, STB) is None
    # a checked synonym: the copies call full-screen live TV "live_channel"
    assert fold.remap_label({"node_id": "a-lc", "label": "live_channel"}, STB)["node_id"] == "s-live"


def test_fold_plans_and_writes_only_temporary_tree_rows():
    rows = [
        _row("a", {"node_id": "a-live", "label": "live"},
             triage={"status": "teacher_only", "teacher_label": {"node_id": "a-home", "label": "home"}}),
        _row("b", {"node_id": "a-x", "label": "netflix_profile"}),          # no match in stb-testop
        _row("c", {"node_id": None, "label": "popup"}),                      # off-tree: app only
        _row("d", None, family="focus"),                                     # focus row: app only
        _row("e", {"node_id": "s-live", "label": "live"}, ui="stb-testop"),      # canonical: untouched
        _row("f", {"node_id": "a-live", "label": "live"}, eval_version="eval-v0-ai"),
    ]
    writes = {}
    report = fold.fold("team", rows, lambda ui: STB if ui == "stb-testop" else None,
                       lambda row, fields: writes.setdefault(row["id"], fields) is not None, "stb-testop")
    assert report["counts"] == {"change": 3, "written": 3, "unmapped": 1, "frozen": 1}
    assert report["unmapped"] == {"netflix_profile": 1}
    assert writes["a"]["userinterface"] == "stb-testop" and writes["a"]["ground_truth"]["node_id"] == "s-live"
    assert writes["a"]["triage"]["teacher_label"]["node_id"] == "s-home"
    assert writes["c"] == {"userinterface": "stb-testop"} and writes["d"] == {"userinterface": "stb-testop"}
    assert "e" not in writes and "b" not in writes and "f" not in writes


def test_dry_run_writes_nothing_and_a_second_run_changes_nothing():
    row = _row("a", {"node_id": "a-live", "label": "live"})
    assert fold.fold("team", [row], lambda ui: STB, None, "stb-testop")["counts"] == {"change": 1}
    done = {**row, "userinterface": "stb-testop", "ground_truth": {"node_id": "s-live", "label": "live", "node": "s-live",
                                                                "node_label": "live", "focus": None}}
    assert fold.fold("team", [done], lambda ui: STB, None, "stb-testop")["counts"] == {}
