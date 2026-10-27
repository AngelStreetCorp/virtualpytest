"""ai-dataset feature: step 4i AI triage (TASK-27).

``scripts/triage_batch.py`` export/import, ``lib/label_write.apply_label`` (the shared
label path), the "Needs you" list filter, the resolve-on-human-answer, the two freeze
options (``eval-v1`` human only, ``eval-v0-ai`` human + AI-agreed) and the mixed-label
marking of ``score_eval.py``.

Pure: every DB, storage and tree call is a fake. No network, DB or bucket is touched.

Run: pytest tests/backend_server/test_ai_dataset_triage.py -v
"""
import importlib
import importlib.util
import json
import os
import sys
import types

import pytest
from flask import Flask, request

_TEST_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.normpath(os.path.join(_TEST_DIR, "..", ".."))
sys.path.insert(0, _REPO_ROOT)

from shared.src.lib.ai import training_samples  # noqa: E402
from shared.src.lib.database import ai_training_samples_db as samples_db  # noqa: E402
from shared.src.lib.utils import cloudflare_utils  # noqa: E402

routes = importlib.import_module("features.ai-dataset.backend_server.server_training_samples_routes")  # noqa: E402
triage_db = importlib.import_module("features.ai-dataset.lib.triage_db")  # noqa: E402
label_write = importlib.import_module("features.ai-dataset.lib.label_write")  # noqa: E402

pytestmark = pytest.mark.unit

TEAM = "7fdeb4bb-3639-4ec3-959f-b54769a219ce"
HASH = "0f" * 32   # informative (128 set bits): step 4j never compares a low-information hash
FAR_HASH = "f" * 64
HOME = "6b0e0f7a-1111-4a4a-9a9a-000000000001"
LIVE = "6b0e0f7a-1111-4a4a-9a9a-000000000002"
SCREENS = [{"node_id": HOME, "label": "home"}, {"node_id": LIVE, "label": "live"}]


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, os.path.join(_REPO_ROOT, *rel.split("/")))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def tb():
    return _load("triage_batch_under_test", "features/ai-dataset/scripts/triage_batch.py")


def _row(sid, family="screen-id", **kw):
    row = {"id": sid, "team_id": TEAM, "family": family, "object_key": f"{TEAM}/{family}/stb/{sid}.jpg",
           "dhash": HASH, "device_model": "stb", "userinterface": "stb-testop", "node_id": None,
           "focus_label": None, "model_answer": None, "ground_truth": None, "label_source": "none",
           "is_failure": False, "label_conflict": False, "split": "train", "eval_version": None,
           "source_ref": None, "created_at": "2026-09-30T10:00:00Z"}
    row.update(kw)
    return row


def _run_row(sid, node=HOME, label="home", **kw):
    return _row(sid, node_id=node, ground_truth={"node_id": node, "label": label}, label_source="run",
                source_ref={"reference": "navigation", "node_id": node}, **kw)


def _failed_row(sid, **kw):
    return _row(sid, model_answer={"expected_node_id": LIVE, "expected_label": "live", "verified": False}, **kw)


# ---- export -----------------------------------------------------------------------------------

class FakeStorage:
    def __init__(self, missing=()):
        self.missing = set(missing)
        self.calls = []

    def download_file(self, key, local):
        self.calls.append(key)
        if any(m in key for m in self.missing):
            return {"success": False, "error": "not found"}
        os.makedirs(os.path.dirname(local), exist_ok=True)
        with open(local, "wb") as fh:
            fh.write(b"\xff\xd8jpeg")
        return {"success": True}


def _prompts():
    mod = types.ModuleType("family_prompts_stub")
    mod.build_prompt = lambda family, row, context=None: (
        f"Which screen? {', '.join(context['screen_labels'])}" if family == "screen-id" else f"Q[{family}]")
    return mod


def _list_fn(rows):
    def fn(team_id, family=None, split=None, label_sources=None, limit=50, offset=0, **_kw):
        assert team_id == TEAM and label_sources == ["none", "run"]
        out = [r for r in rows if r["family"] == family and (split is None or r["split"] == split)
               and r["label_source"] in label_sources]
        return out[offset:offset + limit], len(out)
    return fn


def _export(tb, tmp_path, rows, *extra, storage=None):
    out = tmp_path / "tri"
    args = tb.build_arg_parser().parse_args(["export", "--team", TEAM, "--family", rows[0]["family"] if rows else "screen-id",
                                             "--out", str(out), *extra])
    rc = tb.run_export(args, list_fn=_list_fn(rows), screen_fn=lambda t, ui: SCREENS if ui == "stb-testop" else None,
                       storage=storage or FakeStorage(), prompts=_prompts())
    assert rc == 0
    lines = [json.loads(line) for line in (out / "batch.jsonl").read_text(encoding="utf-8").splitlines()]
    key = json.loads((out / "key.json").read_text(encoding="utf-8"))
    return out, lines, key


def test_blind_export_never_leaks_the_run_label(tb, tmp_path):
    rows = [_run_row("r1"), _failed_row("f1"), _row("u1")]
    out, lines, key = _export(tb, tmp_path, rows)
    for line in lines:
        assert set(line) == set(tb.BLIND_KEYS)  # a whitelist: nothing else, ever
        text = json.dumps(line)
        # neither the run label's node id, nor the failed verification's expected screen,
        # nor the source pointer reaches the line the AI sees
        assert HOME not in text and LIVE not in text
        assert "expected" not in text and "verified" not in text and "navigation" not in text
    assert key["samples"]["r1"]["run_label"] == {"node_id": HOME, "label": "home"}
    assert key["samples"]["f1"]["model_answer"]["expected_label"] == "live"
    assert key["blind"] is True
    assert key["screen_labels"]["stb-testop"] == SCREENS


def test_no_blind_adds_run_label_only(tb, tmp_path):
    _out, lines, _key = _export(tb, tmp_path, [_run_row("r1")], "--no-blind")
    assert set(lines[0]) == set(tb.BLIND_KEYS) | {"run_label"}
    assert lines[0]["run_label"] == {"node_id": HOME, "label": "home"}


def test_export_order_and_exclusions(tb, tmp_path):
    rows = [
        _run_row("run1"),
        _row("human1", label_source="human", ground_truth={"node_id": HOME, "label": "home"}),
        _row("teacher1", label_source="teacher", ground_truth={"node_id": HOME, "label": "home"}),
        _run_row("frozen1", split="eval", eval_version="eval-v1"),
        _row("unl1"),
        _failed_row("fail1"),
        _run_row("tri1", triage={"status": "agreed"}),
        _row("otherui", userinterface="web_tv"),
    ]
    _out, lines, key = _export(tb, tmp_path, rows)
    ids = [line["id"] for line in lines]
    assert ids == ["fail1", "unl1", "run1"]  # failed verification, unlabelled, run
    for never in ("human1", "teacher1", "frozen1", "tri1"):
        assert never not in ids and never not in key["samples"]
    assert "otherui" not in ids  # its userinterface has no tree screens


def test_export_include_triaged_limit_and_userinterface(tb, tmp_path):
    rows = [_run_row("tri1", triage={"status": "agreed"}), _row("u1"), _row("u2"), _row("w1", userinterface="web_tv")]
    _out, lines, _key = _export(tb, tmp_path, rows, "--include-triaged", "--limit", "2", "--userinterface", "stb-testop")
    assert [line["id"] for line in lines] == ["u1", "u2"]


