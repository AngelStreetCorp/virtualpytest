"""ai-dataset feature: export_dataset.py (TASK-27 step 6) + training/dataset.py loader (step 7).

Pure unit tests: no DB, no bucket, no GPU. The export script is loaded from its path with a
stub ``family_prompts`` module in ``sys.modules`` (the real one is step 5's
``features/ai-dataset/lib/family_prompts.py``; the stub has the same interface). The DB
listing, the tree labels and the storage client are fakes passed to ``run(...)``.

Run: pytest tests/backend_server/test_ai_dataset_export.py -v
"""
import importlib.util
import json
import os
import subprocess
import shutil
import sys
import types

import pytest

_TEST_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.normpath(os.path.join(_TEST_DIR, "..", ".."))
_SCRIPT = os.path.join(_REPO_ROOT, "features", "ai-dataset", "scripts", "export_dataset.py")
_LOADER = os.path.join(_REPO_ROOT, "training", "dataset.py")

pytestmark = pytest.mark.unit

TEAM = "7fdeb4bb-3639-4ec3-959f-b54769a219ce"


def _stub_prompts():
    mod = types.ModuleType("family_prompts")
    mod.FAMILY_PROMPTS = {f: f"Q[{f}]" for f in ("screen-id", "focus", "menu", "banner", "av-fault")}

    def build_prompt(family, sample, context=None):
        if family == "screen-id":
            return f"Which screen? One of: {', '.join(context['screen_labels'])}"
        return mod.FAMILY_PROMPTS[family]

    mod.build_prompt = build_prompt
    mod.answer_to_text = lambda family, gt: json.dumps(gt, sort_keys=True)
    mod.parse_answer = lambda family, text: json.loads(text)
    # step 4k: the focus question of a grouped screen-id label
    mod.focus_truth = lambda gt: ({"focused": gt["focus"]} if isinstance(gt, dict) and gt.get("node_id")
                                  and gt.get("focus") else None)
    return mod


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def exp(monkeypatch):
    monkeypatch.setitem(sys.modules, "family_prompts", _stub_prompts())
    return _load("export_dataset", _SCRIPT)


@pytest.fixture
def loader():
    return _load("vpt_training_dataset", _LOADER)


def row(i, family="banner", source="run", split="train", gt=None, **kw):
    base = {
        "id": f"00000000-0000-0000-0000-{i:012d}", "team_id": TEAM, "family": family,
        "object_key": f"{TEAM}/{family}/stb/2026-09/{i}.jpg", "device_model": "stb",
        "userinterface": "example_tv", "split": split, "label_source": source,
        "ground_truth": gt if gt is not None else {"channel_number": str(i)},
        "model_answer": None, "eval_version": None, "is_failure": False, "label_conflict": False,
        "created_at": f"2026-09-29T10:{i % 60:02d}:00Z",
    }
    base.update(kw)
    return base


class FakeDB:
    """Mimics ai_training_samples_db.list_samples filtering (team, family, split, sources)."""

    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def __call__(self, team_id, family=None, split=None, label_sources=None, limit=50, offset=0, **kw):
        self.calls.append((team_id, family, split, tuple(label_sources or ())))
        match = [r for r in self.rows if r["team_id"] == team_id and r["family"] == family
                 and (split is None or r["split"] == split)
                 and (not label_sources or r["label_source"] in label_sources)]
        return [dict(r) for r in match[offset:offset + limit]], len(match)


class FakeStorage:
    def __init__(self, missing=()):
        self.missing = set(missing)
        self.keys = []

    def download_file(self, key, local):
        self.keys.append(key)
        if key in self.missing:
            return {"success": False, "error": "404"}
        os.makedirs(os.path.dirname(local), exist_ok=True)
        with open(local, "wb") as fh:
            fh.write(b"\xff\xd8jpeg")
        return {"success": True}


def labels_fn(team, ui):
    return ["home", "live", "tv_guide"] if ui == "example_tv" else None


def run(exp, argv, rows, storage=None):
    return exp.run(argv, list_fn=FakeDB(rows), screen_label_fn=labels_fn,
                   storage=storage or FakeStorage())


def read_out(tmp_path, version="v9"):
    d = tmp_path / f"dataset-combined-{version}"
    lines = [json.loads(l) for l in (d / "train.jsonl").read_text(encoding="utf-8").splitlines()]
    return d, lines, json.loads((d / "manifest.json").read_text(encoding="utf-8"))


