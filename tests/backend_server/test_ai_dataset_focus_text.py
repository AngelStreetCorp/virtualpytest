"""ai-dataset feature: step 4l focus-text teacher pass (TASK-27).

``scripts/focus_text_pass.py``: an AI reads the visible text of the focused item on grouped
``screen-id`` rows. Export selection (grouped rows with a focus only, human focus skipped,
blind), import validation, the focus update (rest of the label untouched, ``label_source``
kept), the ``focus_teacher`` record, low confidence to ``needs_human``, and the step 4i
interaction (a ``focus_teacher``-only record is not a triage).

Pure: every DB and storage call is a fake.

Run: pytest tests/backend_server/test_ai_dataset_focus_text.py -v
"""
import importlib
import importlib.util
import json
import os
import re
import sys
from collections import Counter

import pytest

_TEST_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.normpath(os.path.join(_TEST_DIR, "..", ".."))
sys.path.insert(0, _REPO_ROOT)

from shared.src.lib.database import ai_training_samples_db as samples_db  # noqa: E402

label_write = importlib.import_module("features.ai-dataset.lib.label_write")  # noqa: E402
triage_db = importlib.import_module("features.ai-dataset.lib.triage_db")  # noqa: E402

pytestmark = pytest.mark.unit

TEAM = "7fdeb4bb-3639-4ec3-959f-b54769a219ce"
HASH = "0f" * 32
HOME = "6b0e0f7a-1111-4a4a-9a9a-000000000001"
REC = "6b0e0f7a-1111-4a4a-9a9a-000000000003"
APPS = "6b0e0f7a-1111-4a4a-9a9a-000000000004"
DISNEY = "6b0e0f7a-1111-4a4a-9a9a-000000000005"


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, os.path.join(_REPO_ROOT, *rel.split("/")))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def ftp():
    return _load("focus_text_pass_under_test", "features/ai-dataset/scripts/focus_text_pass.py")


@pytest.fixture(scope="module")
def tb():
    return _load("triage_batch_for_focus_test", "features/ai-dataset/scripts/triage_batch.py")


def _gt(group=HOME, glabel="home", node=REC, nlabel="home_recodings", focus="recodings"):
    return {"node_id": group, "label": glabel, "node": node, "node_label": nlabel, "focus": focus}


def _row(sid, gt=None, label_source="run", **kw):
    row = {"id": sid, "team_id": TEAM, "family": "screen-id", "object_key": f"{TEAM}/screen-id/stb/{sid}.jpg",
           "dhash": HASH, "device_model": "stb", "userinterface": "stb_tv", "node_id": REC,
           "focus_label": None, "model_answer": None, "ground_truth": _gt() if gt is None else gt,
           "label_source": label_source, "is_failure": False, "label_conflict": False, "split": "train",
           "eval_version": None, "source_ref": None, "triage": None, "created_at": "2026-09-30T10:00:00Z"}
    row.update(kw)
    return row


class FakeStorage:
    def download_file(self, key, local):
        os.makedirs(os.path.dirname(local), exist_ok=True)
        with open(local, "wb") as fh:
            fh.write(b"\xff\xd8jpeg")
        return {"success": True}


def _list_fn(rows):
    def fn(team_id, family=None, limit=50, offset=0, **_kw):
        assert team_id == TEAM
        out = [r for r in rows if r["family"] == family]
        return out[offset:offset + limit], len(out)
    return fn


def _export(ftp, tmp_path, rows, *extra):
    out = tmp_path / "ftp"
    args = ftp.build_arg_parser().parse_args(["export", "--team", TEAM, "--out", str(out), *extra])
    assert ftp.run_export(args, list_fn=_list_fn(rows), storage=FakeStorage(), out=open(os.devnull, "w")) == 0
    raw = (out / "batch.jsonl").read_text(encoding="utf-8")
    key = json.loads((out / "key.json").read_text(encoding="utf-8"))
    return out, raw, [json.loads(line) for line in raw.splitlines()], key


# ---- export: selection -----------------------------------------------------------------------