def test_export_writes_images_questions_and_instructions(tb, tmp_path):
    storage = FakeStorage(missing=("gone",))
    out, lines, key = _export(tb, tmp_path, [_row("u1"), _row("gone")], storage=storage)
    assert [line["id"] for line in lines] == ["u1"]
    assert (out / "images" / "u1.jpg").is_file()
    assert lines[0]["image"] == "images/u1.jpg"
    assert lines[0]["question"] == "Which screen? home, live"
    assert lines[0]["allowed_answers"] == ["home", "live"]
    assert "label" in lines[0]["answer_schema"]["shape"]
    text = (out / "INSTRUCTIONS.md").read_text(encoding="utf-8")
    assert "answers.jsonl" in text and "Read" in text and '"confidence": "low"' in text
    assert "never read `key.json`" in text


def test_strip_allowed_answers_are_the_three_step_4g_answers(tb):
    strip = _row("s1", family="av-fault", model_answer={"incident_type": "freeze", "evidence": "strip"})
    assert tb.allowed_answers(strip) == [
        {"incident_type": "freeze"},
        {"incident_type": None, "static_screen": True},
        {"incident_type": None, "static_screen": False},
    ]
    frame = _row("b1", family="av-fault", model_answer={"incident_type": "blackscreen"})
    assert {"incident_type": None} in tb.allowed_answers(frame)


# ---- import: validation -----------------------------------------------------------------------

def _key(samples, family="screen-id"):
    return {"batch_id": "tri-test", "team_id": TEAM, "family": family,
            "screen_labels": {"stb-testop": SCREENS}, "samples": samples}


def _ks(row):
    from_row = {"family": row["family"], "label_source": row["label_source"],
                "run_label": row["ground_truth"] if row["label_source"] == "run" else None,
                "ground_truth": row["ground_truth"], "userinterface": row.get("userinterface"),
                "strip": (row.get("model_answer") or {}).get("evidence") == "strip"}
    return from_row


def _line(sid, answer, confidence="high", **kw):
    return json.dumps({"id": sid, "answer": answer, "confidence": confidence, **kw})


def test_screen_name_maps_to_node_id_and_off_tree_is_lowercased(tb):
    key = _key({"a": _ks(_row("a")), "b": _ks(_row("b"))})
    accepted, rejected = tb.parse_answers([_line("a", {"label": "Home"}),
                                           _line("b", {"node_id": None, "label": " Popup "})], key)
    assert rejected == []
    assert accepted["a"]["label"] == {"node_id": HOME, "label": "home"}
    assert accepted["b"]["label"] == {"node_id": None, "label": "popup"}


def test_malformed_answers_are_rejected_and_listed(tb):
    strip = _row("s", family="av-fault", model_answer={"evidence": "strip"})
    key = _key({"a": _ks(_row("a")), "b": _ks(_row("b")), "c": _ks(_row("c")), "d": _ks(_row("d")),
                "e": _ks(_row("e")), "s": _ks(strip), "z": _ks(_row("z", family="banner", userinterface=None)),
                "q": _ks(_row("q", family="av-fault"))})
    lines = [
        "not json",
        _line("nope", {"label": "home"}),                        # not in the batch
        _line("a", {"label": "settings"}),                       # not in allowed_answers
        _line("b", {"node_id": HOME, "label": "home"}),          # node ids are never guessed
        _line("c", {"label": "home"}, confidence="medium"),      # bad confidence
        _line("d", "home"),                                      # not an object
        _line("e", {"label": "home"}, extra=1),                  # unknown key
        _line("s", {"incident_type": None}),                     # strip needs one of the three
        _line("z", {"channel_number": "101", "programme": "x"}),  # outside the banner schema
        _line("q", {"incident_type": "audio_loss"}),             # not a visual fault
        _line("q", {"incident_type": None}),                     # fine
        _line("q", {"incident_type": "freeze"}),                 # duplicate id
    ]
    accepted, rejected = tb.parse_answers(lines, key)
    assert list(accepted) == ["q"] and accepted["q"]["label"] == {"incident_type": None}
    by_line = {r["line"]: r for r in rejected}
    assert set(by_line) == {1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12}
    assert "not in allowed_answers" in by_line[3]["reason"]
    assert "duplicate" in by_line[12]["reason"]


def test_strip_answers_keep_static_screen(tb):
    strip = _row("s", family="av-fault", model_answer={"evidence": "strip"})
    accepted, rejected = tb.parse_answers([_line("s", {"incident_type": None, "static_screen": True})],
                                          _key({"s": _ks(strip)}, family="av-fault"))
    assert rejected == [] and accepted["s"]["label"] == {"incident_type": None, "static_screen": True}


# ---- import: decisions ----------------------------------------------------------------------

def _plan(tb, rows, answers, conflict=lambda row, label: False, pct=0):
    key = _key({r["id"]: _ks(r) for r in rows}, family=rows[0]["family"])
    accepted, rejected = tb.parse_answers(answers, key)
    assert rejected == []
    db = {r["id"]: dict(r) for r in rows}
    decisions, skipped = tb.plan(key, accepted, db, conflict, "claude-sonnet-5", pct, "2026-09-30T12:00:00+00:00")
    return {d["id"]: d for d in decisions}, skipped


def test_each_triage_branch(tb):
    rows = [_run_row("agree"), _run_row("disagree"), _run_row("pair"), _run_row("unsure"),
            _run_row("stale", label_conflict=True),
            _row("teach"), _row("teach_low"), _row("teach_pair")]
    answers = [_line("agree", {"label": "home"}), _line("disagree", {"label": "live"}),
               _line("pair", {"label": "home"}), _line("unsure", {"label": "home"}, confidence="low"),
               _line("stale", {"label": "home"}),
               _line("teach", {"label": "live"}), _line("teach_low", {"label": "live"}, confidence="low"),
               _line("teach_pair", {"label": "live"})]
    seen = {}

    def conflict(row, label):
        seen[row["id"]] = label
        return row["id"] in ("pair", "teach_pair")
    d, _ = _plan(tb, rows, answers, conflict=conflict)
    assert (d["agree"]["action"], d["agree"]["status"]) == ("triage", "agreed")
    # step 4j: the live check decides, not the stored (possibly stale) label_conflict flag
    assert (d["stale"]["action"], d["stale"]["status"]) == ("triage", "agreed")
    # a run row is checked with its own current label, a teacher row with the teacher label
    assert seen["pair"] == {"node_id": HOME, "label": "home"}
    assert seen["teach_pair"] == {"node_id": LIVE, "label": "live"}
    assert (d["disagree"]["action"], d["disagree"]["status"], d["disagree"]["reason"]) == \
        ("triage", "needs_human", "disagrees_with_run")
    assert d["pair"]["reason"] == "conflict" and d["unsure"]["reason"] == "low_confidence"
    assert (d["teach"]["action"], d["teach"]["status"], d["teach"]["reason"]) == \
        ("apply", "teacher_only", "no_independent_label")
    assert (d["teach_low"]["action"], d["teach_low"]["reason"]) == ("apply", "low_confidence")
    assert (d["teach_pair"]["action"], d["teach_pair"]["reason"]) == ("apply", "conflict")
    record = d["agree"]["triage"]
    assert record["teacher_model"] == "claude-sonnet-5" and record["teacher_confidence"] == "high"
    assert record["teacher_answer"] == {"label": "home"}
    assert record["teacher_label"] == {"node_id": HOME, "label": "home"}
    assert record["run_label_agreed"] is True and d["disagree"]["triage"]["run_label_agreed"] is False


def test_banner_agreement_uses_the_numeric_zap_run_label(tb):
    run = _row("z", family="banner", userinterface=None, label_source="run", ground_truth={"channel_number": "101"})
    d, _ = _plan(tb, [run], [_line("z", {"channel_number": "101", "channel_name": "BBC One"})])
    assert d["z"]["status"] == "agreed"


