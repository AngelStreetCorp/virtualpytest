"""Jev verdict (gated) for Sherlock (TASK-38 §5 step 4) and the agreement report. No network, no DB."""
import importlib.util
import os

import pytest

from backend_server.src.agent.core import sherlock_jev
from shared.src.lib.ai import usages

_ROOT = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
_spec = importlib.util.spec_from_file_location("jev_agreement", os.path.join(_ROOT, "scripts", "jev_agreement.py"))
jev_agreement = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(jev_agreement)

RECORD = {"id": "sr-1", "team_id": "team-1", "script_name": "zap", "success": False,
          "error_msg": "banner not found", "execution_time_ms": 4200}


@pytest.fixture(autouse=True)
def _fresh_backoff(monkeypatch):  # a failed ask pauses Jev for the module: never across tests
    monkeypatch.setattr(sherlock_jev, "BACKOFF", sherlock_jev.Backoff(sherlock_jev.USAGE))


def _wire(monkeypatch, out=None, resolve_error=None):
    calls = []

    def resolve(usage, team_id):
        if resolve_error:
            raise resolve_error
        return ("res", usage, team_id)

    def choose(resolution, state, options, **kw):
        calls.append({"resolution": resolution, "state": state, "options": options, **kw})
        return dict(out or {"success": True, "choice": "SYSTEM_ISSUE", "confidence": 0.95, "decision_id": "d-1"})

    monkeypatch.setattr(sherlock_jev.router, "resolve", resolve)
    monkeypatch.setattr(sherlock_jev.decisions, "choose", choose)
    monkeypatch.setattr(sherlock_jev.decisions, "set_refs", lambda did, team, refs: calls.append(
        {"set_refs": (did, team, refs)}) or True)
    return calls


def test_usage_is_a_decision_child():
    assert usages.lineage(sherlock_jev.USAGE) == ["text.decision.sherlock", "text.decision", "text"]


def test_ask_uses_the_six_verdicts_and_gates_at_the_threshold(monkeypatch):
    calls = _wire(monkeypatch)
    out = sherlock_jev.ask(RECORD, "x" * 20000, 0.9)
    call = calls[0]
    assert out["choice"] == "SYSTEM_ISSUE" and out["gated"] is True
    assert call["resolution"] == ("res", "text.decision.sherlock", "team-1")
    assert [o["id"] for o in call["options"]] == ["VALID_PASS", "VALID_FAIL", "BUG", "SCRIPT_ISSUE",
                                                  "SYSTEM_ISSUE", "EXTERNAL_BLOCK"]
    assert call["refs"] == {"script_result_id": "sr-1", "gate": 0.9}
    assert call["state"]["result"] == "FAILED" and call["state"]["error"] == "banner not found"
    assert len(call["state"]["verification_review"]) == sherlock_jev.MAX_REVIEW_CHARS
    _wire(monkeypatch, {"success": True, "choice": "VALID_FAIL", "confidence": 0.89, "decision_id": "d-2"})
    assert sherlock_jev.ask(RECORD, "", 0.9)["gated"] is False


def test_gated_verdict_is_saved_as_a_jev_analysis():
    out = {"choice": "SYSTEM_ISSUE", "confidence": 0.97, "decision_id": "d-1"}
    a = sherlock_jev.as_analysis(out, {"SCRIPT_ISSUE", "SYSTEM_ISSUE"})
    assert a["classification"] == "SYSTEM_ISSUE" and a["discard"] is True
    assert a["check_type"] == "ai_auto_jev" and "Jev 97 %" in a["explanation"]
    assert sherlock_jev.as_analysis({**out, "choice": "VALID_FAIL"}, {"SYSTEM_ISSUE"})["discard"] is False


def test_llm_verdict_is_added_to_the_decision_refs(monkeypatch):
    calls = _wire(monkeypatch)
    jev = {"success": True, "choice": "SYSTEM_ISSUE", "decision_id": "d-1", "gated": False}
    sherlock_jev.record_llm_verdict(jev, RECORD, {"classification": "SCRIPT_ISSUE"}, 0.9)
    assert calls[-1]["set_refs"] == ("d-1", "team-1", {"script_result_id": "sr-1", "gate": 0.9,
                                                       "sherlock": "SCRIPT_ISSUE", "audit": False})
    n = len(calls)
    sherlock_jev.record_llm_verdict(None, RECORD, {"classification": "SCRIPT_ISSUE"}, 0.9)
    sherlock_jev.record_llm_verdict({"success": False, "decision_id": "d-3"}, RECORD, None, 0.9)
    assert len(calls) == n


def test_ask_never_raises_and_skips_without_team(monkeypatch):
    _wire(monkeypatch, resolve_error=RuntimeError("no route"))
    assert sherlock_jev.ask(RECORD, "", 0.9) is None
    calls = _wire(monkeypatch)
    assert sherlock_jev.ask({**RECORD, "team_id": None}, "", 0.9) is None and calls == []