def test_selects_only_grouped_rows_with_a_focus(ftp):
    rows = [
        _row("rec"),
        _row("own", gt=_gt(node=HOME, nlabel="home", focus=None)),        # the group's own node
        _row("pre4k", gt={"node_id": REC, "label": "home_recodings"}),     # pre-4k form, no node
        _row("offtree", gt={"node_id": None, "label": "popup"}),
        _row("unl", gt=None, label_source="none"),
        _row("focusfam", family="focus", gt={"focused": "Apps"}),
        _row("teach", label_source="teacher"),
    ]
    rows[4]["ground_truth"] = None
    picked, skipped = ftp.select_rows(rows)
    assert [r["id"] for r in picked] == ["rec", "teach"]
    assert skipped == Counter()  # non-candidates are not counted


def test_human_set_focus_is_skipped_and_counted(ftp):
    rows = [
        _row("h", label_source="human"),
        _row("resolved", triage={"status": "resolved", "prior_status": "needs_human"}),
        _row("odd", label_source="none"),
        _row("frozen", eval_version="eval-v1"),
        _row("done", triage={"focus_teacher": {"batch_id": "ftp-1"}}),
        _row("ok"),
    ]
    picked, skipped = ftp.select_rows(rows)
    assert [r["id"] for r in picked] == ["ok"]
    assert skipped == Counter({"human_label": 1, "human_resolved": 1, "unsure:none": 1, "frozen": 1, "focus_done": 1})
    picked, _ = ftp.select_rows(rows, include_done=True)
    assert [r["id"] for r in picked] == ["done", "ok"]


def test_userinterface_and_limit(ftp):
    rows = [_row("a"), _row("b"), _row("w", userinterface="web_tv")]
    assert [r["id"] for r in ftp.select_rows(rows, userinterface="stb_tv", limit=1)[0]] == ["a"]


def test_export_is_blind_and_names_the_screen(ftp, tmp_path):
    rows = [_row("rec"),
            _row("dis", gt=_gt(group=APPS, glabel="apps", node=DISNEY, nlabel="apps_disney", focus="disney"),
                 node_id=DISNEY)]
    out, raw, lines, key = _export(ftp, tmp_path, rows)
    for line in lines:
        assert set(line) == set(ftp.BLIND_KEYS)
        assert line["family"] == "focus" and line["allowed_answers"] is None
        assert line["answer_schema"]["focused"] == "<text>|null"
    # the old focus, the node and its label never reach the worker
    words = set(re.findall(r"[a-z_]+", raw.lower()))
    for leaked in ("recodings", "home_recodings", "disney", "apps_disney"):
        assert leaked not in words
    for secret in (REC, DISNEY, HOME, APPS, '"node":', '"node_label":', '"focus":'):
        assert secret not in raw
    assert lines[0]["question"].startswith("This is the **Home** screen of a TV app. Which item has the focus")
    assert "nothing is focused" in lines[0]["question"]
    assert lines[1]["question"].startswith("This is the **Apps** screen")
    # the key keeps what the worker must not see
    assert key["kind"] == "focus-text" and key["blind"] is True
    assert key["samples"]["rec"]["previous_focus"] == "recodings"
    assert key["samples"]["rec"]["family"] == "focus" and key["samples"]["rec"]["row_family"] == "screen-id"
    assert (out / "images" / "rec.jpg").is_file()
    text = (out / "INSTRUCTIONS.md").read_text(encoding="utf-8")
    assert "never read `key.json`" in text and "visible text, exactly as shown" in text
    # no real on-screen answer is primed as an example (batch or instructions)
    for primed in ("Aufnahmen", "Disney+", "HBO Max"):
        assert primed not in raw and primed not in text


def test_export_dry_run_counts_by_group(ftp, capsys):
    rows = [_row("a"), _row("b"), _row("h", label_source="human"),
            _row("d", gt=_gt(group=APPS, glabel="apps", node=DISNEY, nlabel="apps_disney", focus="disney"))]
    args = ftp.build_arg_parser().parse_args(["export", "--team", TEAM, "--dry-run"])
    assert ftp.run_export(args, list_fn=_list_fn(rows)) == 0
    report = json.loads(capsys.readouterr().out)
    assert report == {"would_select": 3, "by_group": {"stb_tv/home": 2, "stb_tv/apps": 1},
                      "skipped": {"human_label": 1}}


def test_screen_name(ftp):
    assert ftp.screen_name(_row("x", gt=_gt(glabel="settings_system"))) == "Settings system"


# ---- import -----------------------------------------------------------------------------------