def test_human_frozen_changed_and_triaged_rows_are_skipped(tb):
    rows = [_row("h"), _row("f"), _row("c"), _row("t")]
    key = _key({r["id"]: _ks(r) for r in rows})
    accepted, _ = tb.parse_answers([_line(r["id"], {"label": "home"}) for r in rows], key)
    db = {"h": _row("h", label_source="human", ground_truth={"node_id": LIVE, "label": "live"}),
          "f": _row("f", eval_version="eval-v1"),
          "c": _row("c", label_source="run", ground_truth={"node_id": LIVE, "label": "live"}),
          "t": _row("t", triage={"status": "needs_human"})}
    decisions, skipped = tb.plan(key, accepted, db, lambda r, label: False, "m", 0, "now")
    assert {d["id"]: d["skip"] for d in decisions} == {
        "h": "human_label", "f": "frozen", "c": "changed_since_export", "t": "already_triaged"}
    assert all(d["action"] == "skip" for d in decisions)


def test_spot_check_is_deterministic_and_exact(tb):
    ids = [f"id{i:03d}" for i in range(100)]
    first = tb.spot_check_ids(ids, "batch-a", 5)
    assert len(first) == 5
    assert tb.spot_check_ids(list(reversed(ids)), "batch-a", 5) == first
    assert tb.spot_check_ids(ids, "batch-b", 5) != first
    assert tb.spot_check_ids(ids, "batch-a", 0) == []
    assert len(tb.spot_check_ids(ids[:3], "batch-a", 5)) == 1  # at least 5%: ceil
    assert len(tb.spot_check_ids(ids, "batch-a", 12.5)) == 13


def test_spot_check_takes_only_final_ai_labels(tb):
    rows = [_run_row(f"a{i}") for i in range(20)] + [_run_row("dis")]
    answers = [_line(f"a{i}", {"label": "home"}) for i in range(20)] + [_line("dis", {"label": "live"})]
    d, _ = _plan(tb, rows, answers, pct=5)
    spot = [i for i, x in d.items() if x.get("reason") == "spot_check"]
    assert len(spot) == 1 and spot[0] != "dis"
    assert d[spot[0]]["status"] == "needs_human" and d[spot[0]]["triage"]["spot_check_of"] == "agreed"
    again, _ = _plan(tb, rows, answers, pct=5)
    assert [i for i, x in again.items() if x.get("reason") == "spot_check"] == spot


# ---- import: applying ------------------------------------------------------------------------

def _write_batch(tmp_path, rows, answers, family="screen-id", team=TEAM):
    folder = tmp_path / "batch"
    folder.mkdir()
    key = _key({r["id"]: _ks(r) for r in rows}, family=family)
    key["team_id"] = team
    (folder / "key.json").write_text(json.dumps(key), encoding="utf-8")
    (folder / "answers.jsonl").write_text("\n".join(answers) + "\n", encoding="utf-8")
    return folder


def _import_args(tb, folder, *extra):
    return tb.build_arg_parser().parse_args(["import", "--team", TEAM, "--in", str(folder), *extra])


def test_import_applies_through_the_label_path_and_records_triage(tb, tmp_path, capsys):
    rows = [_run_row("agree"), _run_row("disagree"), _row("teach")]
    folder = _write_batch(tmp_path, rows, [_line("agree", {"label": "home"}), _line("disagree", {"label": "live"}),
                                           _line("teach", {"label": "live"})])
    db = {r["id"]: dict(r) for r in rows}
    applied, triaged = [], []

    def apply_fn(team_id, row, label, triage_for):
        applied.append((team_id, row["id"], label, triage_for(False)))
        return {"ok": True, "is_failure": True, "label_conflict": False}

    rc = tb.run_import(_import_args(tb, folder, "--spot-check-pct", "0"), get_fn=lambda sid, t: db.get(sid),
                       conflict_fn=lambda r, label: False, apply_fn=apply_fn,
                       set_triage_fn=lambda t, sid, rec: triaged.append((sid, rec)) or True,
                       column_fn=lambda: True, opted_in_fn=lambda t: True)
    assert rc == 0
    assert [(a[1], a[2]) for a in applied] == [("teach", {"node_id": LIVE, "label": "live"})]
    assert applied[0][3]["status"] == "teacher_only"
    assert {sid: rec["status"] for sid, rec in triaged} == {"agree": "agreed", "disagree": "needs_human"}
    out = capsys.readouterr().out
    assert "needs_human/disagrees_with_run: 1" in out


def test_import_dry_run_writes_nothing(tb, tmp_path, capsys):
    rows = [_row("teach")]
    folder = _write_batch(tmp_path, rows, [_line("teach", {"label": "live"})])

    def boom(*a, **k):
        raise AssertionError("dry run must not write")

    rc = tb.run_import(_import_args(tb, folder, "--dry-run"), get_fn=lambda sid, t: dict(rows[0]),
                       conflict_fn=lambda r, label: False, apply_fn=boom, set_triage_fn=boom,
                       column_fn=boom, opted_in_fn=boom)
    assert rc == 0
    assert "dry run" in capsys.readouterr().out


def test_import_refuses_other_team_missing_column_or_no_opt_in(tb, tmp_path):
    rows = [_row("teach")]
    folder = _write_batch(tmp_path, rows, [_line("teach", {"label": "live"})], team="other-team")
    with pytest.raises(tb.TriageError, match="key.json is for team"):
        tb.run_import(_import_args(tb, folder), get_fn=lambda s, t: None, conflict_fn=lambda r, label: False)
    folder2 = tmp_path / "b2"
    folder2.mkdir()
    for name in ("key.json", "answers.jsonl"):
        (folder2 / name).write_text((folder / name).read_text(encoding="utf-8").replace("other-team", TEAM), encoding="utf-8")
    common = dict(get_fn=lambda s, t: dict(rows[0]), conflict_fn=lambda r, label: False,
                  apply_fn=lambda *a: {"ok": True}, set_triage_fn=lambda *a: True)
    with pytest.raises(tb.TriageError, match="001_triage.sql"):
        tb.run_import(_import_args(tb, folder2), column_fn=lambda: False, opted_in_fn=lambda t: True, **common)
    with pytest.raises(tb.TriageError, match="opted in"):
        tb.run_import(_import_args(tb, folder2), column_fn=lambda: True, opted_in_fn=lambda t: False, **common)


def test_conflict_found_at_write_time_or_after_the_batch_goes_to_the_human(tb):
    decisions = [
        {"id": "w", "family": "screen-id", "action": "apply", "status": "teacher_only", "reason": "no_independent_label",
         "label": {"node_id": HOME, "label": "home"}, "row": _row("w"),
         "triage": {"status": "teacher_only", "reason": "no_independent_label"}},
        {"id": "s", "family": "screen-id", "action": "triage", "status": "agreed", "reason": None,
         "triage": {"status": "agreed", "reason": None}},
    ]
    written = []

    def apply_fn(team_id, row, label, triage_for):
        written.append(triage_for(True))  # the write's own check found a conflict
        return {"ok": True}

    sets = []
    tb._apply(TEAM, decisions, apply_fn, lambda t, sid, rec: sets.append((sid, rec)) or True,
              lambda sid, t: {"id": sid, "label_conflict": False, "ground_truth": {"node_id": HOME}},
              __import__("collections").Counter(), lambda row, label: row["id"] == "s")
    assert written[0]["status"] == "needs_human" and written[0]["reason"] == "conflict"
    assert decisions[0]["reason"] == "conflict"
    assert decisions[1]["status"] == "needs_human" and decisions[1]["reason"] == "conflict"  # the sweep
    assert sets[-1] == ("s", {"status": "needs_human", "reason": "conflict"})


