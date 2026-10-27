"""ai-dataset feature, TASK-27 step 4h: navigation-tree seed and coverage.

Pure: the scope rules, node filtering and tree walk (``lib/dataset_scope.py``), the coverage
maths (``lib/dataset_coverage.py``), the seed script against in-memory fakes (refusals,
idempotency, dedup classification, split, limit), and the ``/coverage`` route in a bare Flask
app (admin gate, team scope). No network, DB or bucket is touched.

Run: pytest tests/backend_server/test_ai_dataset_coverage.py -v
"""
import importlib
import os
import sys

import pytest
from flask import Flask, request

_test_dir = os.path.dirname(os.path.abspath(__file__))
_repo_root = os.path.normpath(os.path.join(_test_dir, "..", ".."))
sys.path.insert(0, _repo_root)

scope = importlib.import_module("features.ai-dataset.lib.dataset_scope")  # noqa: E402
cov = importlib.import_module("features.ai-dataset.lib.dataset_coverage")  # noqa: E402
seed = importlib.import_module("features.ai-dataset.scripts.seed_from_trees")  # noqa: E402
report_cli = importlib.import_module("features.ai-dataset.scripts.coverage_report")  # noqa: E402
routes = importlib.import_module("features.ai-dataset.backend_server.server_training_samples_routes")  # noqa: E402

pytestmark = pytest.mark.unit

TEAM = "11111111-1111-1111-1111-111111111111"
OTHER = "22222222-2222-2222-2222-222222222222"


# ---- scope ------------------------------------------------------------------------------------

@pytest.mark.parametrize("name", ["stb-testop", "youtube-web", "web_tv"])
def test_canonical_apps_are_in_scope(name):
    assert scope.scope_refusal(name) is None


@pytest.mark.parametrize("name,pattern", [
    ("stb3_autobuild", "*_autobuild*"), ("stb_tv_autobuild_copy", "*_autobuild*"),
    ("stb3_autobuild_depth2", "*_autobuild*"), ("stb3_depth3", "*_depth*"), ("stb3_sim", "*_sim"),
    ("stb_tv_settings", "*_settings*"), ("stb3_settings3", "*_settings*"), ("stb3_live", "*_live"),
    ("__smoke_test_ui_85a6db5c__", "__smoke*"), ("__ci_fixture_interface__", "__ci*"),
    ("web_tv_copy", "*_copy"),
])
def test_exclusion_patterns(name, pattern):
    assert scope.excluded_pattern(name) == pattern
    assert "exclusion pattern" in scope.scope_refusal(name)


def test_exclusion_wins_even_if_added_to_the_canonical_list(monkeypatch):
    monkeypatch.setitem(scope.CANONICAL_USERINTERFACES, "stb3_autobuild", "stb")
    assert "exclusion pattern" in scope.scope_refusal("stb3_autobuild")


@pytest.mark.parametrize("name", ["google_tv", "sauce-demo", "androidtv-testop", "youtube-android-mobile"])
def test_other_apps_are_not_in_the_canonical_list(name):
    assert "not in CANONICAL_USERINTERFACES" in scope.scope_refusal(name)


def test_platforms():
    assert scope.platform_of("stb-testop") == "stb" and scope.platform_of("web_tv") == "web"
    assert scope.platform_of("androidtv-testop", ["android_tv", "fire_tv_fireos"]) == "android_tv"
    assert scope.platform_of("phone_home", ["phone_agent"]) == "android_mobile"
    assert scope.device_model_for(["android_mobile", "android_tv"]) == "android_mobile"
    assert scope.device_model_for([]) is None


# ---- node filtering and tree walk -----------------------------------------------------------------

def node(node_id, label=None, node_type="screen", tree="t-root", shot=True, hidden=False, **kw):
    n = {"node_id": node_id, "label": label or node_id, "node_type": node_type, "tree_id": tree,
         "hidden_in_base": hidden, "screenshot": f"navigation/app/{label or node_id}.jpg" if shot else None}
    n.update(kw)
    return n


def test_visible_screen_filter():
    nodes = [node("home", is_system_protected=True), node("menu1", node_type="menu"),
             node("entry-node", "ENTRY", node_type="entry"), node("act", node_type="action"),
             node("variant_only", hidden=True), node("weird", "ENTRY"), node("", "blank")]
    assert [n["node_id"] for n in scope.visible_screens(nodes)] == ["home", "menu1"]