def _key(rows):
    return {"kind": "focus-text", "batch_id": "ftp-test", "team_id": TEAM, "family": "focus",
            "samples": {r["id"]: {"family": "focus", "row_family": "screen-id", "label_source": r["label_source"],
                                  "ground_truth": r["ground_truth"], "previous_focus": r["ground_truth"].get("focus"),
                                  "userinterface": r["userinterface"]} for r in rows}}


def _answers(*objs):
    return [json.dumps(o) for o in objs]


def test_import_validation(ftp, tb):
    key = _key([_row("a"), _row("b"), _row("c"), _row("d")])
    accepted, rejected = tb.parse_answers(_answers(
        {"id": "a", "answer": {"focused": " Aufnahmen "}, "confidence": "high"},
        {"id": "b", "answer": {"focused": None}, "confidence": "high"},
        {"id": "c", "answer": {"label": "home"}, "confidence": "high"},          # a screen answer
        {"id": "d", "answer": {"focused": ""}, "confidence": "high"},
        {"id": "a", "answer": {"focused": "x"}, "confidence": "high"},           # duplicate
        {"id": "zz", "answer": {"focused": "x"}, "confidence": "high"},          # not in batch
    ) + ["not json"], key)
    assert accepted["a"]["label"] == {"focused": "Aufnahmen"}
    assert accepted["b"]["label"] == {"focused": None}
    reasons = {r["id"]: r["reason"] for r in rejected}
    assert set(reasons) == {"c", "d", "a", "zz", None}


def test_focus_update_leaves_the_screen_label_untouched(ftp):
    row = _row("a", triage={"status": "agreed", "teacher_model": "claude-sonnet-5"})
    accepted = {"a": {"label": {"focused": "Aufnahmen"}, "answer": {"focused": "Aufnahmen"},
                      "confidence": "high", "note": None}}
    decisions, skipped = ftp.plan(_key([row]), accepted, {"a": row}, "claude-sonnet-5", "NOW")
    d = decisions[0]
    assert d["ground_truth"] == {**_gt(), "focus": "Aufnahmen"}
    assert d["outcome"] == "changed" and not d["low"]
    # status / reason / teacher fields of the 4i triage stay; focus_teacher is added
    assert d["triage"]["status"] == "agreed" and d["triage"]["teacher_model"] == "claude-sonnet-5"
    assert d["triage"]["focus_teacher"] == {"model": "claude-sonnet-5", "answer": {"focused": "Aufnahmen"},
                                            "confidence": "high", "note": None, "batch_id": "ftp-test",
                                            "previous_focus": "recodings", "triaged_at": "NOW"}
    assert skipped == Counter()


def test_outcomes_same_changed_nothing(ftp):
    rows = [_row("dis", gt=_gt(focus="disney")), _row("hbo", gt=_gt(focus="hbomax")),
            _row("rec"), _row("none")]
    acc = lambda text: {"label": {"focused": text}, "answer": {"focused": text}, "confidence": "high", "note": None}
    accepted = {"dis": acc("Disney+"), "hbo": acc("HBO Max"), "rec": acc("Aufnahmen"), "none": acc(None)}
    decisions, _ = ftp.plan(_key(rows), accepted, {r["id"]: r for r in rows}, "m", "NOW")
    by = {d["id"]: d for d in decisions}
    assert by["dis"]["outcome"] == "same" and by["hbo"]["outcome"] == "same"
    assert by["rec"]["outcome"] == "changed"
    assert by["none"]["outcome"] == "nothing_focused" and by["none"]["ground_truth"]["focus"] is None
    s = ftp.summarize(_key(rows), decisions, [], accepted, Counter())
    assert (s["updated"], s["changed"], s["same"], s["nothing_focused"], s["low_confidence"]) == (4, 1, 2, 1, 0)


def test_never_overwrites_human_or_frozen_or_changed(ftp):
    rows = [_row("h"), _row("r"), _row("f"), _row("c"), _row("gone")]
    key = _key(rows)
    now = {"h": _row("h", label_source="human"), "r": _row("r", triage={"status": "resolved"}),
           "f": _row("f", eval_version="eval-v1"), "c": _row("c", gt=_gt(focus="Aufnahmen")), "gone": None}
    acc = {sid: {"label": {"focused": "X"}, "answer": {"focused": "X"}, "confidence": "high", "note": None}
           for sid in now}
    decisions, skipped = ftp.plan(key, acc, now, "m", "NOW")
    assert all(d["action"] == "skip" for d in decisions)
    assert skipped == Counter({"human_label": 1, "human_resolved": 1, "frozen": 1,
                               "changed_since_export": 1, "row_missing": 1})