def test_refused_write_is_reported_as_skipped(tb):
    class Refused(Exception):
        reason = "human"

    decisions = [{"id": "w", "family": "screen-id", "action": "apply", "status": "teacher_only", "reason": None,
                  "label": {}, "row": _row("w"), "triage": {"status": "teacher_only"}}]
    skipped = __import__("collections").Counter()

    def apply_fn(*a):
        raise Refused("a human labelled it meanwhile")

    tb._apply(TEAM, decisions, apply_fn, lambda *a: True, lambda sid, t: None, skipped, lambda r, label: False)
    assert decisions[0]["skip"] == "refused:human" and skipped["refused:human"] == 1


# ---- the shared label path (lib/label_write.py) -----------------------------------------------

@pytest.fixture
def fake_db(monkeypatch):
    state = {"rows": {}, "flagged": []}
    monkeypatch.setattr(samples_db, "get_group", lambda *a, **k: [])
    monkeypatch.setattr(samples_db, "get_labelled_hashes", lambda team_id, family, model, limit=2000: [
        (r["id"], r["dhash"], r["ground_truth"]) for r in state["rows"].values()
        if r["family"] == family and r["ground_truth"] is not None])
    monkeypatch.setattr(samples_db, "set_label_conflict",
                        lambda team_id, ids, value=True: state["flagged"].append((list(ids), value)) or len(ids))
    monkeypatch.setattr(samples_db, "get_sample", lambda sid, team_id: dict(state["rows"][sid]) if sid in state["rows"] else None)
    return state


def test_teacher_label_goes_through_apply_label_with_is_failure_and_conflicts(tb, fake_db):
    fake_db["rows"]["partner"] = _row("partner", ground_truth={"node_id": LIVE, "label": "live"}, label_source="run")
    row = _row("t1", model_answer={"content": '{"node_id": "%s", "label": "home"}' % HOME})
    writes = []

    def writer(sid, team_id, gt, source, is_failure, conflict):
        writes.append((sid, gt, source, is_failure, conflict))
        return True

    result = label_write.apply_label(TEAM, row, {"node_id": HOME, "label": "home"}, "teacher", write=writer)
    assert result == {"ok": True, "is_failure": False, "label_conflict": True}
    assert writes == [("t1", {"node_id": HOME, "label": "home"}, "teacher", False, True)]
    assert fake_db["flagged"] == [(["partner"], True)]  # both sides of the look-alike pair


def test_teacher_label_never_replaces_a_human_one_nor_a_frozen_row(fake_db):
    human = _row("h", label_source="human", ground_truth={"node_id": LIVE, "label": "live"})
    with pytest.raises(label_write.LabelRefused) as e:
        label_write.apply_label(TEAM, human, {"node_id": HOME, "label": "home"}, "teacher", write=lambda *a: True)
    assert e.value.reason == "human"
    with pytest.raises(label_write.LabelRefused) as e:
        label_write.apply_label(TEAM, _row("f", eval_version="eval-v1"), {"node_id": HOME, "label": "home"}, "teacher",
                                write=lambda *a: True)
    assert e.value.reason == "frozen"


def test_teacher_writer_stores_label_and_triage_in_one_guarded_update(monkeypatch):
    calls = []

    class Q:
        def __init__(self):
            self.chain = []

        def __getattr__(self, name):
            def f(*a, **k):
                self.chain.append((name, a))
                return self
            return f

        def execute(self):
            calls.append(self.chain)
            return types.SimpleNamespace(data=[{"id": "x"}])

    monkeypatch.setattr(triage_db, "_table", lambda: Q())
    write = triage_db.teacher_label_writer(lambda conflict: {"status": "needs_human" if conflict else "teacher_only"})
    assert write("x", TEAM, {"node_id": HOME, "label": "home"}, "teacher", True, True) is True
    chain = calls[0]
    update = dict(chain[0][1][0])
    assert update["triage"] == {"status": "needs_human"} and update["label_source"] == "teacher"
    assert ("neq", ("label_source", "human")) in chain and ("is_", ("eval_version", "null")) in chain
    assert ("eq", ("team_id", TEAM)) in chain


class _Chain:
    """Records a supabase query chain; ``execute`` returns ``data``/``count``."""

    def __init__(self, calls, data=None, count=0):
        self.calls, self.chain, self.data, self.count = calls, [], data or [], count

    def __getattr__(self, name):
        def f(*a, **k):
            self.chain.append((name, a))
            return self
        return f

    def execute(self):
        self.calls.append(self.chain)
        return types.SimpleNamespace(data=self.data, count=self.count)


def test_ai_freeze_and_ai_count_exclude_agreed_rows_that_became_confusable(monkeypatch):
    calls = []
    monkeypatch.setattr(triage_db, "_table", lambda: _Chain(calls, data=[{"id": "a"}], count=3))
    assert triage_db.count_ai_freeze_candidates(TEAM, "screen-id") == 3
    assert triage_db.freeze_ai_eval(TEAM, "screen-id", "eval-v0-ai") == 1
    assert triage_db.count_agreed_eval(TEAM, "screen-id") == 3
    ai_filter = ("or_", ("label_source.eq.human,and(triage->>status.eq.agreed,label_conflict.is.false)",))
    for chain in calls[:2]:
        assert ai_filter in chain
        assert ("eq", ("team_id", TEAM)) in chain and ("eq", ("split", "eval")) in chain
        assert ("is_", ("eval_version", "null")) in chain
    assert ("update", ({"eval_version": "eval-v0-ai"},)) in calls[1]
    assert ("eq", ("label_conflict", False)) in calls[2] and ("eq", ("triage->>status", "agreed")) in calls[2]


def test_needs_you_also_lists_agreed_rows_that_became_confusable(monkeypatch):
    calls = []
    rows = [_run_row("late", triage={"status": "agreed"}, label_conflict=True, created_at="2026-09-30T00:00:00Z"),
            _run_row("spot", triage={"status": "needs_human", "reason": "spot_check"}, created_at="2026-09-30T09:00:00Z")]
    monkeypatch.setattr(triage_db, "_table", lambda: _Chain(calls, data=rows))
    page, total = triage_db.list_needs_human(TEAM, family="screen-id")
    assert [r["id"] for r in page] == ["late", "spot"] and total == 2
    assert ("or_", ("triage->>status.eq.needs_human,and(triage->>status.eq.agreed,label_conflict.is.true)",)) in calls[0]
    assert triage_db.needs_human_reason(rows[0]) == "conflict"
    assert triage_db.needs_human_reason(_run_row("ok", triage={"status": "agreed"})) is None


# ---- routes: "Needs you", resolve, freeze options -----------------------------------------------