# ---- guards -----------------------------------------------------------------------------

def test_teams_is_required(exp):
    with pytest.raises(SystemExit):
        exp.run(["--version", "v1", "--dry-run"], list_fn=FakeDB([]))
    with pytest.raises(exp.ExportError):
        exp.run(["--teams", " , ", "--dry-run"], list_fn=FakeDB([]))


def test_cli_refuses_without_teams():
    proc = subprocess.run([sys.executable, _SCRIPT, "--dry-run"], capture_output=True, text=True)
    assert proc.returncode == 2 and "--teams" in proc.stderr


@pytest.mark.parametrize("bad", [
    {"split": "eval"}, {"split": "holdout"}, {"eval_version": "eval-v1"},
    {"label_source": "none"}, {"ground_truth": None}, {"object_key": ""},
])
def test_check_row_refuses(exp, bad):
    r = row(1)
    r.update(bad)
    with pytest.raises(exp.ExportError):
        exp.check_row(r, include_teacher=True)


def test_teacher_only_with_flag(exp):
    with pytest.raises(exp.ExportError):
        exp.check_row(row(1, source="teacher"), include_teacher=False)
    exp.check_row(row(1, source="teacher"), include_teacher=True)


def test_teacher_rows_not_requested_without_flag(exp, tmp_path):
    db = FakeDB([row(1), row(2, source="teacher")])
    exp.run(["--teams", TEAM, "--version", "v9", "--out", str(tmp_path)], list_fn=db,
            screen_label_fn=labels_fn, storage=FakeStorage())
    assert all("teacher" not in c[3] and "none" not in c[3] for c in db.calls)
    assert all(c[2] == "train" for c in db.calls)
    _, lines, manifest = read_out(tmp_path)
    assert [l["id"] for l in lines] == [row(1)["id"]]
    assert manifest["options"]["label_sources"] == ["run", "human"]


def test_frozen_train_row_refuses_whole_export(exp, tmp_path):
    rows = [row(1), row(2, eval_version="eval-v1")]
    with pytest.raises(exp.ExportError):
        run(exp, ["--teams", TEAM, "--version", "v9", "--out", str(tmp_path)], rows)
    assert not (tmp_path / "dataset-combined-v9").exists()


def test_eval_rows_never_exported(exp, tmp_path):
    rows = [row(1), row(2, split="eval", source="human"), row(3, split="holdout")]
    run(exp, ["--teams", TEAM, "--version", "v9", "--out", str(tmp_path)], rows)
    _, lines, manifest = read_out(tmp_path)
    assert [l["id"] for l in lines] == [row(1)["id"]]
    assert manifest["eval_rows"] == 0
    assert '"split": "eval"' not in json.dumps(manifest)


def test_rows_a_second_ai_pass_could_not_settle_never_train(exp, tmp_path):
    rows = [row(1), row(2, triage={"status": "excluded", "reason": "disagrees_with_run"}),
            row(3, triage=json.dumps({"status": "agreed"})), row(4, triage="not json")]
    run(exp, ["--teams", TEAM, "--version", "v9", "--out", str(tmp_path)], rows)
    _, lines, manifest = read_out(tmp_path)
    assert sorted(l["id"] for l in lines) == [row(1)["id"], row(3)["id"], row(4)["id"]]
    assert exp.excluded_by_triage(row(2, triage={"status": "excluded"}))
    assert not exp.excluded_by_triage(row(5))


def test_unknown_family_refused(exp):
    with pytest.raises(exp.ExportError):
        run(exp, ["--teams", TEAM, "--families", "other", "--dry-run"], [])


# ---- JSONL shape and trainer format ---------------------------------------------------------

