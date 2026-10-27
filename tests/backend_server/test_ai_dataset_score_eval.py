"""ai-dataset feature: TASK-27 step 5 scoring — pure unit tests.

Covers ``features/ai-dataset/lib/family_prompts.py`` (prompts, canonical answers,
tolerant parsing), ``lib/comparators.py`` and the pure parts of
``scripts/score_eval.py`` (fallback abort, scoring loop, report merge, confusion
table). No network, no DB: the model call and the image fetch are injected fakes.
The router's pinned-profile resolution is tested in tests/shared/test_ai_router.py.

Run: pytest tests/backend_server/test_ai_dataset_score_eval.py -v
"""
import importlib
import importlib.util
import json
import os
import sys

import pytest

_TEST_DIR = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.normpath(os.path.join(_TEST_DIR, "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

# The interface the step 6/7 tooling imports.
family_prompts = importlib.import_module("features.ai-dataset.lib.family_prompts")
comparators = importlib.import_module("features.ai-dataset.lib.comparators")

_spec = importlib.util.spec_from_file_location(
    "score_eval", os.path.join(_REPO_ROOT, "features", "ai-dataset", "scripts", "score_eval.py"))
score_eval = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(score_eval)

pytestmark = pytest.mark.unit

SCREENS = [{"node_id": "46854a27-uuid", "label": "home"},
           {"node_id": "node-1761512376607", "label": "home_tvshop"},
           {"node_id": "n-guide", "label": "tvguide"}]
CTX = {"screen_labels": SCREENS}


# ---- build_prompt ----------------------------------------------------------------------

def test_screen_id_prompt_lists_screens_and_the_off_tree_option():
    prompt = family_prompts.build_prompt("screen-id", {}, CTX)
    for s in SCREENS:
        assert f"- {s['label']}" in prompt
    assert "46854a27" not in prompt  # node ids are never shown to the model
    assert 'if it is none of these, answer {"node_id": null, "label": "<short name e.g. popup>"}' in prompt.lower()
    assert '{"label": "<screen name>"}' in prompt
    # plain names work too (export/training), and are deduped case-insensitively
    plain = family_prompts.build_prompt("screen-id", {}, {"screen_labels": ["home", "Home", "live"]})
    assert [line for line in plain.splitlines() if line.startswith("- ")] == ["- home", "- live"]
    with pytest.raises(ValueError):
        family_prompts.build_prompt("screen-id", {}, None)


def test_freeze_strip_prompt_explains_frames_and_times():
    strip = {"model_answer": {"incident_type": "freeze", "evidence": "strip", "duration_ms": 30174,
                              "frames": [0.0, 15.0, 30.2]}}
    prompt = family_prompts.build_prompt("av-fault", strip)
    assert "strip of 3 frames" in prompt and "side by side" in prompt
    assert "+0.0 s, +15.0 s, +30.2 s" in prompt and "frozen <seconds> s" in prompt
    assert '"incident_type"' in prompt and "{evidence}" not in prompt
    single = family_prompts.build_prompt("av-fault", {"model_answer": {"incident_type": "blackscreen"}})
    assert "strip" not in single and "one frame" in single
    # model_answer stored as a JSON string is understood too
    assert family_prompts.is_strip({"model_answer": json.dumps(strip["model_answer"])})


def test_banner_prompt_is_the_runtime_prompt():
    from shared.src.lib.utils.ai_utils import _create_banner_analysis_prompt
    assert family_prompts.build_prompt("banner", {}) == _create_banner_analysis_prompt()
    assert family_prompts.FAMILY_PROMPTS["banner"] == _create_banner_analysis_prompt()


def test_every_family_has_a_prompt_and_unknown_is_refused():
    assert set(family_prompts.FAMILY_PROMPTS) == {"screen-id", "focus", "banner", "menu", "av-fault"}
    for fam in ("focus", "menu"):
        assert "{" in family_prompts.build_prompt(fam, {})
    with pytest.raises(ValueError):
        family_prompts.build_prompt("other", {})


# ---- answer_to_text / parse_answer ------------------------------------------------------

@pytest.mark.parametrize("family,truth", [
    ("screen-id", {"node_id": "46854a27-uuid", "label": "home"}),
    ("screen-id", {"node_id": None, "label": "popup"}),
    ("focus", {"focused": "Settings"}),
    ("banner", {"channel_number": "102", "channel_name": "ITV2"}),
    ("banner", {"channel_number": None, "channel_name": None}),
    ("menu", {"items": ["English", "French"], "selected": "French"}),
    ("av-fault", {"incident_type": "freeze"}),
    ("av-fault", {"incident_type": None}),
])
def test_canonical_answer_parses_back_to_a_correct_answer(family, truth):
    text = family_prompts.answer_to_text(family, truth)
    json.loads(text)
    parsed = family_prompts.parse_answer(family, text, CTX)
    assert comparators.compare(family, truth, parsed)[0], (text, parsed)


def test_screen_id_training_target_never_contains_node_ids():
    assert family_prompts.answer_to_text("screen-id", {"node_id": "46854a27-uuid", "label": "home"}) == '{"label": "home"}'
    assert json.loads(family_prompts.answer_to_text("screen-id", {"node_id": None, "label": " Popup "})) == \
        {"node_id": None, "label": "popup"}


def test_banner_target_uses_the_runtime_vocabulary():
    out = json.loads(family_prompts.answer_to_text("banner", {"channel_name": "itv2"}))
    assert out == {"banner_detected": True, "channel_name": "itv2", "channel_number": ""}
    assert json.loads(family_prompts.answer_to_text("banner", {"channel_number": None, "channel_name": None}))[
        "banner_detected"] is False


@pytest.mark.parametrize("text", [
    '{"label": "Home"}',
    '```json\n{"label": "home"}\n```',
    'Sure! The screen is:\n{"label": "home"} as requested.',
    '<think>looks like the start page {"label": "tvguide"}</think>{"label": "home"}',
    '{"label": "home",}',
])
def test_parse_answer_is_tolerant(text):
    assert family_prompts.parse_answer("screen-id", text, CTX) == {"node_id": "46854a27-uuid", "label": "home"}


@pytest.mark.parametrize("text", [None, "", "no json here", "[1, 2]", '{"unrelated": 1}', "{broken"])
def test_parse_answer_returns_none_on_garbage(text):
    assert family_prompts.parse_answer("screen-id", text, CTX) is None
    assert family_prompts.parse_answer("focus", text) is None


def test_parse_screen_off_tree_and_unknown_names():
    assert family_prompts.parse_answer("screen-id", '{"node_id": null, "label": "Popup"}', CTX) == \
        {"node_id": None, "label": "popup"}
    # an unlisted name is an off-tree guess
    assert family_prompts.parse_answer("screen-id", '{"label": "Netflix"}', CTX) == {"node_id": None, "label": "netflix"}
    # "node_id: null" wins even if the label happens to be a listed screen
    assert family_prompts.parse_answer("screen-id", '{"node_id": null, "label": "home"}', CTX)["node_id"] is None
    # a model echoing a real node id is mapped back
    assert family_prompts.parse_answer("screen-id", '{"node_id": "n-guide", "label": "guide"}', CTX) == \
        {"node_id": "n-guide", "label": "tvguide"}


def test_parse_runtime_banner_and_menu_shapes():
    runtime = ('{"banner_detected": true, "channel_name": "itv2", "channel_number": "", "program_name": '
               '"Big Brother", "start_time": "22:00", "end_time": "23:00", "confidence": 0.9}')
    assert family_prompts.parse_answer("banner", runtime) == {"channel_number": None, "channel_name": "itv2"}
    none = '{"banner_detected": false, "channel_name": "", "channel_number": ""}'
    assert family_prompts.parse_answer("banner", none) == {"channel_number": None, "channel_name": None}
    menu = ('{"menu_detected": true, "audio_languages": ["English", "French"], "subtitle_languages": [], '
            '"selected_audio": 1, "selected_subtitle": -1}')
    assert family_prompts.parse_answer("menu", menu) == {"items": ["English", "French"], "selected": "French"}
    assert family_prompts.parse_answer("menu", '{"items": ["A", "B"], "selected": 0}') == {"items": ["A", "B"], "selected": "A"}


def test_parse_av_fault_values():
    assert family_prompts.parse_answer("av-fault", '{"incident_type": "Freeze"}') == {"incident_type": "freeze"}
    assert family_prompts.parse_answer("av-fault", '{"incident_type": "none"}') == {"incident_type": None}
    assert family_prompts.parse_answer("av-fault", '{"incident_type": "audio_loss"}') is None


# ---- comparators --------------------------------------------------------------------------

def test_screen_id_comparator():
    truth = {"node_id": "46854a27-uuid", "label": "home"}
    assert comparators.screen_id(truth, {"node_id": "46854a27-uuid", "label": "home"})[0]
    ok, detail = comparators.screen_id(truth, {"node_id": "n-guide", "label": "tvguide"})
    assert not ok and "tvguide" in detail
    assert not comparators.screen_id(truth, {"node_id": None, "label": "home"})[0]
    off = {"node_id": None, "label": "popup"}
    assert comparators.screen_id(off, {"node_id": None, "label": " Popup "})[0]
    assert not comparators.screen_id(off, {"node_id": None, "label": "dialog"})[0]
    assert not comparators.screen_id(off, {"node_id": "n-guide", "label": "popup"})[0]
    assert comparators.screen_id(truth, None) == (False, "unparsed answer")


def test_focus_comparator():
    assert comparators.focus({"focused": "Settings "}, {"focused": "settings"})[0]
    assert not comparators.focus({"focused": "Settings"}, {"focused": "Search"})[0]


def test_banner_comparator():
    assert comparators.banner({"channel_number": "102"}, {"channel_number": "102", "channel_name": "whatever"})[0]
    assert not comparators.banner({"channel_number": "102"}, {"channel_number": "103", "channel_name": None})[0]
    assert comparators.banner({"channel_name": "ITV 2 HD"}, {"channel_number": None, "channel_name": "itv2"})[0]
    assert comparators.banner({"channel_name": "BBC One"}, {"channel_name": "bbc-one hd"})[0]
    assert not comparators.banner({"channel_name": "BBC One"}, {"channel_name": "BBC Two"})[0]
    both = {"channel_number": "1", "channel_name": "BBC One"}
    assert not comparators.banner(both, {"channel_number": "1", "channel_name": "ITV"})[0]
    no_banner = {"channel_number": None, "channel_name": None}
    assert comparators.banner(no_banner, {"channel_number": None, "channel_name": None})[0]
    assert not comparators.banner(no_banner, {"channel_number": None, "channel_name": "ITV"})[0]
    assert comparators.normalize_channel_name("E4 HD.") == "e4"


def test_menu_comparator():
    truth = {"items": ["English", "French"], "selected": "French"}
    assert comparators.menu(truth, {"items": ["French ", "English"], "selected": " French"})[0]
    assert not comparators.menu(truth, {"items": ["French", "English"], "selected": "french"})[0]
    assert not comparators.menu(truth, {"items": ["french", "English"], "selected": "French"})[0]
    assert not comparators.menu(truth, {"items": ["English"], "selected": "French"})[0]
    assert not comparators.menu(truth, {"items": ["English", "French"], "selected": "English"})[0]


def test_av_fault_comparator():
    assert comparators.av_fault({"incident_type": "freeze"}, {"incident_type": "freeze"})[0]
    assert comparators.av_fault({"incident_type": None, "static_screen": True}, {"incident_type": None})[0]
    assert not comparators.av_fault({"incident_type": None}, {"incident_type": "freeze"})[0]


# ---- scoring loop and the fallback abort --------------------------------------------------

def _rows():
    return [{"id": f"s{i}", "ground_truth": {"node_id": "46854a27-uuid", "label": "home"},
             "userinterface": "stb-testop", "device_model": "stb"} for i in range(3)]


def _gateway_result(content, profile="qwen-vl-pc", fallback=False, success=True):
    return {"success": success, "content": content, "error": "" if success else "offline",
            "usage": {"prompt_tokens": 100, "completion_tokens": 5, "total_tokens": 105},
            "provider_used": "openai_compatible", "model": "qwen/qwen3-vl-8b", "profile": profile,
            "endpoint": "lmstudio-pc", "via": "profile:" + profile, "split_arm": "", "fallback_used": fallback}


def _score(call):
    return score_eval.score_samples(_rows(), "screen-id", pinned_profile="qwen-vl-pc", call=call,
                                    image_for=lambda r: b"jpeg", context_for=lambda r: CTX)


def test_scoring_records_every_field():
    answers = iter(['{"label": "home"}', '{"label": "tvguide"}', "garbage"])
    samples = _score(lambda prompt, image: _gateway_result(next(answers)))
    assert [s["correct"] for s in samples] == [True, False, False]
    first = samples[0]
    for key in ("id", "truth", "answer_text", "parsed", "correct", "detail", "latency_ms", "model", "profile"):
        assert key in first
    assert first["parsed"] == {"node_id": "46854a27-uuid", "label": "home"}
    assert samples[2]["detail"] == "unparsed answer"
    summary = score_eval.summarize(samples)
    assert (summary["n"], summary["correct"], summary["unparsed"], summary["tokens_in"]) == (3, 1, 1, 300)
    assert summary["accuracy"] == pytest.approx(1 / 3, abs=1e-3) and summary["cost_usd"] is None


def test_a_fallback_answer_aborts_the_run():
    calls = []

    def call(prompt, image):
        calls.append(prompt)
        return _gateway_result('{"label": "home"}', fallback=len(calls) == 2)

    with pytest.raises(score_eval.FallbackAbort):
        _score(call)
    assert len(calls) == 2  # stopped at the first fallback, not after the run


def test_another_profile_answering_aborts_the_run():
    with pytest.raises(score_eval.FallbackAbort):
        _score(lambda p, i: _gateway_result('{"label": "home"}', profile="gpt-4.1-mini"))


def test_a_failed_call_is_an_error_not_an_abort():
    samples = _score(lambda p, i: _gateway_result("", success=False))
    assert all(not s["correct"] and s["error"] == "offline" for s in samples)
    assert score_eval.summarize(samples)["errors"] == 3


def test_usage_key_per_family():
    assert score_eval.usage_for("banner") == "vision.banner"
    assert score_eval.usage_for("menu") == "vision.menu"
    assert score_eval.usage_for("screen-id") == score_eval.usage_for("av-fault") == "vision"


# ---- report merge and confusion table -------------------------------------------------------

def _run(profile, created, correct_flags, quant="Q4_K_M", family="screen-id", predicted="tvguide"):
    samples = []
    for i, ok in enumerate(correct_flags):
        truth = {"node_id": "46854a27-uuid", "label": "home"} if i % 2 == 0 else {"node_id": "n-guide", "label": "tvguide"}
        parsed = truth if ok else ({"node_id": "n-guide", "label": predicted} if i % 2 == 0
                                   else {"node_id": "46854a27-uuid", "label": "home"})
        samples.append({"id": f"s{i}", "truth": truth, "parsed": parsed, "correct": ok, "error": None,
                        "latency_ms": 1000 + i, "tokens": {"prompt_tokens": 10, "completion_tokens": 2}})
    return {"run_id": f"{profile}-{created}", "created_at": created, "family": family, "source": "human",
            "eval_version": None, "usage_key": "vision", "profile": profile, "endpoint": "ep",
            "model": "qwen/qwen3-vl-8b", "model_reported": {"id": "qwen/qwen3-vl-8b", "quantization": quant},
            "summary": score_eval.summarize(samples), "samples": samples}


def test_report_merges_runs_newest_per_cell():
    old = _run("qwen-vl-pc", "2026-09-30T10:00:00Z", [False, False, False, False])
    new = _run("qwen-vl-pc", "2026-09-30T11:00:00Z", [True, True, True, False])
    cloud = _run("qwen3-vl-8b", "2026-09-30T09:00:00Z", [True, True, False, True], quant=None)
    report = score_eval.render_report([new, old, cloud])
    assert "| Family | qwen-vl-pc (qwen/qwen3-vl-8b, Q4_K_M) | qwen3-vl-8b (qwen/qwen3-vl-8b) |" in report
    row = next(line for line in report.splitlines() if line.startswith("| screen-id [human eval rows]"))
    assert row.count("**75.0%** (3/4)") == 2 and "0.0%" not in row
    assert "cost n/a (40+8 tok)" in row
    assert "`qwen-vl-pc-2026-09-30T11:00:00Z`" in report and "10:00:00Z`" not in report


def test_confusion_table_for_screen_id():
    run = _run("qwen-vl-pc", "2026-09-30T11:00:00Z", [False, True, False, False])
    conf = score_eval.confusion("screen-id", run["samples"])
    assert conf["per_class"]["home"] == {"n": 2, "correct": 0}
    assert conf["per_class"]["tvguide"] == {"n": 2, "correct": 1}
    assert conf["pairs"][0] == (("home", "tvguide"), 2)
    report = score_eval.render_report([run])
    assert "## Confusion: screen-id [human eval rows]" in report
    assert "| home | tvguide | 2 |" in report and "| tvguide | home | 1 |" in report
    assert "| home | 2 | 0 | 0% |" in report


def test_confusion_marks_off_tree_errors_and_unparsed():
    samples = [
        {"truth": {"node_id": None, "label": "popup"}, "parsed": {"node_id": "x", "label": "home"}, "correct": False},
        {"truth": {"node_id": "x", "label": "home"}, "parsed": None, "correct": False},
        {"truth": {"node_id": "x", "label": "home"}, "parsed": None, "correct": False, "error": "offline"},
    ]
    pairs = dict(score_eval.confusion("screen-id", samples)["pairs"])
    assert pairs == {("off-tree:popup", "home"): 1, ("home", "(unparsed)"): 1, ("home", "(error)"): 1}
    focus = [{"truth": {"focused": "Settings"}, "parsed": {"focused": "Search"}, "correct": False}]
    assert score_eval.confusion("focus", focus)["pairs"] == [(("settings", "search"), 1)]


def test_report_mode_reads_result_files(tmp_path):
    (tmp_path / "a.json").write_text(json.dumps(_run("p", "2026-09-30T11:00:00Z", [True, False])), encoding="utf-8")
    out = tmp_path / "report.md"
    assert score_eval.main(["--report", "--out", str(tmp_path), "--report-path", str(out)]) == 0
    assert "**50.0%** (1/2)" in out.read_text(encoding="utf-8")


def test_report_refuses_to_overwrite_with_no_results(tmp_path):
    out = tmp_path / "report.md"
    out.write_text("keep", encoding="utf-8")
    assert score_eval.main(["--report", "--out", str(tmp_path / "none"), "--report-path", str(out)]) == 1
    assert out.read_text(encoding="utf-8") == "keep"


def test_scoring_needs_team_family_profile():
    with pytest.raises(SystemExit):
        score_eval.main(["--family", "screen-id"])
    with pytest.raises(SystemExit):
        score_eval.main(["--team", "t", "--family", "banner", "--profile", "p", "--source", "eval-version"])


# ---- step 4k: screen groups and the screen-id/focus sub-metric -------------------------------------

GROUPED = {"node_id": "n-home", "label": "home", "node": "n-apps", "node_label": "home_apps", "focus": "Apps"}
GROUP_CTX = {"screen_labels": [{"node_id": "n-home", "label": "home"}, {"node_id": "n-store", "label": "apps"}]}


def test_screen_id_is_correct_when_the_group_matches():
    parsed = family_prompts.parse_answer("screen-id", '{"label": "home"}', GROUP_CTX)
    assert comparators.compare("screen-id", GROUPED, parsed) == (True, "node_id match")
    wrong = family_prompts.parse_answer("screen-id", '{"label": "apps"}', GROUP_CTX)
    assert comparators.compare("screen-id", GROUPED, wrong)[0] is False
    assert comparators.confusion_key("screen-id", GROUPED) == "home"      # confusion stays per group
    prompt = family_prompts.build_prompt("screen-id", {}, GROUP_CTX)
    assert "- home\n- apps" in prompt and "asked separately" in prompt


def test_focus_null_is_nothing_focused():
    assert family_prompts.parse_answer("focus", '{"focused": null}') == {"focused": None}
    assert family_prompts.parse_answer("focus", '{"focused": "null"}') == {"focused": None}
    assert family_prompts.answer_to_text("focus", {"focused": None}) == '{"focused": null}'
    assert comparators.compare("focus", {"focused": None}, {"focused": None})[0] is True
    assert comparators.compare("focus", {"focused": None}, {"focused": "Apps"})[0] is False
    assert comparators.compare("focus", {"focused": "Apps"}, {"focused": None})[0] is False
    assert comparators.confusion_key("focus", {"focused": None}) == "(nothing focused)"
    assert "null" in family_prompts.build_prompt("focus", {})


def test_focus_truth_only_on_grouped_rows_with_a_focus():
    assert family_prompts.focus_truth(GROUPED) == {"focused": "Apps"}
    assert family_prompts.focus_truth(dict(GROUPED, focus=None)) is None
    assert family_prompts.focus_truth({"node_id": "n-home", "label": "home"}) is None
    assert family_prompts.focus_truth({"node_id": None, "label": "popup"}) is None


def test_scoring_asks_the_focus_on_rows_with_a_focus_only():
    rows = [{"id": "a", "ground_truth": GROUPED, "userinterface": "stb-testop"},
            {"id": "b", "ground_truth": dict(GROUPED, node="n-home", node_label="home", focus=None),
             "userinterface": "stb-testop"},
            {"id": "c", "ground_truth": GROUPED, "userinterface": "stb-testop"}]
    prompts = []
    answers = iter(['{"label": "home"}', '{"focused": "apps"}',      # a: screen ok, focus ok
                    '{"label": "home"}',                              # b: no focus question
                    '{"label": "apps"}', '{"focused": "Replay"}'])   # c: screen wrong, focus wrong

    def call(prompt, image):
        prompts.append(prompt)
        return _gateway_result(next(answers))
    samples = score_eval.score_samples(rows, "screen-id", pinned_profile="qwen-vl-pc", call=call,
                                       image_for=lambda r: b"jpeg", context_for=lambda r: GROUP_CTX)
    assert len(prompts) == 5 and "highlighted" in prompts[1]
    assert [s["correct"] for s in samples] == [True, True, False]
    assert samples[0]["focus"]["correct"] is True and "focus" not in samples[1]
    assert samples[2]["focus"]["correct"] is False
    summary = score_eval.summarize(samples)
    assert summary["accuracy"] == pytest.approx(2 / 3, abs=1e-3)       # the screen, by group
    assert (summary["focus"]["n"], summary["focus"]["correct"]) == (2, 1)
    assert summary["focus"]["metric"] == "screen-id/focus"
    run = {"run_id": "r1", "created_at": "2026-09-30T12:00:00Z", "family": "screen-id", "source": "human",
           "eval_version": None, "usage_key": "vision", "profile": "qwen-vl-pc", "endpoint": "ep",
           "model": "m", "model_reported": {}, "summary": summary, "samples": samples}
    report = score_eval.render_report([run])
    focus_row = next(line for line in report.splitlines() if line.startswith("| screen-id/focus [human eval rows]"))
    assert "**50.0%** (1/2)" in focus_row