def test_low_confidence_goes_to_needs_human(ftp):
    ft = {"model": "m"}
    # no triage yet, or a final status: flipped, previous status kept in focus_teacher
    rec = ftp.new_triage(None, ft, low=True)
    assert rec["status"] == "needs_human" and rec["reason"] == "focus_low_confidence"
    assert rec["focus_teacher"]["previous_status"] is None
    rec = ftp.new_triage({"status": "agreed", "reason": None}, ft, low=True)
    assert (rec["status"], rec["reason"], rec["focus_teacher"]["previous_status"]) == \
        ("needs_human", "focus_low_confidence", "agreed")
    # already needs_human for another reason: the reason stays, focus_low_confidence is appended
    rec = ftp.new_triage({"status": "needs_human", "reason": "conflict"}, ft, low=True)
    assert rec["reason"] == "conflict" and rec["reasons"] == ["conflict", "focus_low_confidence"]
    assert "previous_status" not in rec["focus_teacher"]
    # high confidence: status untouched, a triage-less row gets focus_teacher only
    assert ftp.new_triage(None, ft, low=False) == {"focus_teacher": ft}
    assert ftp.new_triage({"status": "teacher_only", "reason": "no_independent_label"}, ft, low=False)["status"] \
        == "teacher_only"


def test_low_confidence_keeps_the_new_text(ftp):
    row = _row("a")
    accepted = {"a": {"label": {"focused": "Aufnahmen"}, "answer": {"focused": "Aufnahmen"},
                      "confidence": "low", "note": "blurry"}}
    decisions, _ = ftp.plan(_key([row]), accepted, {"a": row}, "m", "NOW")
    assert decisions[0]["ground_truth"]["focus"] == "Aufnahmen"
    assert decisions[0]["triage"]["status"] == "needs_human" and decisions[0]["low"]


# ---- write through the label path -------------------------------------------------------------

@pytest.fixture
def fake_db(monkeypatch):
    monkeypatch.setattr(samples_db, "get_group", lambda *a, **k: [])
    monkeypatch.setattr(samples_db, "get_labelled_hashes", lambda *a, **k: [])
    monkeypatch.setattr(samples_db, "set_label_conflict", lambda *a, **k: 0)


def test_apply_keeps_label_source_is_failure_and_conflict(ftp, fake_db):
    row = _row("a", model_answer={"content": json.dumps({"node_id": HOME, "label": "home"})})
    accepted = {"a": {"label": {"focused": "Aufnahmen"}, "answer": {"focused": "Aufnahmen"},
                      "confidence": "high", "note": None}}
    decisions, skipped = ftp.plan(_key([row]), accepted, {"a": row}, "m", "NOW")
    writes = []

    def write_fn(team_id, sid, fields, label_source):
        writes.append((team_id, sid, fields, label_source))
        return True
    ftp.apply(TEAM, decisions, label_write.apply_label, write_fn, skipped)
    assert len(writes) == 1
    team_id, sid, fields, source = writes[0]
    assert (team_id, sid, source) == (TEAM, "a", "run")      # guarded on the source as read
    assert "label_source" not in fields                        # never rewritten
    assert fields["ground_truth"] == {**_gt(), "focus": "Aufnahmen"}
    assert fields["is_failure"] is False and fields["label_conflict"] is False
    assert fields["triage"]["focus_teacher"]["previous_focus"] == "recodings"


def test_apply_refused_on_human_row(ftp, fake_db):
    d = {"id": "h", "action": "write", "row": _row("h", label_source="human"), "ground_truth": _gt(focus="X"),
         "triage": {}, "low": False, "outcome": "changed"}
    skipped = Counter()
    ftp.apply(TEAM, [d], label_write.apply_label, lambda *a: pytest.fail("must not write"), skipped)
    assert d["skip"] == "refused:human" and skipped["refused:human"] == 1