def test_jsonl_shape_and_loader(exp, loader, tmp_path):
    rows = [row(1), row(2, family="screen-id", gt={"node_id": "n1", "label": "home"}),
            row(3, family="screen-id", gt={"node_id": None, "label": "popup"}, source="human")]
    run(exp, ["--teams", TEAM, "--version", "v9", "--out", str(tmp_path)], rows)
    d, lines, _ = read_out(tmp_path)
    assert len(lines) == 3
    for line in lines:
        loader.validate_line(line)
        user, assistant = line["messages"]
        assert user["content"][0] == {"type": "image", "image": f"images/{line['id']}.jpg"}
        assert (d / user["content"][0]["image"]).is_file()
        assert isinstance(assistant["content"], str)
        assert set(line) == {"messages", "family", "id"}
    sid = next(l for l in lines if l["id"] == row(2)["id"])
    assert sid["messages"][0]["content"][1]["text"] == "Which screen? One of: home, live, tv_guide"
    assert json.loads(sid["messages"][1]["content"]) == {"node_id": "n1", "label": "home"}

    convs = loader.load(str(d), open_images=False)
    assert len(convs) == 3
    user, assistant = convs[0]["messages"]
    assert user["content"][0]["type"] == "image" and os.path.isabs(user["content"][0]["image"])
    assert assistant["content"] == [{"type": "text", "text": lines[0]["messages"][1]["content"]}]


def test_loader_rejects_bad_lines(loader):
    good = {"messages": [{"role": "user", "content": [{"type": "image", "image": "images/a.jpg"},
                                                      {"type": "text", "text": "q"}]},
                         {"role": "assistant", "content": "{}"}], "family": "banner", "id": "a"}
    loader.validate_line(good)
    for mutate in (lambda o: o.pop("family"),
                   lambda o: o["messages"][0]["content"].pop(0),
                   lambda o: o["messages"][0]["content"][0].update(image="/abs/a.jpg"),
                   lambda o: o["messages"][1].update(content="")):
        bad = json.loads(json.dumps(good))
        mutate(bad)
        with pytest.raises(loader.DatasetFormatError):
            loader.validate_line(bad)


def test_screen_id_without_tree_is_skipped(exp, tmp_path):
    rows = [row(1, family="screen-id", gt={"node_id": "n", "label": "x"}, userinterface="gone"),
            row(2, family="screen-id", gt={"node_id": "n", "label": "home"})]
    run(exp, ["--teams", TEAM, "--version", "v9", "--out", str(tmp_path)], rows)
    _, lines, manifest = read_out(tmp_path)
    assert [l["id"] for l in lines] == [row(2)["id"]]
    assert manifest["skipped"] == {"screen-id:no_tree_labels": 1}


# ---- manifest, balance, cap -------------------------------------------------------------------

def test_manifest_counts(exp, tmp_path):
    rows = ([row(i) for i in range(1, 4)]
            + [row(4, source="human", device_model="android_tv", label_conflict=True)]
            + [row(5, family="screen-id", gt={"node_id": "n", "label": "home"}, is_failure=True)])
    storage = FakeStorage(missing={rows[1]["object_key"]})
    run(exp, ["--teams", TEAM, "--version", "v9", "--out", str(tmp_path)], rows, storage)
    _, lines, m = read_out(tmp_path)
    assert m["name"] == "dataset-combined-v9" and m["version"] == "v9" and m["teams"] == [TEAM]
    assert m["total"] == len(lines) == 4
    assert m["counts"]["family"] == {"banner": 3, "screen-id": 1}
    assert m["counts"]["label_source"]["banner"] == {"run": 2, "human": 1}
    assert m["counts"]["device_model"]["banner"] == {"stb": 2, "android_tv": 1}
    assert m["counts"]["split"] == {"banner": {"train": 3}, "screen-id": {"train": 1}}
    assert m["counts"]["label_conflict"]["banner"] == 1
    assert m["counts"]["is_failure"]["screen-id"] == 1
    assert m["skipped"] == {"image_missing": 1}
    assert m["eval_rows"] == 0
    assert set(m["prompt_hash"]) == {"banner", "screen-id"} and len(m["prompt_hash"]["banner"]) == 16
    assert m["git_hash"] and m["created_at"].endswith("+00:00")
    assert m["families"] == ["screen-id", "banner"]


def test_default_families_are_those_with_rows(exp, capsys):
    rows = [row(1), row(2, family="focus", gt={"focused": "Settings"})]
    assert run(exp, ["--teams", TEAM, "--dry-run"], rows) == 0
    m = json.loads(capsys.readouterr().out)
    assert m["families"] == ["focus", "banner"] and m["total"] == 2


def test_dry_run_writes_nothing(exp, tmp_path):
    storage = FakeStorage()
    run(exp, ["--teams", TEAM, "--version", "v9", "--out", str(tmp_path), "--dry-run"], [row(1)], storage)
    assert storage.keys == [] and list(tmp_path.iterdir()) == []