def test_node_type_falls_back_to_data_type():
    assert scope.is_visible_screen({"node_id": "x", "label": "x", "data": {"type": "screen"}})


def test_tree_walk_root_plus_nested_only():
    trees = [
        {"id": "late-root", "is_root_tree": True, "parent_tree_id": None, "created_at": "2026-02"},
        {"id": "root", "is_root_tree": True, "parent_tree_id": None, "created_at": "2026-01"},
        {"id": "child", "is_root_tree": False, "parent_tree_id": "root", "created_at": "2026-03"},
        {"id": "grandchild", "is_root_tree": False, "parent_tree_id": "child", "created_at": "2026-04"},
        {"id": "orphan", "is_root_tree": False, "parent_tree_id": "nowhere", "created_at": "2026-05"},
    ]
    assert scope.tree_ids_from_root(trees) == ["root", "child", "grandchild"]
    assert scope.tree_ids_from_root([t for t in trees if not t["is_root_tree"]]) == []


def test_screenshot_keys_resolved_then_label_fallback():
    n = node("n1", "home_movies&series", shot=False,
             screenshot="https://pub.example.r2.dev/navigation/web_player/home_moviesseries.jpg")
    resolve = lambda url: url.split(".dev/", 1)[1]  # noqa: E731
    assert scope.screenshot_keys(n, "web_tv", resolve) == [
        "navigation/web_player/home_moviesseries.jpg", "navigation/web_tv/home_moviesseries.jpg"]
    assert scope.screenshot_keys(node("n2", shot=False), "web_tv", resolve) == []
    assert scope.sanitize_label("Live TV guide") == "Live_TV_guide"


def test_app_screen_nodes_keeps_only_the_apps_trees():
    ui = {"id": "ui1", "name": "stb-testop"}
    trees = [{"id": "r", "userinterface_id": "ui1", "is_root_tree": True, "parent_tree_id": None},
             {"id": "c", "userinterface_id": "ui1", "is_root_tree": False, "parent_tree_id": "r"},
             {"id": "x", "userinterface_id": "ui2", "is_root_tree": True, "parent_tree_id": None}]
    nodes = [node("a", tree="r"), node("a", tree="c"), node("b", tree="c"), node("z", tree="x"),
             node("e", node_type="entry", tree="r")]
    assert [(n["node_id"], n["tree_id"]) for n in scope.app_screen_nodes(ui, trees, nodes)] == \
        [("a", "r"), ("a", "c"), ("b", "c")]


# ---- coverage maths --------------------------------------------------------------------------------

def s(node_id, ui="stb-testop", family="screen-id", source="run", split="train", label=None, **kw):
    row = {"family": family, "userinterface": ui, "device_model": "stb", "label_source": source,
           "split": split, "eval_version": None, "reference": None,
           "ground_truth": None if source == "none" else {"node_id": node_id, "label": label or node_id}}
    row.update(kw)
    return row


def test_app_coverage_ge1_gek_missing_thin():
    rows = [node("a"), node("a", tree="child"), node("b"), node("c"), node("d")]
    samples = ([s("a")] * 3 + [s("b")] * 2 + [s("c", source="none")] +
               [s("c", ui="web_tv")] +                                   # other app
               [s(None, source="human", label="Popup ")] +               # off-tree
               [s("gone")] +                                             # stale node
               [s("d", source="human", split="eval")] +                  # eval-verified
               [s("a", reference="navigation")] +                        # seeded
               [s(None, family="focus", source="human", split="eval",
                  ground_truth={"focused": "x"})])
    a = cov.app_coverage("stb-testop", "stb", ["stb"], rows, samples, k=3)
    assert (a["screens"], a["node_rows"]) == (4, 5)
    assert a["screens_ge1"] == 3          # a, b, d
    assert a["screens_gek"] == 1          # a has 4 (3 + seeded)
    assert a["pct_gek"] == 25.0
    assert [m["node_id"] for m in a["missing_screens"]] == ["c"]
    assert [(m["node_id"], m["samples"]) for m in a["thin_screens"]] == [("b", 2), ("d", 1)]
    assert a["offtree_labels"] == ["popup"] and a["stale_labels"] == ["gone"]
    assert a["eval_verified"] == 1 and a["seeded_rows"] == 1
    assert a["screen_id_rows"] == 10 and a["screen_id_labelled"] == 9
    assert a["focus"] == {"rows": 1, "labelled": 1, "eval_verified": 1}


