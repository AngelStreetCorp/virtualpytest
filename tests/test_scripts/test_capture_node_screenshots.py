"""capture_node_screenshots.py: node selection, filename rule, and the capture/store step.

Pure: the AV controller, R2 upload and navigation_trees_db functions are
replaced by in-memory fakes.

Run: pytest tests/test_scripts/test_capture_node_screenshots.py -v
"""
import os
import sys
import types

import pytest

_test_dir = os.path.dirname(os.path.abspath(__file__))
_repo_root = os.path.normpath(os.path.join(_test_dir, "..", ".."))
sys.path.insert(0, _repo_root)

from test_scripts import capture_node_screenshots as cns  # noqa: E402

TREE = "tree-1"
TEAM = "team-1"


def _nodes():
    return [
        {"node_id": "entry-node", "label": "Entry", "node_type": "entry", "data": {}},
        {"node_id": "home", "label": "home", "node_type": "screen", "data": {"screenshot": "https://r2/old.jpg"}},
        {"node_id": "shorts", "label": "shorts", "node_type": "screen", "data": {}},
        {"node_id": "settings", "label": "Settings Menu", "node_type": "menu", "data": {}},
        {"node_id": "press-ok", "label": "press ok", "node_type": "action", "data": {}},
    ]


def test_sanitize_filename_matches_editor_rule():
    assert cns._sanitize_filename("Settings Menu") == "Settings_Menu"
    assert cns._sanitize_filename("live / fullscreen!") == "live__fullscreen"


def test_select_all_screen_and_menu_nodes_by_default():
    selected, skipped = cns._select_nodes(_nodes(), "", overwrite=True)
    assert [n["node_id"] for n in selected] == ["home", "shorts", "settings"]
    assert ("Entry", "type 'entry' has no screen") in skipped
    assert ("press ok", "type 'action' has no screen") in skipped


def test_overwrite_false_skips_nodes_with_a_screenshot():
    selected, skipped = cns._select_nodes(_nodes(), "", overwrite=False)
    assert [n["node_id"] for n in selected] == ["shorts", "settings"]
    assert ("home", "already has a screenshot (overwrite=false)") in skipped


def test_explicit_nodes_accept_labels_or_ids_and_report_unknown():
    selected, skipped = cns._select_nodes(_nodes(), "Settings Menu, press-ok, nope", overwrite=True)
    # explicit selection bypasses the type filter (action node captured on request)
    assert [n["node_id"] for n in selected] == ["settings", "press-ok"]
    assert ("nope", "not found in tree") in skipped


class FakeAV:
    def __init__(self, path="/tmp/shot.jpg"):
        self.path = path
        self.calls = []

    def save_screenshot(self, filename):
        self.calls.append(filename)
        return self.path


class FakeDevice:
    def __init__(self, av):
        self.av = av

    def _get_controller(self, name):
        return self.av if name == "av" else None


class FakeContext:
    team_id = TEAM


@pytest.fixture
def fakes(monkeypatch):
    store = {"saved": [], "uploads": []}

    fake_cf = types.ModuleType("shared.src.lib.utils.cloudflare_utils")

    def upload_navigation_screenshot(local_path, userinterface_name, screenshot_name):
        store["uploads"].append((local_path, userinterface_name, screenshot_name))
        return {"success": True, "url": f"https://r2.example/navigation/{userinterface_name}/{screenshot_name}"}

    fake_cf.upload_navigation_screenshot = upload_navigation_screenshot

    fake_db = types.ModuleType("shared.src.lib.database.navigation_trees_db")

    def get_node_by_id(tree_id, node_id, team_id):
        return {"success": True, "node": {"node_id": node_id, "data": {"type": "screen", "keep": 1}}}

    def save_node(tree_id, node_data, team_id):
        store["saved"].append((tree_id, team_id, node_data))
        return {"success": True}

    fake_db.get_node_by_id = get_node_by_id
    fake_db.save_node = save_node

    monkeypatch.setitem(sys.modules, "shared.src.lib.utils.cloudflare_utils", fake_cf)
    monkeypatch.setitem(sys.modules, "shared.src.lib.database.navigation_trees_db", fake_db)
    # cv2 / ImageHelpers are best-effort; make the import fail so the fingerprint path is skipped.
    monkeypatch.setitem(sys.modules, "cv2", None)
    return store


def test_capture_and_store_uploads_and_patches_node_data(fakes):
    av = FakeAV()
    node = {"node_id": "settings", "label": "Settings Menu", "node_type": "menu", "data": {}}

    url = cns._capture_and_store(FakeDevice(av), FakeContext(), TREE, node, "youtube-web")

    assert av.calls == ["Settings_Menu"]
    assert fakes["uploads"] == [("/tmp/shot.jpg", "youtube-web", "Settings_Menu.jpg")]
    assert url == "https://r2.example/navigation/youtube-web/Settings_Menu.jpg"
    tree_id, team_id, node_data = fakes["saved"][0]
    assert (tree_id, team_id, node_data["node_id"]) == (TREE, TEAM, "settings")
    assert node_data["data"]["screenshot"] == url
    assert node_data["data"]["keep"] == 1  # existing data preserved
    assert node_data["data"]["screenshot_timestamp"] > 0
    assert "fingerprint" not in node_data["data"]


def test_capture_and_store_fails_loudly_when_capture_returns_nothing(fakes):
    node = {"node_id": "shorts", "label": "shorts", "node_type": "screen", "data": {}}
    with pytest.raises(RuntimeError, match="no screenshot"):
        cns._capture_and_store(FakeDevice(FakeAV(path=None)), FakeContext(), TREE, node, "youtube-web")
    assert fakes["saved"] == []