def test_cap_per_family_balances_and_prefers_human(exp, tmp_path):
    rows = ([row(i) for i in range(1, 11)]
            + [row(11, source="human"), row(12, is_failure=True)]
            + [row(20 + i, family="focus", gt={"focused": "x"}) for i in range(3)])
    run(exp, ["--teams", TEAM, "--version", "v9", "--out", str(tmp_path), "--cap-per-family", "4"], rows)
    _, lines, m = read_out(tmp_path)
    banner = [l["id"] for l in lines if l["family"] == "banner"]
    assert len(banner) == 4 and banner[0] == row(11)["id"] and banner[1] == row(12)["id"]
    assert m["balance"]["banner"] == {"available": 12, "exported": 4, "share_pct": 57.1}
    assert m["balance"]["focus"]["exported"] == 3
    # deterministic: same seed, same pick
    tmp2 = tmp_path / "again"
    run(exp, ["--teams", TEAM, "--version", "v9", "--out", str(tmp2), "--cap-per-family", "4"], rows)
    _, lines2, _ = read_out(tmp2)
    assert [l["id"] for l in lines2] == [l["id"] for l in lines]


def test_limit_is_round_robin(exp, tmp_path):
    rows = [row(i) for i in range(1, 10)] + [row(20 + i, family="focus", gt={"focused": "x"}) for i in range(9)]
    run(exp, ["--teams", TEAM, "--version", "v9", "--out", str(tmp_path), "--limit", "5"], rows)
    _, _, m = read_out(tmp_path)
    assert m["counts"]["family"] == {"focus": 3, "banner": 2}


def test_existing_target_refused(exp, tmp_path):
    run(exp, ["--teams", TEAM, "--version", "v9", "--out", str(tmp_path)], [row(1)])
    with pytest.raises(exp.ExportError):
        run(exp, ["--teams", TEAM, "--version", "v9", "--out", str(tmp_path)], [row(1)])


def test_freeze_strip_exports_one_image(exp, tmp_path):
    strip = row(7, family="av-fault", source="human",
                gt={"incident_type": None, "static_screen": True},
                model_answer={"incident_type": "freeze", "evidence": "strip",
                              "duration_ms": 30174, "frames": [0.0, 15.0, 30.2]})
    storage = FakeStorage()
    run(exp, ["--teams", TEAM, "--version", "v9", "--out", str(tmp_path)], [strip], storage)
    d, lines, m = read_out(tmp_path)
    assert storage.keys == [strip["object_key"]]
    assert os.listdir(d / "images") == [f"{strip['id']}.jpg"]
    images = [p for p in lines[0]["messages"][0]["content"] if p["type"] == "image"]
    assert len(images) == 1
    assert m["counts"]["freeze_strip"] == 1


def test_multi_team_counts(exp, tmp_path):
    other = "22222222-2222-2222-2222-222222222222"
    rows = [row(1), row(2, team_id=other)]
    run(exp, ["--teams", f"{TEAM},{other}", "--version", "v9", "--out", str(tmp_path)], rows)
    _, _, m = read_out(tmp_path)
    assert m["counts"]["team"] == {TEAM: {"banner": 1}, other: {"banner": 1}}


# ---- shell scripts -----------------------------------------------------------------------------

@pytest.mark.parametrize("script", ["train_combined.sh", "merge_and_convert.sh"])
def test_shell_scripts_parse(script):
    bash = shutil.which("bash")
    if not bash:
        pytest.skip("no bash")
    path = os.path.join(_REPO_ROOT, "training", script)
    with open(path, "rb") as fh:
        assert b"\r\n" not in fh.read(), "CRLF line endings would break the script on Linux"
    proc = subprocess.run([bash, "-n", path], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


def test_git_hash_falls_back_to_version_file(exp, monkeypatch, tmp_path):
    monkeypatch.delenv("VPT_GIT_HASH", raising=False)
    monkeypatch.setattr(exp.subprocess, "check_output",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("no git")))
    (tmp_path / "VERSION.txt").write_text("current:main-2026.09.29-9404\nprevious:x\n")
    monkeypatch.setattr(exp, "_REPO_ROOT", str(tmp_path))
    assert exp.git_hash() == "version:main-2026.09.29-9404"
    monkeypatch.setenv("VPT_GIT_HASH", "abc123")
    assert exp.git_hash() == "abc123"