def test_failed_verification_row_counts_by_its_label_not_its_node_column():
    a = cov.app_coverage("stb-testop", "stb", ["stb"], [node("a")],
                         [dict(s("a", source="human"), node_id=None)], k=1)
    assert a["screens_gek"] == 1


def test_summary_per_platform_and_global():
    apps = [
        {"name": "stb-testop", "platform": "stb", "screens": 10, "screens_ge1": 6, "screens_gek": 3,
         "eval_verified": 5, "screen_id_labelled": 30},
        {"name": "iad_gui", "platform": "web", "screens": 6, "screens_ge1": 6, "screens_gek": 6,
         "eval_verified": 0, "screen_id_labelled": 6},
        {"name": "web_tv", "platform": "web", "screens": 4, "screens_ge1": 1, "screens_gek": 0,
         "eval_verified": 1, "screen_id_labelled": 1},
    ]
    banners = [s(None, family="banner", ui=None, ground_truth={"channel_number": "1"}),
               s(None, family="banner", ui=None, source="none"),
               s(None, family="banner", ui=None, device_model="android_tv", ground_truth={"x": 1})]
    out = cov.summarize(apps, banners, k=3)
    assert out["global"] == {"screens": 20, "screens_ge1": 13, "screens_gek": 9, "eval_verified": 6,
                             "exhaustiveness_pct": 45.0}
    web = next(p for p in out["platforms"] if p["platform"] == "web")
    assert (web["apps"], web["screens"], web["screens_gek"], web["pct_gek"]) == (["iad_gui", "web_tv"], 10, 6, 60.0)
    stb = next(p for p in out["platforms"] if p["platform"] == "stb")
    assert stb["banner"] == {"rows": 2, "labelled": 1, "eval_verified": 0}
    assert out["banner_by_platform"]["android_tv"]["rows"] == 1


def test_summary_of_nothing_is_zero_not_an_error():
    assert cov.summarize([], [], k=3)["global"]["exhaustiveness_pct"] == 0.0


def _world():
    uis = [{"id": "u1", "name": "stb-testop", "models": ["stb"]},
           {"id": "u2", "name": "stb3_autobuild", "models": ["stb"]},
           {"id": "u3", "name": "google_tv", "models": ["android_mobile", "android_tv"]},
           {"id": "u4", "name": "youtube-web", "models": ["web"]}]
    trees = [{"id": f"t{i}", "userinterface_id": u["id"], "is_root_tree": True, "parent_tree_id": None}
             for i, u in enumerate(uis)]
    nodes = [node("home", tree="t0"), node("guide", tree="t0"), node("x", tree="t1"),
             node("y", tree="t2"), node("Home", tree="t3")]
    samples = [s("home")] * 3 + [s("x", ui="stb3_autobuild")] * 5
    return uis, trees, nodes, samples


def test_compute_scopes_apps_and_lists_the_rest():
    uis, trees, nodes, samples = _world()
    out = cov.compute(uis, trees, nodes, samples, k=3)
    assert [a["name"] for a in out["apps"]] == ["stb-testop", "youtube-web"]
    assert out["global"]["screens"] == 3 and out["global"]["screens_gek"] == 1
    others = {o["name"]: o for o in out["not_in_scope"]}
    assert others["stb3_autobuild"]["reason"] == "excluded (*_autobuild*)"
    assert others["stb3_autobuild"]["screens"] == 1
    assert others["google_tv"]["reason"] == "not in the canonical list"
    assert others["google_tv"]["platform"] == "android_mobile"
    assert out["canonical_missing"] == ["web_tv"]


def test_build_coverage_passes_the_team_to_every_reader_and_clamps_k():
    seen = []
    uis, trees, nodes, samples = _world()

    def rec(name, value):
        def fn(team_id, *a):
            seen.append((name, team_id))
            return value
        return fn

    out = cov.build_coverage(TEAM, 999, load_uis=rec("uis", uis), load_trees=rec("trees", trees),
                             load_nodes=rec("nodes", nodes), load_sample_rows=rec("samples", samples),
                             load_groups=rec("groups", None))
    # step 4k: one screen-group read per in-scope app (stb-testop, youtube-web)
    assert {t for _n, t in seen} == {TEAM} and len(seen) == 6
    assert out["k"] == cov.MAX_K and out["team_id"] == TEAM
    with pytest.raises(ValueError):
        cov.build_coverage("")
    assert cov.clamp_k("abc") == cov.DEFAULT_K and cov.clamp_k(0) == 1