@pytest.fixture
def api(monkeypatch):
    state = {"rows": {}, "needs_calls": [], "list_calls": [], "resolved": [], "updates": [],
             "human": 0, "agreed": 0, "ai": 0, "frozen": [], "ai_frozen": []}

    def fake_update(sid, team_id, gt, source, is_failure, conflict):
        state["updates"].append((sid, gt, source))
        state["rows"][sid].update(ground_truth=gt, label_source=source)
        return True

    def fake_needs(team_id, family=None, split=None, device_model=None, limit=50, offset=0):
        state["needs_calls"].append(dict(team_id=team_id, family=family, split=split, limit=limit, offset=offset))
        rows = [dict(r) for r in state["rows"].values() if (r.get("triage") or {}).get("status") == "needs_human"]
        return triage_db.order_needs_human(rows)[offset:offset + limit], len(rows)

    def fake_list(team_id, **kw):
        state["list_calls"].append(kw)
        return [dict(r) for r in state["rows"].values()], len(state["rows"])

    monkeypatch.setattr(samples_db, "list_samples", fake_list)
    monkeypatch.setattr(samples_db, "get_sample", lambda sid, t: dict(state["rows"][sid]) if sid in state["rows"] else None)
    monkeypatch.setattr(samples_db, "get_group", lambda *a, **k: [])
    monkeypatch.setattr(samples_db, "get_labelled_hashes", lambda *a, **k: [])
    monkeypatch.setattr(samples_db, "set_label_conflict", lambda *a, **k: 0)
    monkeypatch.setattr(samples_db, "update_label", fake_update)
    monkeypatch.setattr(samples_db, "count_freeze_candidates", lambda t, f: state["human"])
    monkeypatch.setattr(samples_db, "eval_version_exists", lambda t, f, v: False)
    monkeypatch.setattr(samples_db, "freeze_eval", lambda t, f, v: state["frozen"].append(v) or state["human"])
    monkeypatch.setattr(triage_db, "list_needs_human", fake_needs)
    monkeypatch.setattr(triage_db, "resolve_triage", lambda t, sid, rec: state["resolved"].append((sid, rec)) or True)
    monkeypatch.setattr(triage_db, "count_agreed_eval", lambda t, f: state["agreed"])
    monkeypatch.setattr(triage_db, "count_ai_freeze_candidates", lambda t, f: state["ai"])
    monkeypatch.setattr(triage_db, "freeze_ai_eval", lambda t, f, v: state["ai_frozen"].append(v) or state["ai"])
    monkeypatch.setattr(cloudflare_utils, "get_training_storage", lambda: types.SimpleNamespace(
        generate_presigned_url=lambda key, expires_in=3600: {"success": True, "url": f"https://signed/{key}"}))
    monkeypatch.setattr(training_samples, "enabled", lambda: False)

    app = Flask(__name__)

    @app.before_request
    def _principal():
        request.user_role = "admin"

    app.register_blueprint(routes.server_training_samples_bp)
    state["client"] = app.test_client()
    return state


def test_needs_you_filter_lists_triage_rows_spot_checks_last(api):
    api["rows"] = {
        "spot": _run_row("spot", triage={"status": "needs_human", "reason": "spot_check"}, created_at="2026-09-30T12:00:00Z"),
        "dis": _run_row("dis", triage={"status": "needs_human", "reason": "disagrees_with_run"}, created_at="2026-09-29T00:00:00Z"),
        "low": _row("low", triage={"status": "needs_human", "reason": "low_confidence"}),
        "ok": _run_row("ok", triage={"status": "agreed"}),
    }
    resp = api["client"].get(f"/server/training-samples/list?team_id={TEAM}&triage=needs_human&family=screen-id&balance=device_model")
    body = resp.get_json()
    assert resp.status_code == 200
    assert [s["id"] for s in body["samples"]] == ["dis", "low", "spot"]
    assert body["total"] == 3 and api["list_calls"] == []  # the core list is not used
    assert api["needs_calls"][0]["family"] == "screen-id"
    assert body["samples"][0]["triage"]["reason"] == "disagrees_with_run"


def test_needs_you_filter_rejects_unknown_values(api):
    resp = api["client"].get(f"/server/training-samples/list?team_id={TEAM}&triage=agreed")
    assert resp.status_code == 400


def test_list_rows_carry_their_triage(api):
    api["rows"] = {"ok": _run_row("ok", triage=json.dumps({"status": "agreed"})), "none": _run_row("none")}
    body = api["client"].get(f"/server/training-samples/list?team_id={TEAM}").get_json()
    by_id = {s["id"]: s for s in body["samples"]}
    assert by_id["ok"]["triage"] == {"status": "agreed"} and by_id["none"]["triage"] is None


def test_human_answer_resolves_the_triage(api):
    api["rows"]["t"] = _row("t", label_source="teacher", ground_truth={"node_id": LIVE, "label": "live"},
                            triage={"status": "needs_human", "reason": "low_confidence",
                                    "teacher_label": {"node_id": LIVE, "label": "live"}})
    resp = api["client"].post("/server/training-samples/t/label",
                              json={"team_id": TEAM, "ground_truth": {"node_id": HOME, "label": "home"}})
    body = resp.get_json()
    assert resp.status_code == 200 and body["label_source"] == "human"
    assert api["updates"] == [("t", {"node_id": HOME, "label": "home"}, "human")]
    sid, record = api["resolved"][0]
    assert sid == "t" and record["status"] == "resolved"
    assert record["prior_status"] == "needs_human" and record["prior_reason"] == "low_confidence"
    assert record["human_agreed_with_teacher"] is False and record["resolved_at"]
    assert body["triage"]["status"] == "resolved"


def test_human_answer_on_an_untriaged_row_writes_no_triage(api):
    api["rows"]["n"] = _row("n")
    resp = api["client"].post("/server/training-samples/n/label",
                              json={"team_id": TEAM, "ground_truth": {"node_id": HOME, "label": "home"}})
    assert resp.status_code == 200 and api["resolved"] == [] and resp.get_json()["triage"] is None


def _freeze(api, version, **extra):
    return api["client"].post("/server/training-samples/freeze",
                              json={"team_id": TEAM, "family": "screen-id", "version": version, **extra})


def test_freeze_eval_v1_stays_human_only_at_200(api):
    api["human"], api["ai"] = 199, 500
    assert _freeze(api, "eval-v1").status_code == 400
    api["human"] = 200
    resp = _freeze(api, "eval-v1")
    assert resp.status_code == 200 and resp.get_json()["labels"] == "human"
    assert api["frozen"] == ["eval-v1"] and api["ai_frozen"] == []


def test_freeze_eval_v0_ai_takes_human_plus_agreed_with_a_configurable_minimum(api):
    api["ai"] = 49
    resp = _freeze(api, "eval-v0-ai")
    assert resp.status_code == 400 and "50 needed" in resp.get_json()["error"]
    api["ai"] = 30
    resp = _freeze(api, "eval-v0-ai", min_rows=25)
    assert resp.status_code == 200 and resp.get_json()["labels"] == "human+ai"
    assert api["ai_frozen"] == ["eval-v0-ai"] and api["frozen"] == []
    assert _freeze(api, "eval-v0-ai", min_rows=0).status_code == 400
    assert _freeze(api, "eval-v0-ai", min_rows="x").status_code == 400
    assert _freeze(api, "eval-v0-AI").status_code == 400


def test_eval_counts_split_human_and_ai_verified(api):
    api["human"], api["agreed"] = 7, 11
    body = api["client"].get(f"/server/training-samples/eval-counts?team_id={TEAM}").get_json()
    assert body["counts"]["screen-id"] == 7 and body["agreed_counts"]["screen-id"] == 11
    assert body["threshold"] == 200 and body["ai_threshold"] == 50


# ---- score_eval: eval-v0-ai is marked as mixed labels ----------------------------------------

def test_score_eval_marks_eval_v0_ai_as_mixed():
    se = _load("score_eval_triage_test", "features/ai-dataset/scripts/score_eval.py")
    run = {"family": "screen-id", "source": "eval-version", "eval_version": "eval-v0-ai"}
    assert se._row(run) == "screen-id [eval-v0-ai, labels: human+AI (mixed)]"
    assert se._row({**run, "eval_version": "eval-v1"}) == "screen-id [eval-v1]"
    assert se.label_kind("eval-v0-ai") == "human+ai" and se.label_kind("eval-v1") == "human"
    rows = [{"label_source": "human"}, {"label_source": "run", "triage": {"status": "agreed"}},
            {"label_source": "run", "triage": json.dumps({"status": "agreed"})}, {"label_source": "human",
                                                                                   "triage": {"status": "resolved"}}]
    assert se.label_mix(rows) == {"human": 2, "run+ai-agreed": 2}
    summary = {"accuracy": 1.0, "correct": 1, "n": 1, "tokens_in": 0, "tokens_out": 0}
    report = se.render_report([{**run, "profile": "p", "model": "m", "summary": summary, "samples": [],
                                "created_at": "2026-09-30T00:00:00Z"}])
    assert "labels: human+AI (mixed)" in report and "pilot, not a human-verified eval set" in report