def _row(choice, conf, ref, label=None, ok=True):
    return {"ok": ok, "answers": {"choice": {"choice": choice, "confidence": conf}},
            "refs": {"sherlock": ref}, "outcome": {"label": label} if label else None}


def test_agreement_buckets_and_human_override():
    rows = [_row("A", 0.95, "A"), _row("A", 0.92, "B"), _row("B", 0.65, "B"),
            _row("A", 0.5, "A", label="C"), _row("A", 0.99, None), _row("A", 0.99, "A", ok=False)]
    s = jev_agreement.summarize(rows, "sherlock")
    assert (s["n"], s["agree"]) == (4, 2)
    assert s["buckets"][">=0.9"] == {"n": 2, "agree": 1}
    assert s["buckets"]["0.6-0.7"] == {"n": 1, "agree": 1}
    assert s["buckets"]["<0.6"] == {"n": 1, "agree": 0}
    assert s["confusion"][("B", "A")] == 1 and s["confusion"][("C", "A")] == 1


def _handler(monkeypatch, jev_out, audited=False, llm_fails=False, retry_out=None):
    from backend_server.src.agent.core import sherlock_handler
    h = sherlock_handler.SherlockHandler()
    seen = {"saved": [], "llm": 0, "refs": [], "asks": 0, "errors": []}
    monkeypatch.setattr(h, "_mark_ai_error", lambda rid, err: seen["errors"].append(err))
    monkeypatch.setattr(h, "_load_script_result", lambda rid: dict(RECORD))
    monkeypatch.setattr(h, "_fetch_markdown", lambda record: "review")
    monkeypatch.setattr(h, "_jev_audited", lambda rid: audited)
    monkeypatch.setattr(h, "_save_analysis", lambda rid, a: seen["saved"].append(a))

    def llm(record, md, arguments=None):
        seen["llm"] += 1
        seen["llm_arguments"] = arguments
        if llm_fails:
            raise RuntimeError("HTTP 402 insufficient credits")
        return {"classification": "VALID_FAIL", "discard": False, "explanation": "llm"}

    monkeypatch.setattr(h, "_classify_with_llm", llm)
    monkeypatch.setattr(sherlock_handler.sherlock_args, "for_record", lambda record: ARGS)
    def ask(*a, **k):
        seen["asks"] += 1
        out = jev_out if seen["asks"] == 1 else retry_out
        return dict(out) if out else None

    monkeypatch.setattr(sherlock_handler.sherlock_jev, "ask", ask)
    monkeypatch.setattr(sherlock_handler.sherlock_jev.decisions, "set_refs",
                        lambda did, team, refs: seen["refs"].append(refs) or True)
    h.process_task_direct("script", "sr-1", {})
    return seen


ARGS = [{"name": "dns", "value": "x.example", "default": "system", "used_default": False}]
SURE = {"success": True, "choice": "SYSTEM_ISSUE", "confidence": 0.97, "decision_id": "d-1", "gated": True}


def test_handler_gated_saves_jev_and_skips_the_llm(monkeypatch):
    seen = _handler(monkeypatch, SURE)
    assert seen["llm"] == 0 and seen["refs"] == []
    assert [a["classification"] for a in seen["saved"]] == ["SYSTEM_ISSUE"]
    assert seen["saved"][0]["check_type"] == "ai_auto_jev" and seen["saved"][0]["discard"] is True


def test_handler_audit_runs_the_llm_but_keeps_jev_saved(monkeypatch):
    seen = _handler(monkeypatch, SURE, audited=True)
    assert seen["llm"] == 1 and [a["classification"] for a in seen["saved"]] == ["SYSTEM_ISSUE"]
    assert seen["refs"][0]["sherlock"] == "VALID_FAIL" and seen["refs"][0]["audit"] is True


def test_handler_unsure_or_unavailable_falls_back_to_the_llm(monkeypatch):
    seen = _handler(monkeypatch, {**SURE, "confidence": 0.6, "gated": False})
    assert seen["llm"] == 1 and seen["saved"][0]["classification"] == "VALID_FAIL"
    assert "check_type" not in seen["saved"][0]
    assert seen["refs"][0]["sherlock"] == "VALID_FAIL" and seen["refs"][0]["audit"] is False
    assert seen["llm_arguments"] == ARGS
    seen = _handler(monkeypatch, None)
    assert seen["llm"] == 1 and seen["refs"] == []


def test_handler_llm_failure_keeps_a_gated_jev_verdict(monkeypatch):
    seen = _handler(monkeypatch, None, llm_fails=True, retry_out=SURE)
    assert seen["asks"] == 2 and seen["errors"] == []
    assert seen["saved"][0]["check_type"] == "ai_auto_jev"
    # Jev unsure (below the gate), or unavailable twice: ai_error stays
    seen = _handler(monkeypatch, {**SURE, "confidence": 0.6, "gated": False}, llm_fails=True)
    assert seen["asks"] == 1 and seen["saved"] == [] and len(seen["errors"]) == 1
    seen = _handler(monkeypatch, None, llm_fails=True)
    assert seen["asks"] == 2 and seen["saved"] == [] and len(seen["errors"]) == 1