def test_cli_format_mentions_the_global_percentage_and_missing_screens():
    uis, trees, nodes, samples = _world()
    text = report_cli.format_report(cov.compute(uis, trees, nodes, samples, k=3))
    assert "GLOBAL exhaustiveness: 33.3%" in text
    assert "missing: guide" in text and "Not in scope (2)" in text


# ---- seed script ------------------------------------------------------------------------------------

class FakeSeedDeps:
    """In-memory source tree + dataset. Images are bytes whose dhash is given by ``hashes``."""

    def __init__(self, uis, trees, nodes, objects, hashes, enabled=True, opted_in=True):
        self.uis, self.trees, self.nodes = uis, trees, nodes
        self.objects = dict(objects)            # key -> bytes
        self.hashes = dict(hashes)              # bytes -> dhash
        self.rows = []                          # recorded samples (kwargs)
        self.group_rows = {}                    # (model, node) -> [(id, hash, truth, failure)]
        self._enabled, self._opted = enabled, opted_in
        self.reads = []

    def load_userinterfaces(self, team_id):
        assert team_id == TEAM
        return self.uis

    def load_trees(self, team_id, ui_ids):
        return [t for t in self.trees if t["userinterface_id"] in ui_ids]

    def load_nodes(self, team_id, tree_ids):
        return [n for n in self.nodes if n["tree_id"] in tree_ids]

    def resolve(self, url):
        return url

    def exists(self, key):
        return key in self.objects

    def fetch(self, key):
        self.reads.append(key)
        return self.objects.get(key)

    def seeded_refs(self, team_id):
        return [r["source_ref"] for r in self.rows]

    def enabled(self):
        return self._enabled

    def opted_in(self, team_id):
        return self._opted

    def excluded_models(self):
        return {"android_mobile"}

    def dhash(self, image):
        return self.hashes[image]

    def group(self, team_id, model, node_id):
        return list(self.group_rows.get((model, node_id), []))

    def near_dup_bits(self):
        return 8

    def group_cap(self):
        return 20

    def hamming(self, a, b):
        return 0 if a == b else 100

    def informative(self, dhash):
        return not str(dhash).startswith("blank")

    def record(self, **kw):
        sid = f"s{len(self.rows) + 1}"
        self.rows.append(dict(kw, id=sid))
        self.group_rows.setdefault((kw["device_model"], kw["node_id"]), []).append(
            (sid, self.hashes[kw["image"]], kw["ground_truth"], False))
        return sid


def _seed_world(**kw):
    uis = [{"id": "u1", "name": "stb-testop", "models": ["stb"]},
           {"id": "u2", "name": "web_tv", "models": ["web", "host_vnc"]}]
    trees = [{"id": "r1", "userinterface_id": "u1", "is_root_tree": True, "parent_tree_id": None},
             {"id": "c1", "userinterface_id": "u1", "is_root_tree": False, "parent_tree_id": "r1"},
             {"id": "r2", "userinterface_id": "u2", "is_root_tree": True, "parent_tree_id": None}]
    nodes = [
        node("home-node", "home", tree="r1", screenshot="navigation/stb-testop/home.jpg"),
        node("guide", tree="r1", screenshot="navigation/stb-testop/guide.jpg"),
        node("guide", tree="c1", screenshot="navigation/stb-testop/guide.jpg"),   # nested copy, same image
        node("noshot", tree="r1", shot=False),
        node("gone", tree="r1", screenshot="navigation/stb-testop/gone.jpg"),     # object missing
        node("act", node_type="action", tree="r1", screenshot="navigation/stb-testop/act.jpg"),
        node("home-node", "home", tree="r2", screenshot="https://old/navigation/perseus/home.jpg"),
    ]
    objects = {"navigation/stb-testop/home.jpg": b"H1", "navigation/stb-testop/guide.jpg": b"G1",
               "navigation/stb-testop/act.jpg": b"A1", "navigation/web_tv/home.jpg": b"W1"}
    hashes = {b"H1": "h1", b"G1": "g1", b"A1": "a1", b"W1": "w1"}
    return FakeSeedDeps(uis, trees, nodes, objects, hashes, **kw)