def test_real_import_refusals(ftp, tmp_path):
    folder = tmp_path / "b"
    folder.mkdir()
    (folder / "key.json").write_text(json.dumps({**_key([_row("a")]), "kind": None}), encoding="utf-8")
    (folder / "answers.jsonl").write_text("", encoding="utf-8")
    args = ftp.build_arg_parser().parse_args(["import", "--team", TEAM, "--in", str(folder)])
    with pytest.raises(ftp.FocusPassError, match="not a focus-text batch"):
        ftp.run_import(args, get_fn=lambda sid, t: None)
    (folder / "key.json").write_text(json.dumps(_key([_row("a")])), encoding="utf-8")
    with pytest.raises(ftp.FocusPassError, match="triage column is missing"):
        ftp.run_import(args, get_fn=lambda sid, t: None, column_fn=lambda: False, opted_in_fn=lambda t: True,
                       apply_fn=lambda *a, **k: pytest.fail("no write"))
    with pytest.raises(ftp.FocusPassError, match="opted in"):
        ftp.run_import(args, get_fn=lambda sid, t: None, column_fn=lambda: True, opted_in_fn=lambda t: False,
                       apply_fn=lambda *a, **k: pytest.fail("no write"))


def test_import_dry_run_end_to_end(ftp, tmp_path, capsys):
    rows = [_row("a"), _row("b", label_source="human")]
    folder = tmp_path / "b"
    folder.mkdir()
    (folder / "key.json").write_text(json.dumps(_key(rows)), encoding="utf-8")
    (folder / "answers.jsonl").write_text("\n".join(_answers(
        {"id": "a", "answer": {"focused": "Aufnahmen"}, "confidence": "low"},
        {"id": "b", "answer": {"focused": "Aufnahmen"}, "confidence": "high"})), encoding="utf-8")
    args = ftp.build_arg_parser().parse_args(["import", "--team", TEAM, "--in", str(folder), "--dry-run"])
    assert ftp.run_import(args, get_fn=lambda sid, t: {r["id"]: r for r in rows}[sid],
                          apply_fn=lambda *a, **k: pytest.fail("dry run writes nothing")) == 0
    text = capsys.readouterr().out
    assert "'recodings' -> 'Aufnahmen'  changed  LOW -> needs_human" in text
    assert "updated 1: focus changed 1, same 0, nothing focused 0; low confidence (-> needs_human) 1" in text
    assert "skipped/human_label: 1" in text


# ---- step 4i interaction ------------------------------------------------------------------------

def test_focus_teacher_only_record_is_not_a_triage(tb):
    row = _row("a", triage={"focus_teacher": {"batch_id": "ftp-1"}})
    picked, skipped = tb.select_rows([row], "screen-id")
    assert [r["id"] for r in picked] == ["a"] and "already_triaged" not in skipped
    sample = {"label_source": "run", "ground_truth": row["ground_truth"]}
    assert tb.skip_reason(sample, row) is None
    assert tb.skip_reason(sample, _row("a", triage={"status": "agreed"})) == "already_triaged"


def test_triage_import_keeps_focus_teacher(tb):
    row = _row("a", triage={"focus_teacher": {"batch_id": "ftp-1"}})
    key = {"batch_id": "tri-x", "samples": {"a": {"family": "screen-id", "label_source": "run",
                                                  "ground_truth": row["ground_truth"],
                                                  "run_label": row["ground_truth"]}}}
    accepted = {"a": {"label": {"node_id": HOME, "label": "home"}, "answer": {"label": "home"},
                      "confidence": "high", "note": None}}
    decisions, _ = tb.plan(key, accepted, {"a": row}, lambda r, label: False, "m", 0, "NOW")
    assert decisions[0]["triage"]["status"] == "agreed"
    assert decisions[0]["triage"]["focus_teacher"] == {"batch_id": "ftp-1"}


def test_focus_low_confidence_is_a_known_reason():
    assert "focus_low_confidence" in triage_db.TRIAGE_REASONS
    row = {"triage": {"status": "needs_human", "reason": "focus_low_confidence"}, "created_at": "1"}
    assert triage_db.needs_human_reason(row) == "focus_low_confidence"
    ordered = triage_db.order_needs_human([
        {"triage": {"status": "needs_human", "reason": "spot_check"}, "created_at": "2"}, row])
    assert ordered[0] is row