# ---- step 4j: the import's conflict branch follows the core rules ---------------------------

LOW_HASH = "0" * 63 + "3"    # 2 set bits: black / colour bars


def _summary_json(out):
    """The --json summary printed after the per-row lines and the table."""
    return json.loads(out[out.index('{\n  "batch_id"'):])


def test_import_dry_run_conflicts_follow_the_step_4j_rules(tb, tmp_path, capsys, fake_db):
    near = format(int(HASH, 16) ^ 0b1, "064x")
    rows = [
        # blank-ish run rows with different labels, flagged under the old rules
        _run_row("bars", node=HOME, label="home", dhash=LOW_HASH, label_conflict=True),
        _run_row("black", node=LIVE, label="live", dhash="0" * 64, label_conflict=True),
        # an informative look-alike pair: still a conflict
        _run_row("real", node=HOME, label="home"),
        _run_row("real_partner", node=LIVE, label="live", dhash=near),
        # a blank teacher row next to a blank labelled row
        _row("teach_blank", dhash="0" * 64),
    ]
    for r in rows:
        fake_db["rows"][r["id"]] = dict(r)
    answers = [_line("bars", {"label": "home"}), _line("black", {"label": "live"}),
               _line("real", {"label": "home"}), _line("real_partner", {"label": "live"}),
               _line("teach_blank", {"label": "home"})]
    folder = _write_batch(tmp_path, rows, answers)
    rc = tb.run_import(_import_args(tb, folder, "--dry-run", "--spot-check-pct", "0", "--json"))
    assert rc == 0
    out = capsys.readouterr().out
    summary = _summary_json(out)
    fam = summary["families"]["screen-id"]
    assert fam["needs_human"] == {"conflict": 2}        # real + real_partner only
    assert fam["agreed"] == 2 and fam["teacher_only"] == 1
    assert fake_db["flagged"] == []                      # dry run: nothing written


def test_import_dry_run_focus_rows_never_conflict(tb, tmp_path, capsys, fake_db):
    near = format(int(HASH, 16) ^ 0b1, "064x")
    labelled = _row("menu_a", family="focus", ground_truth={"focused": "Movies"}, label_source="human")
    fake_db["rows"]["menu_a"] = labelled
    teach = _row("menu_b", family="focus", dhash=near)
    fake_db["rows"]["menu_b"] = dict(teach)
    folder = _write_batch(tmp_path, [teach], [_line("menu_b", {"focused": "Series"})], family="focus")
    rc = tb.run_import(_import_args(tb, folder, "--dry-run", "--spot-check-pct", "0", "--json"))
    assert rc == 0
    out = capsys.readouterr().out
    fam = _summary_json(out)["families"]["focus"]
    assert fam["needs_human"] == {} and fam["teacher_only"] == 1


# ---- step 4k: screen groups and "nothing focused" ------------------------------------------------

def test_focus_answer_may_say_nothing_is_focused(tb):
    label, problem = tb.validate_answer("focus", {}, [], {"focused": None})
    assert problem is None and label == {"focused": None}
    assert tb.answer_schema({"family": "focus"})["nothing_focused"] == {"focused": None}
    text = tb.render_instructions("b1", "focus", 3, "/var/tmp/tri")
    assert '{"focused": null}' in text
    assert tb.validate_answer("focus", {}, [], {"focused": ""})[1]      # empty text is not "nothing"


def test_teacher_naming_the_group_agrees_with_a_grouped_run_label(tb):
    run_label = {"node_id": "n-home", "label": "home", "node": "n-apps", "node_label": "home_apps",
                 "focus": "apps"}
    screens = [{"node_id": "n-home", "label": "home"}, {"node_id": "n-apps-store", "label": "apps"}]
    teacher, problem = tb.validate_answer("screen-id", {}, screens, {"label": "home"})
    assert problem is None and teacher == {"node_id": "n-home", "label": "home"}
    assert tb.decide("screen-id", {"run_label": run_label}, {}, teacher, "high", False) == ("triage", "agreed", None)
    other, _ = tb.validate_answer("screen-id", {}, screens, {"label": "apps"})
    assert tb.decide("screen-id", {"run_label": run_label}, {}, other, "high", False)[2] == "disagrees_with_run"
    # the rules no longer teach that a Home tab is its own screen
    rules = tb.render_instructions("b1", "screen-id", 3, "/var/tmp/tri")
    assert "whichever tab" in rules and "different screen from `settings`" not in rules


def test_screen_list_is_the_groups(tb, monkeypatch):
    class Groups:
        def entries(self):
            return [{"node_id": "n-apps", "label": "apps"}, {"node_id": "n-home", "label": "home"}]
    scope = tb._load_lib("screen_group_scope")
    monkeypatch.setattr(tb, "_load_lib", lambda name: scope if name == "screen_group_scope" else None)
    monkeypatch.setattr(scope, "groups_for", lambda team, ui: Groups() if ui == "stb-testop" else None)
    assert tb.tree_screen_labels("t", "stb-testop") == [{"node_id": "n-apps", "label": "apps"},
                                                    {"node_id": "n-home", "label": "home"}]
    assert tb.tree_screen_labels("t", "nope") is None


# ---- second pass (2026-10-01: the human only when really necessary) -------------------------

def _nh(reason, **triage):
    return {"status": "needs_human", "reason": reason, "teacher_model": "claude-sonnet-5",
            "teacher_label": {"node_id": LIVE, "label": "live"}, "teacher_confidence": "low",
            "batch_id": "tri-first", "triaged_at": "2026-10-01T10:00:00+00:00", **triage}


def _teacher_row(sid, label="live", node=LIVE, **kw):
    return _row(sid, ground_truth={"node_id": node, "label": label}, label_source="teacher", **kw)


def test_second_pass_export_takes_only_rows_the_ai_could_not_settle(tb, tmp_path):
    rows = [
        _run_row("open-run"),                                                  # never triaged
        _row("open-none"),                                                     # never triaged
        _teacher_row("low", triage=_nh("low_confidence")),
        _run_row("disagree", triage=_nh("disagrees_with_run")),
        _teacher_row("pair", triage=_nh("conflict")),
        _teacher_row("spot", triage=_nh("spot_check")),                       # the human's audit
        _run_row("focus", triage=_nh("focus_low_confidence")),                # step 4l, its own pass
        _run_row("agreed", triage={"status": "agreed"}),
        _teacher_row("teacher", triage={"status": "teacher_only"}),
        _teacher_row("excl", triage={"status": "excluded", "reason": "low_confidence"}),
        _row("human", ground_truth={"node_id": HOME, "label": "home"}, label_source="human"),
        _teacher_row("frozen", triage=_nh("low_confidence"), eval_version="eval-v0-ai"),
    ]
    seen_sources = []

    def list_fn(team_id, family=None, split=None, label_sources=None, limit=50, offset=0, **_kw):
        seen_sources.append(tuple(label_sources))
        out = [r for r in rows if r["family"] == family and r["label_source"] in label_sources]
        return out[offset:offset + limit], len(out)
    out = tmp_path / "tri2"
    args = tb.build_arg_parser().parse_args(["export", "--team", TEAM, "--family", "screen-id",
                                             "--second-pass", "--out", str(out)])
    assert tb.run_export(args, list_fn=list_fn, screen_fn=lambda t, ui: SCREENS,
                         storage=FakeStorage(), prompts=_prompts()) == 0
    key = json.loads((out / "key.json").read_text(encoding="utf-8"))
    lines = [json.loads(l) for l in (out / "batch.jsonl").read_text(encoding="utf-8").splitlines()]
    assert key["second_pass"] is True
    assert set(key["samples"]) == {"open-run", "open-none", "low", "disagree", "pair"}
    assert seen_sources and all(s == ("none", "run", "teacher") for s in seen_sources)
    # still blind: no run label, no first-pass answer reaches the worker
    assert all(set(l) == set(tb.BLIND_KEYS) for l in lines)
    assert key["samples"]["low"]["ground_truth"] == {"node_id": LIVE, "label": "live"}