ARGS = ["--team", TEAM, "--userinterfaces", "stb-testop,web_tv"]


@pytest.mark.parametrize("names", ["stb-testop,stb3_autobuild", "google_tv", "stb_tv_settings", "__ci_x", ""])
def test_seed_refuses_non_canonical_and_excluded_names_before_reading(names):
    deps = _seed_world()
    with pytest.raises(seed.SeedError):
        seed.run(["--team", TEAM, "--userinterfaces", names], deps=deps)
    assert deps.reads == [] and deps.rows == []


def test_seed_real_run_records_train_samples_with_the_run_label():
    deps = _seed_world()
    out = seed.run(ARGS, deps=deps)
    stb, web = out["apps"]
    assert stb["counts"] == {"seeded": 2, "skipped-exists": 1, "no-screenshot": 1, "image-missing": 1}
    assert web["counts"] == {"seeded": 1}
    assert web["notes"] and "'web'" in web["notes"][0]            # several models: the first is used
    first = deps.rows[0]
    assert first["family"] == "screen-id" and first["label_source"] == "run" and first["split"] == "train"
    assert first["force"] is False and first["team_id"] == TEAM and first["device_model"] == "stb"
    assert first["ground_truth"] == {"node_id": "home-node", "label": "home"}
    assert first["source_ref"] == {"reference": "navigation", "tree_id": "r1", "node_id": "home-node",
                                   "userinterface": "stb-testop", "screenshot": "navigation/stb-testop/home.jpg"}
    # the web_tv screenshot URL points at another folder: the label fallback found it
    assert deps.rows[-1]["source_ref"]["screenshot"] == "navigation/web_tv/home.jpg"
    assert deps.rows[-1]["device_model"] == "web" and deps.rows[-1]["userinterface"] == "web_tv"


def test_seed_is_idempotent():
    deps = _seed_world()
    seed.run(ARGS, deps=deps)
    n = len(deps.rows)
    reads = len(deps.reads)
    again = seed.run(ARGS, deps=deps)
    assert len(deps.rows) == n
    assert len(deps.reads) == reads                    # nothing downloaded a second time
    assert again["totals"].get("seeded", 0) == 0
    assert again["totals"]["skipped-exists"] == 4      # 2 stb-testop + nested copy + web_tv


def test_same_node_id_in_another_app_is_not_skipped_as_existing():
    deps = _seed_world()
    seed.run(["--team", TEAM, "--userinterfaces", "stb-testop"], deps=deps)
    out = seed.run(["--team", TEAM, "--userinterfaces", "web_tv"], deps=deps)
    assert out["apps"][0]["counts"] == {"seeded": 1}   # home-node of web_tv is its own screen


def test_seed_classifies_duplicate_and_cap():
    deps = _seed_world()
    deps.group_rows[("stb", "home-node")] = [("old", "h1", {"node_id": "home-node"}, False)]
    deps.group_rows[("stb", "guide")] = [(f"r{i}", f"x{i}", None, False) for i in range(20)]
    out = seed.run(["--team", TEAM, "--userinterfaces", "stb-testop"], deps=deps)
    counts = out["apps"][0]["counts"]
    assert counts["skipped-duplicate"] == 1 and counts["skipped-cap"] == 2 and "seeded" not in counts
    assert deps.rows == []


def test_seed_classify_low_information_is_never_a_duplicate_but_is_capped():
    """Step 4j: a black poweroff / standby screenshot mirrors should_keep."""
    info = FakeSeedDeps.informative
    same = lambda a, b: 0   # noqa: E731 - every pair "identical"
    group = [("old", "blank-a", {"node_id": "standby"}, False)]
    assert seed.classify("blank-b", group, ["blank-c"], 8, 20, same, lambda h: info(None, h)) is None
    assert seed.classify("h1", group, [], 8, 20, same, lambda h: info(None, h)) is None
    assert seed.classify("h1", group + [("o2", "h2", None, False)], [], 8, 20, same,
                         lambda h: info(None, h)) == "skipped-duplicate"
    full = [(f"r{i}", f"x{i}", None, False) for i in range(20)]
    assert seed.classify("blank-b", full, [], 8, 20, same, lambda h: info(None, h)) == "skipped-cap"