# ---- against the real step 5 prompts module ----------------------------------------------------

@pytest.fixture
def exp_real(monkeypatch):
    """export_dataset with the real features/ai-dataset/lib/family_prompts.py (no stub)."""
    monkeypatch.delitem(sys.modules, "family_prompts", raising=False)
    mod = _load("export_dataset_real", _SCRIPT)
    real = mod.load_prompts()
    assert os.path.normpath(real.__file__) == os.path.normpath(
        os.path.join(_REPO_ROOT, "features", "ai-dataset", "lib", "family_prompts.py"))
    return mod


def test_real_prompts_end_to_end(exp_real, loader, tmp_path):
    rows = [row(1, gt={"channel_number": "7", "channel_name": None}),
            row(2, family="screen-id", gt={"node_id": "node-1761667661932", "label": "replay"}),
            row(3, family="screen-id", gt={"node_id": None, "label": "Popup"}, source="human"),
            row(4, family="av-fault", source="human", gt={"incident_type": "freeze"},
                model_answer={"incident_type": "freeze", "evidence": "strip", "frames": [0.0, 15.0, 30.2]}),
            row(5, family="focus", gt={"focused": "Settings"})]
    run(exp_real, ["--teams", TEAM, "--version", "v9", "--out", str(tmp_path)], rows)
    d, lines, m = read_out(tmp_path)
    assert m["total"] == 5 and m["eval_rows"] == 0
    by_id = {l["id"]: l for l in lines}
    for line in lines:
        loader.validate_line(line)
    answers = {i: json.loads(by_id[row(i)["id"]]["messages"][1]["content"]) for i in range(1, 6)}
    assert answers[2] == {"label": "replay"}                       # a name, never a node id
    assert answers[3] == {"node_id": None, "label": "popup"}
    assert answers[1] == {"banner_detected": True, "channel_name": "", "channel_number": "7"}
    assert answers[4] == {"incident_type": "freeze"}
    sid_prompt = by_id[row(2)["id"]]["messages"][0]["content"][1]["text"]
    assert "- home" in sid_prompt and "- tv_guide" in sid_prompt
    assert "+15.0 s" in by_id[row(4)["id"]]["messages"][0]["content"][1]["text"]
    assert set(m["prompt_hash"]) == {"screen-id", "focus", "banner", "av-fault"}


# ---- step 4k: a grouped screen-id row with a focus is two lessons --------------------------------

def test_grouped_screen_id_row_with_focus_exports_two_lessons(exp_real, loader, tmp_path):
    rows = [row(1, family="screen-id", gt={"node_id": "n-home", "label": "home", "node": "n-apps",
                                           "node_label": "home_apps", "focus": "Apps"}),
            row(2, family="screen-id", gt={"node_id": "n-home", "label": "home", "node": "n-home",
                                           "node_label": "home", "focus": None}),
            row(3, family="screen-id", gt={"node_id": "n-live", "label": "live"})]
    run(exp_real, ["--teams", TEAM, "--version", "v9", "--out", str(tmp_path)], rows)
    d, lines, m = read_out(tmp_path)
    for line in lines:
        loader.validate_line(line)
    ids = [l["id"] for l in lines]
    first = row(1)["id"]
    assert ids.count(first) == 1 and f"{first}:focus" in ids
    assert f"{row(2)['id']}:focus" not in ids and f"{row(3)['id']}:focus" not in ids   # null / pre-4k: one lesson
    assert len(lines) == 4 and m["total"] == 3 and m["counts"]["focus_from_screen_id"] == 1
    by_id = {l["id"]: l for l in lines}
    screen, focus = by_id[first], by_id[f"{first}:focus"]
    assert json.loads(screen["messages"][1]["content"]) == {"label": "home"}          # the group
    assert json.loads(focus["messages"][1]["content"]) == {"focused": "Apps"}
    assert focus["family"] == "focus"
    assert focus["messages"][0]["content"][0]["image"] == screen["messages"][0]["content"][0]["image"]
    assert "highlighted" in focus["messages"][0]["content"][1]["text"]
    assert "asked separately" in screen["messages"][0]["content"][1]["text"]