def _plan2(tb, rows, answers, conflict=lambda row, label: False, pct=0):
    key = {**_key({r["id"]: _ks(r) for r in rows}), "second_pass": True}
    accepted, rejected = tb.parse_answers(answers, key)
    assert rejected == []
    decisions, skipped = tb.plan(key, accepted, {r["id"]: dict(r) for r in rows}, conflict,
                                 "claude-sonnet-5", pct, "2026-10-01T12:00:00+00:00")
    return {d["id"]: d for d in decisions}, skipped


def test_second_pass_settles_or_excludes_never_asks_the_human(tb):
    rows = [_run_row("agree", triage=_nh("disagrees_with_run")), _run_row("disagree"),
            _run_row("agree_low"), _run_row("agree_pair"),
            _teacher_row("teach", triage=_nh("low_confidence")), _row("teach_none"),
            _teacher_row("teach_low", triage=_nh("low_confidence")), _row("teach_pair"),
            _teacher_row("spot", triage=_nh("spot_check"))]
    answers = [_line("agree", {"label": "home"}), _line("disagree", {"label": "live"}),
               _line("agree_low", {"label": "home"}, confidence="low"), _line("agree_pair", {"label": "home"}),
               _line("teach", {"label": "home"}), _line("teach_none", {"label": "live"}),
               _line("teach_low", {"label": "home"}, confidence="low"), _line("teach_pair", {"label": "live"}),
               _line("spot", {"label": "home"})]
    d, skipped = _plan2(tb, rows, answers, conflict=lambda row, label: row["id"] in ("agree_pair", "teach_pair"))
    got = {sid: (x.get("action"), x.get("status"), x.get("reason")) for sid, x in d.items()}
    assert got["agree"] == ("triage", "agreed", None)
    assert got["disagree"] == ("triage", "excluded", "disagrees_with_run")
    assert got["agree_low"] == ("triage", "excluded", "low_confidence")
    assert got["agree_pair"] == ("triage", "excluded", "conflict")
    assert got["teach"] == ("apply", "teacher_only", "no_independent_label")
    assert got["teach_none"] == ("apply", "teacher_only", "no_independent_label")
    # an unsettled row keeps its label: the triage is recorded, nothing is applied
    assert got["teach_low"] == ("triage", "excluded", "low_confidence")
    assert got["teach_pair"] == ("triage", "excluded", "conflict")
    # the human's spot-check is never re-decided by the AI
    assert d["spot"]["action"] == "skip" and skipped["already_triaged"] == 1
    assert not any(x.get("status") == "needs_human" for x in d.values())
    record = d["agree"]["triage"]
    assert record["second_pass"] is True
    assert record["first_pass"]["reason"] == "disagrees_with_run" and record["first_pass"]["batch_id"] == "tri-first"
    assert "first_pass" not in d["disagree"]["triage"]  # never triaged before


def test_second_pass_keeps_the_spot_check_on_its_final_rows_only(tb):
    rows = [_run_row(f"r{i}") for i in range(20)] + [_run_row("x")]
    answers = [_line(f"r{i}", {"label": "home"}) for i in range(20)] + [_line("x", {"label": "live"})]
    d, _ = _plan2(tb, rows, answers, pct=5)
    spot = [sid for sid, x in d.items() if x.get("reason") == "spot_check"]
    assert len(spot) == 1 and spot[0].startswith("r")
    assert d[spot[0]]["triage"]["spot_check_of"] == "agreed"
    assert d["x"]["status"] == "excluded"  # excluded is not final: never spot-checked


def test_second_pass_conflict_at_write_time_is_excluded_not_sent_to_the_human(tb):
    decisions = [
        {"id": "w", "family": "screen-id", "action": "apply", "status": "teacher_only", "reason": "no_independent_label",
         "label": {"node_id": HOME, "label": "home"}, "row": _row("w"),
         "triage": {"status": "teacher_only", "reason": "no_independent_label"}},
        {"id": "s", "family": "screen-id", "action": "triage", "status": "agreed", "reason": None,
         "triage": {"status": "agreed", "reason": None}},
    ]
    written = []

    def apply_fn(team_id, row, label, triage_for):
        written.append(triage_for(True))
        return {"ok": True}

    sets = []
    tb._apply(TEAM, decisions, apply_fn, lambda t, sid, rec: sets.append((sid, rec)) or True,
              lambda sid, t: {"id": sid, "label_conflict": False, "ground_truth": {"node_id": HOME}},
              __import__("collections").Counter(), lambda row, label: row["id"] == "s", unsettled="excluded")
    assert written[0]["status"] == "excluded" and written[0]["reason"] == "conflict"
    assert decisions[1]["status"] == "excluded" and sets[-1] == ("s", {"status": "excluded", "reason": "conflict"})


def test_second_pass_summary_counts_excluded(tb):
    rows = [_run_row("a"), _run_row("b")]
    d, skipped = _plan2(tb, rows, [_line("a", {"label": "home"}), _line("b", {"label": "live"})])
    key = {**_key({r["id"]: _ks(r) for r in rows}), "second_pass": True}
    summary = tb.summarize(key, list(d.values()), [], {"a": 1, "b": 1}, skipped)
    fam = summary["families"]["screen-id"]
    assert summary["second_pass"] is True
    assert fam["agreed"] == 1 and fam["excluded"] == {"disagrees_with_run": 1} and fam["needs_human"] == {}


def test_excluded_is_in_the_triage_vocabulary():
    assert "excluded" in triage_db.TRIAGE_STATUSES
    sql = open(os.path.join(_REPO_ROOT, "features", "ai-dataset", "db", "002_triage_excluded.sql"), encoding="utf-8").read()
    assert "'excluded'" in sql and "'resolved'" in sql


# ---- 2026-10-04: verdict_ai scores on the Langfuse traces of decided rows ------------------------

class _FakeLangfuse:
    def __init__(self):
        self.scores, self.flushed = [], 0

    def score(self, **kw):
        self.scores.append(kw)

    def flush(self):
        self.flushed += 1