def test_dry_run_writes_nothing_and_needs_no_opt_in():
    deps = _seed_world(enabled=False, opted_in=False)
    out = seed.run(ARGS + ["--dry-run"], deps=deps)
    assert deps.rows == []
    assert out["totals"]["would-seed"] == 3
    # the nested copy of guide carries the same image: a real run skips it (exists), the dry run
    # sees it as a near-duplicate of the frame it would have seeded
    assert out["apps"][0]["counts"]["skipped-duplicate"] == 1


@pytest.mark.parametrize("enabled,opted", [(False, True), (True, False)])
def test_real_run_stops_when_capture_is_off_or_team_not_opted_in(enabled, opted):
    deps = _seed_world(enabled=enabled, opted_in=opted)
    with pytest.raises(seed.SeedError):
        seed.run(ARGS, deps=deps)
    assert deps.reads == [] and deps.rows == []


def test_split_flag_is_passed_through_and_validated():
    deps = _seed_world()
    seed.run(ARGS + ["--split", "eval"], deps=deps)
    assert {r["split"] for r in deps.rows} == {"eval"}
    with pytest.raises(SystemExit):
        seed.run(ARGS + ["--split", "test"], deps=_seed_world())


def test_limit_caps_the_attempts():
    deps = _seed_world()
    out = seed.run(ARGS + ["--limit", "1"], deps=deps)
    assert len(deps.rows) == 1 and out["totals"]["skipped-limit"] == 3


def test_phone_app_is_refused(monkeypatch):
    monkeypatch.setitem(scope.CANONICAL_USERINTERFACES, "phone_app", "android_mobile")
    deps = _seed_world()
    deps.uis.append({"id": "u9", "name": "phone_app", "models": ["android_mobile"]})
    with pytest.raises(seed.SeedError, match="phone/tablet"):
        seed.run(["--team", TEAM, "--userinterfaces", "phone_app"], deps=deps)


# ---- route ------------------------------------------------------------------------------------------

@pytest.fixture
def client(monkeypatch):
    calls = []

    def fake_build(team_id, k=3, **kw):
        calls.append((team_id, k))
        return {"team_id": team_id, "k": k, "global": {"exhaustiveness_pct": 12.5}, "platforms": [],
                "apps": [], "not_in_scope": []}

    monkeypatch.setattr(routes.dataset_coverage, "build_coverage", fake_build)
    app = Flask(__name__)

    @app.before_request
    def _principal():
        request.user_role = request.headers.get("X-Test-Role", "admin")

    app.register_blueprint(routes.server_training_samples_bp)
    c = app.test_client()
    c.calls = calls
    return c


@pytest.mark.parametrize("role", ["tester", "viewer"])
def test_coverage_route_is_admin_only(client, role):
    r = client.get(f"/server/training-samples/coverage?team_id={TEAM}", headers={"X-Test-Role": role})
    assert r.status_code == 403 and client.calls == []


def test_coverage_route_needs_team_and_is_scoped_to_it(client):
    assert client.get("/server/training-samples/coverage").status_code == 400
    r = client.get(f"/server/training-samples/coverage?team_id={OTHER}&k=5")
    assert r.status_code == 200 and r.get_json()["team_id"] == OTHER
    assert client.calls == [(OTHER, 5)]


def test_coverage_route_clamps_k(client):
    client.get(f"/server/training-samples/coverage?team_id={TEAM}&k=0")
    client.get(f"/server/training-samples/coverage?team_id={TEAM}&k=nope")
    client.get(f"/server/training-samples/coverage?team_id={TEAM}&k=10000")
    assert [k for _t, k in client.calls] == [1, 3, cov.MAX_K]


def test_iad_gui_is_out_of_scope():
    assert "iad_gui" not in scope.CANONICAL_USERINTERFACES
    assert scope.scope_refusal("iad_gui") is not None



# ---- step 4k: screens are screen groups ------------------------------------------------------------