def test_state_carries_arguments_only_when_known():
    assert "arguments" not in sherlock_jev.build_state(RECORD, "r")
    state = sherlock_jev.build_state(RECORD, "r", ARGS)
    assert state["arguments"] == ARGS and list(state)[-1] == "verification_review"


# --- "Every Jev verdict explains itself" (TASK-47): evidence + explanation + metadata.jev ---

SPEEDTEST = {
    "id": "sr-9", "team_id": "team-1", "script_name": "ookla_speedtest", "success": False,
    "host_name": "host-clone-1", "execution_time_ms": 11186,
    "error_msg": 'Speedtest failed: speedtest command failed (exit code 2) - {"type":"log","message":"Error: [101] '
                 'Network unreachable","level":"error"}\n{"type":"log","message":"Error: [0] Timeout occurred in '
                 'connect.","level":"error"}\n',
}
PROBS = {"BUG": 0, "VALID_FAIL": 0.05, "VALID_PASS": 0, "SCRIPT_ISSUE": 0.01, "SYSTEM_ISSUE": 0.93,
         "EXTERNAL_BLOCK": 0.01}
JEV_OUT = {"choice": "SYSTEM_ISSUE", "confidence": 0.93, "decision_id": "c173506b-2c5d-4965-9ede-76e0a95cbe93",
           "probabilities": PROBS}
DEFAULT_ARGS = [{"name": "server", "value": "auto", "default": "auto", "used_default": False},
                {"name": "interface", "value": "auto", "default": "auto", "used_default": True}]


def test_explanation_is_self_contained_with_probabilities_and_evidence():
    a = sherlock_jev.as_analysis(JEV_OUT, {"SYSTEM_ISSUE"}, SPEEDTEST, DEFAULT_ARGS, "")
    text = a["explanation"]
    assert text.startswith("Jev 93 % (next: VALID_FAIL 5 %, SCRIPT_ISSUE 1 %). Evidence: error \"")
    assert "Network unreachable" in text and "Timeout occurred in connect" in text and '{"type"' not in text
    assert "arguments: defaults" in text and "host host-clone-1" in text and "failed after 11 s" in text
    assert text.endswith("LLM not called (decision c173506b).")
    jev = a["jev"]
    assert jev["decision_id"] == JEV_OUT["decision_id"] and jev["choice"] == "SYSTEM_ISSUE"
    assert jev["runner_up"] == "VALID_FAIL" and jev["probabilities"]["SYSTEM_ISSUE"] == 0.93
    assert jev["evidence"] and len(jev["probabilities"]) == 6


def test_error_pick_prefers_informative_lines_and_caps_length():
    err = "starting\nsetup ok\n" + "x" * 500 + " timeout\nTraceback\nValueError: bad thing happened\nmore"
    ev = sherlock_jev.build_evidence({"error_msg": err, "success": False}, None, "", "VALID_FAIL")
    line = ev[0]
    assert "setup ok" not in line and "bad thing happened" in line
    assert all(len(part) <= sherlock_jev.MAX_LINE_CHARS for part in line[len('error "'):-1].split(" … "))


def test_non_default_arguments_are_listed_with_their_default():
    args = [{"name": "dns", "value": "my.host", "default": "8.8.8.8", "used_default": False},
            {"name": "count", "value": "3", "default": "3", "used_default": False}]
    ev = sherlock_jev.build_evidence({"success": False, "error_msg": "e"}, args, "", None)
    assert "arguments: dns=my.host (default: dns=8.8.8.8)" in ev


def test_pass_case_uses_the_verification_line_and_missing_fields_are_skipped():
    review = "# Pack\n- status: PASS\n- Verification: banner found at 0.97\n"
    ev = sherlock_jev.build_evidence({"success": True, "execution_time_ms": 4200}, [], review, "VALID_PASS")
    assert ev[0].startswith('verification "') and "banner found" in ev[0] and "passed after 4.2 s" in ev
    assert sherlock_jev.build_evidence({}, None, "", None) == []
    assert sherlock_jev.build_evidence({"success": True}, None, "no review available", None) == ["passed"]


def test_explanation_without_probabilities_or_evidence_still_reads():
    a = sherlock_jev.as_analysis({"choice": "VALID_PASS", "confidence": 0.99, "decision_id": "abcdef123456"},
                                 set())
    assert a["explanation"] == "Jev 99 %. LLM not called (decision abcdef12)."
    assert a["jev"]["runner_up"] is None and a["jev"]["evidence"] == []