def test_import_posts_verdict_ai_on_traced_decided_rows(tb, tmp_path, capsys):
    zap = {"channel_name": "BBC TWO", "channel_number": "", "program_name": "News", "confidence": 0.9}
    rows = [_row("agree", family="banner", userinterface=None, label_source="run",
                 model_answer=dict(zap, channel_number="3"),
                 ground_truth={"channel_number": "3"}, source_ref={"zap_id": "z1", "trace_id": "tr-agree"}),
            _row("teach", family="banner", userinterface=None, model_answer=zap,
                 source_ref={"zap_id": "z2", "trace_id": "tr-teach"}),
            _row("notrace", family="banner", userinterface=None, model_answer=zap, source_ref={"zap_id": "z3"}),
            _row("dis", family="banner", userinterface=None, label_source="run", model_answer=zap,
                 ground_truth={"channel_number": "9"}, source_ref={"trace_id": "tr-dis"})]
    folder = _write_batch(tmp_path, rows, [_line("agree", {"channel_number": "3", "channel_name": "BBC Two"}),
                                           _line("teach", {"channel_number": "5", "channel_name": "ITV"}),
                                           _line("notrace", {"channel_name": "BBC Two"}),
                                           _line("dis", {"channel_number": "3", "channel_name": "BBC Two"})],
                          family="banner")
    db = {r["id"]: dict(r) for r in rows}
    client = _FakeLangfuse()
    common = dict(get_fn=lambda sid, t: db.get(sid), conflict_fn=lambda r, label: False,
                  apply_fn=lambda *a: {"ok": True}, set_triage_fn=lambda *a: True,
                  column_fn=lambda: True, opted_in_fn=lambda t: True, langfuse_client=client)
    assert tb.run_import(_import_args(tb, folder, "--spot-check-pct", "0", "--teacher-model", "claude-x"),
                         **common) == 0
    by_trace = {s["trace_id"]: s for s in client.scores}
    assert set(by_trace) == {"tr-agree", "tr-teach"}  # needs_human (dis) and the untraced row get none
    assert by_trace["tr-agree"]["name"] == "verdict_ai" and by_trace["tr-agree"]["value"] == 1.0
    assert by_trace["tr-teach"]["value"] == 0.0  # the model read BBC TWO, the teacher ITV
    assert "teacher claude-x (teacher_only)" in by_trace["tr-teach"]["comment"]
    assert client.flushed == 1
    assert "2 verdict_ai scores" in capsys.readouterr().out
    # --no-langfuse and dry runs post nothing
    client.scores.clear()
    tb.run_import(_import_args(tb, folder, "--spot-check-pct", "0", "--no-langfuse"), **common)
    tb.run_import(_import_args(tb, folder, "--dry-run"), **common)
    assert client.scores == []


def test_post_verdicts_scores_excluded_rows_and_never_raises(tb):
    class Boom(_FakeLangfuse):
        def score(self, **kw):
            raise RuntimeError("langfuse down")
    row = _row("x", family="banner", model_answer={"channel_name": "ITV"}, source_ref={"trace_id": "tr-x"})
    decisions = [{"id": "x", "family": "banner", "action": "triage", "status": "excluded", "reason": "conflict",
                  "label": {"channel_name": "ITV"}, "row": row}]
    client = _FakeLangfuse()
    assert tb.post_verdicts(decisions, "m", client=client) == 1 and client.scores[0]["value"] == 1.0
    assert tb.post_verdicts(decisions, "m", client=Boom()) == 0
    assert tb.post_verdicts([dict(decisions[0], status="needs_human")], "m", client=client) is None


# ---- import-jev: Jev first (owner, 2026-10-04) ------------------------------------------------

GROUPS = {"g-home": {"node_id": "g-home", "label": "home"}, "g-live": {"node_id": "g-live", "label": "live"}}


def _jev(sid, choice="g-home", confidence=0.9, success=True):
    return {"id": sid, "choice": choice, "confidence": confidence, "success": success,
            "probabilities": {choice: confidence}, "decision_id": f"dec-{sid}"}


def _plan_jev(tb, rows, jev, conflict=lambda row, label: False, pct=0, snapshots=None):
    db = {r["id"]: dict(r) for r in rows}
    snaps = snapshots or {r["id"]: {"label_source": r["label_source"], "ground_truth": r["ground_truth"]} for r in rows}
    decisions, skipped = tb.plan_jev(snaps, jev, db, lambda ui: GROUPS, conflict, 0.8, pct, "jev-test",
                                     "2026-10-04T12:00:00+00:00")
    return {d["id"]: d for d in decisions}, skipped


def _home_run(sid, **kw):
    return _run_row(sid, node="g-home", label="home", **kw)


def test_jev_settles_only_confident_answers_never_as_agreed(tb):
    rows = [_row("none_hi"), _home_run("run_agree"), _home_run("run_disagree"), _row("none_lo"),
            _row("failed"), _row("unknown"), _row("pair"),
            _teacher_row("teacher_open", triage=_nh("low_confidence")),
            _teacher_row("spot", triage=_nh("spot_check")),
            _row("human", ground_truth={"node_id": "g-home", "label": "home"}, label_source="human"),
            _row("frozen", eval_version="eval-v0-ai")]
    jev = [_jev("none_hi", "g-live"), _jev("run_agree", "g-home"), _jev("run_disagree", "g-live"),
           _jev("none_lo", confidence=0.79), _jev("failed", success=False), _jev("unknown", "g-nope"),
           _jev("pair"), _jev("teacher_open", "g-home"), _jev("spot"), _jev("human"), _jev("frozen")]
    d, skipped = _plan_jev(tb, rows, jev, conflict=lambda row, label: row["id"] == "pair")
    got = {sid: (x.get("action"), x.get("status"), x.get("reason") or x.get("skip")) for sid, x in d.items()}
    assert got["none_hi"] == ("apply", "teacher_only", "jev_settled")
    assert d["none_hi"]["label"] == {"node_id": "g-live", "label": "live"}
    # agrees with the run: the run label stays (triage only), and it is NOT an independent check
    assert got["run_agree"] == ("triage", "teacher_only", "jev_agrees_with_run")
    assert got["teacher_open"] == ("apply", "teacher_only", "jev_settled")
    for sid, why in [("run_disagree", "disagrees_with_run"), ("none_lo", "below_confidence"),
                     ("failed", "jev_failed"), ("unknown", "unknown_choice"), ("pair", "conflict"),
                     ("spot", "already_triaged"), ("human", "human_label"), ("frozen", "frozen")]:
        assert got[sid] == ("skip", None, why), sid
    assert not any(x.get("status") == "agreed" for x in d.values())
    record = d["none_hi"]["triage"]
    assert record["teacher_model"] == "typesafe/jev-1.13" and record["jev"]["confidence"] == 0.9
    assert record["jev"]["decision_id"] == "dec-none_hi"
    assert d["teacher_open"]["triage"]["first_pass"]["reason"] == "low_confidence"


def test_jev_skips_a_row_changed_since_the_export(tb):
    row = _row("a")
    d, _ = _plan_jev(tb, [row], [_jev("a")], snapshots={"a": {"label_source": "run", "ground_truth": {"label": "x"}}})
    assert d["a"]["skip"] == "changed_since_export"


def test_jev_settled_rows_keep_the_spot_check(tb):
    rows = [_row(f"r{i}") for i in range(20)]
    d, _ = _plan_jev(tb, rows, [_jev(f"r{i}") for i in range(20)], pct=5)
    spot = [sid for sid, x in d.items() if x.get("reason") == "spot_check"]
    assert len(spot) == 1 and d[spot[0]]["triage"]["spot_check_of"] == "teacher_only"


def test_import_jev_cli_reads_a_bundle(tb, tmp_path):
    bundle = tmp_path / "bundle"
    (bundle / "ui" / "stb-testop").mkdir(parents=True)
    (bundle / "ui" / "stb-testop" / "groups.json").write_text(json.dumps([
        {"node_id": "g-home", "label": "home", "members": []}]), encoding="utf-8")
    row = _row("a")
    (bundle / "rows.jsonl").write_text(json.dumps({**row, "set": "open"}) + "\n", encoding="utf-8")
    (bundle / "decisions.jsonl").write_text(json.dumps(_jev("a")) + "\n", encoding="utf-8")
    args = tb.build_arg_parser().parse_args(["import-jev", "--team", TEAM, "--bundle", str(bundle), "--dry-run",
                                             "--spot-check-pct", "0"])
    import io
    out = io.StringIO()
    assert tb.run_import_jev(args, get_fn=lambda sid, team: dict(row), conflict_fn=lambda r, l: False, out=out) == 0
    assert "teacher_only/jev_settled" in out.getvalue() and "nothing written" in out.getvalue()