def _groups():
    from shared.src.lib.ai import screen_groups as sg
    key = lambda k: {"command": "press_key", "params": {"key": k}}  # noqa: E731
    nodes = [{"node_id": n, "label": n, "node_type": "screen"} for n in
             ("home", "home_apps", "home_tvguide", "apps", "live")]
    edges = [{"source_node_id": a, "target_node_id": b, "default_action_set_id": f"{a}-{b}",
              "action_sets": [{"id": f"{a}-{b}", "actions": [key(k)]}]}
             for a, b, k in (("home", "home_tvguide", "RIGHT"), ("home_tvguide", "home_apps", "RIGHT"),
                             ("home_apps", "apps", "OK"), ("home", "live", "BACK"))]
    return sg.from_rows(nodes, edges)


def test_screens_are_groups_and_states_are_their_nodes():
    groups = _groups()
    rows = [node(n) for n in ("home", "home_apps", "home_tvguide", "apps", "live")]
    grouped = groups.label_for("home_apps")
    samples = ([s("home")] * 2 +                                   # pre-4k label of home
               [dict(s("x"), ground_truth=grouped)] +               # group label, node home_apps
               [s("home_tvguide")] +                                # pre-4k label of a tab
               [s("apps")])
    a = cov.app_coverage("stb-testop", "stb", ["stb"], rows, samples, k=3, groups=groups)
    assert (a["screens"], a["node_screens"], a["grouped"]) == (3, 5, True)
    by = {g["label"]: g for g in a["groups"]}
    assert set(by) == {"home", "apps", "live"}
    assert by["home"]["samples"] == 4 and a["screens_gek"] == 1           # home: 2 + 1 + 1
    assert (by["home"]["states_covered"], by["home"]["states_total"]) == (3, 3)
    assert {st["label"]: st["samples"] for st in by["home"]["states"]} ==         {"home": 2, "home_apps": 1, "home_tvguide": 1}
    assert [m["label"] for m in a["missing_screens"]] == ["live"]
    assert [m["label"] for m in a["thin_screens"]] == ["apps"]


def test_coverage_without_groups_is_per_node():
    rows = [node("home"), node("home_apps")]
    a = cov.app_coverage("stb-testop", "stb", ["stb"], rows, [s("home")], k=1)
    assert (a["screens"], a["grouped"]) == (2, False)


def test_seed_labels_every_node_frame_with_its_group():
    from shared.src.lib.ai import screen_groups as sg
    key = {"command": "press_key", "params": {"key": "RIGHT"}}
    groups = sg.from_rows([{"node_id": "home-node", "label": "home"}, {"node_id": "guide", "label": "guide"}],
                          [{"source_node_id": "home-node", "target_node_id": "guide", "default_action_set_id": "s",
                            "action_sets": [{"id": "s", "actions": [key]}]}])
    deps = _seed_world()
    deps.groups = lambda team_id, ui: groups if ui == "stb-testop" else None
    out = seed.run(ARGS, deps=deps)
    assert out["apps"][0]["groups"] == 1 and out["apps"][1]["groups"] is None
    by_node = {r["node_id"]: r for r in deps.rows if r["userinterface"] == "stb-testop"}
    assert set(by_node) == {"home-node", "guide"}              # every node frame is still seeded
    assert by_node["guide"]["ground_truth"] == {"node_id": "home-node", "label": "home", "node": "guide",
                                                "node_label": "guide", "focus": "guide"}
    assert by_node["home-node"]["ground_truth"]["focus"] is None
    web = next(r for r in deps.rows if r["userinterface"] == "web_tv")
    assert web["ground_truth"] == {"node_id": "home-node", "label": "home"}   # no groups: per node


def test_load_screen_nodes_chunks_trees_and_skips_screenshot_for_coverage(monkeypatch):
    calls = []

    class Q:
        def __init__(self): self.sel = None; self.chunk = None
        def table(self, name): return self
        def select(self, cols): self.sel = cols; return self
        def eq(self, *a): return self
        def in_(self, col, vals):
            if col == 'tree_id': self.chunk = list(vals)
            return self
        def order(self, *a): return self
        def range(self, *a): return self
        def execute(self):
            calls.append((self.sel, len(self.chunk)))
            return type('R', (), {'data': []})()

    monkeypatch.setattr(scope, '_client', lambda: Q())
    scope.load_screen_nodes('t', [f'id{i}' for i in range(92)], with_screenshot=False)
    assert [n for _, n in calls] == [25, 25, 25, 17]
    assert all('screenshot' not in sel for sel, _ in calls)
    calls.clear()
    scope.load_screen_nodes('t', ['a'])
    assert 'screenshot' in calls[0][0]
