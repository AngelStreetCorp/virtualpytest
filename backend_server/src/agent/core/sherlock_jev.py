"""
Jev verdict for Sherlock (TASK-38 §5 step 4): gated.

Before Sherlock's LLM, a decision model (Jev, usage ``text.decision.sherlock``) picks the same
closed verdict from the same evidence. At or above the gate confidence its verdict is the
analysis and the LLM isn't called; below it (or when Jev is unavailable) the LLM decides as before.
Every call is logged to ``ai_decisions``; when the LLM also ran, its verdict is added to the row's
``refs.sherlock`` so ``scripts/jev_agreement.py`` keeps measuring. An audit sample of gated results
still runs the LLM, so the gate's accuracy stays measured. The gate (0.9) comes from 217 results
labelled by blind judges: Jev ≥0.9 right 59/60 (docs/agent/ai/JEV.md "Correctness").
Never raises.
"""

import re
from typing import Any, Dict, Optional

from shared.src.lib.ai import decisions, router

from .backoff import Backoff

USAGE = "text.decision.sherlock"
MAX_REVIEW_CHARS = 12000
TIMEOUT_S = 15
CHECK_TYPE = "ai_auto_jev"
# Provider down (OpenRouter without credits): stop asking for 1 h, 5 h, then 24 h; the LLM decides alone.
BACKOFF = Backoff(USAGE)

INSTRUCTIONS = ("Classify this automated test execution: was the result a real outcome of the product, "
                "or caused by the test script or the test infrastructure?")

# Same verdicts as the LLM prompt (sherlock_handler.CLASSIFICATIONS). The wrong-argument clause took the
# misconfigured dns_lookuptime runs from 0/133 to 133/133 with no change on the other 84 labelled results.
OPTIONS = [
    {"id": "VALID_PASS", "facts": "the test passed and the evidence shows a legitimate success"},
    {"id": "VALID_FAIL", "facts": "the test failed because of a real product bug or wrong product state, with the test set up correctly"},
    {"id": "BUG", "facts": "the report says fail, but the visual or log evidence shows the expected element or state exists"},
    {"id": "SCRIPT_ISSUE", "facts": "test automation problem: bad selector, timing or expected value, or an argument whose value does not fit its meaning"},
    {"id": "SYSTEM_ISSUE", "facts": "infrastructure problem: black screen, no signal, device disconnected"},
    {"id": "EXTERNAL_BLOCK", "facts": "an external service or policy blocked the test, such as a CAPTCHA or rate limiting"},
]


def build_state(record: Dict[str, Any], review_markdown: str,
                arguments: Optional[list] = None) -> Dict[str, Any]:
    state = {
        "script_name": record.get("script_name"),
        "result": "PASSED" if record.get("success") else "FAILED",
        "error": record.get("error_msg") or None,
        "execution_time_ms": record.get("execution_time_ms"),
    }
    if arguments:
        state["arguments"] = arguments  # sherlock_args.for_record: value, default, meaning
    state["verification_review"] = (review_markdown or "no review available")[:MAX_REVIEW_CHARS]
    return state


def ask(record: Dict[str, Any], review_markdown: str, gate: float, nickname: str = "Sherlock",
        arguments: Optional[list] = None) -> Optional[Dict[str, Any]]:
    """Ask Jev for the verdict (logged). Returns the ``choose`` result, or None when skipped.
    ``out["gated"]`` is True when Jev's confidence reaches ``gate``: its verdict stands alone."""
    team_id = record.get("team_id")
    if not team_id or not decisions.enabled(USAGE):
        return None
    if BACKOFF.blocked():
        return None
    try:
        out = decisions.choose(router.resolve(USAGE, team_id), build_state(record, review_markdown, arguments), OPTIONS,
                               instructions=INSTRUCTIONS, timeout_s=TIMEOUT_S,
                               refs={"script_result_id": record.get("id"), "gate": gate})
    except Exception as e:
        print(f"[{nickname}] Jev skipped: {e}")
        return None
    if out.get("disabled"):  # switched off on the server (host-side env differs): the LLM decides
        return None
    if not out.get("success"):
        pause = BACKOFF.failed(str(out.get("error")))
        print(f"[{nickname}] Jev failed for {record.get('id')}: {out.get('error')} (Jev paused {pause // 3600} h)")
        return out
    BACKOFF.succeeded()
    out["gated"] = (out.get("confidence") or 0) >= gate
    print(f"[{nickname}] Jev {record.get('id')}: {out['choice']} conf={out.get('confidence')} "
          f"{'decides' if out['gated'] else 'unsure, LLM decides'} decision={out.get('decision_id')}")
    return out


ERROR_HINTS = ("error", "exception", "failed", "failure", "timeout", "timed out", "unreachable",
               "not found", "refused", "denied", "no signal", "disconnected", "black")
PASS_HINTS = ("verif", "passed", "success", "found", "match", "✅")
MAX_LINE_CHARS = 160
MAX_ERROR_LINES = 2


def _clip(text: str, limit: int = MAX_LINE_CHARS) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


_JSON_LOG = re.compile(r'\{[^{}]*?"message"\s*:\s*"((?:[^"\\]|\\.)*)"[^{}]*\}')


def _pick_lines(text: str, hints: tuple, count: int) -> list:
    """The most informative lines of ``text``: hint lines first, else the first lines, in original order.
    JSON log lines (``{"type":"log","message":"..."}``) are reduced to their message."""
    text = _JSON_LOG.sub(lambda m: m.group(1).replace('\\"', '"'), text or "")
    lines = [l.strip(" -*#>\t") for l in (text or "").splitlines()]
    lines = [l for l in lines if len(l) > 3]
    hinted = [l for l in lines if any(h in l.lower() for h in hints)]
    chosen = (hinted or lines)[:count]
    return [_clip(re.sub(r"^(error|exception)\s*:\s*", "", l, flags=re.I)) for l in chosen]


def build_evidence(record: Dict[str, Any], arguments: Optional[list], review_markdown: str,
                   choice: Optional[str]) -> list:
    """The facts Jev saw that matter for the verdict, as short strings. Deterministic, never raises."""
    ev = []
    try:
        error = (record.get("error_msg") or "").strip()
        if error:
            ev.append('error "' + " … ".join(_pick_lines(error, ERROR_HINTS, MAX_ERROR_LINES)) + '"')
        elif record.get("success"):
            lines = _pick_lines(review_markdown if review_markdown != "no review available" else "",
                                PASS_HINTS, 1)
            if lines:
                ev.append(f'verification "{lines[0]}"')
        args = [a for a in (arguments or []) if isinstance(a, dict) and a.get("name")]
        if args:
            changed = [a for a in args if a.get("used_default") is False
                       and not ("default" in a and str(a.get("value")) == str(a.get("default")))]
            if changed:
                shown = ", ".join(_clip(f"{a['name']}={a.get('value')}", 60) for a in changed[:4])
                ev.append(f"arguments: {shown} (default: " + ", ".join(
                    f"{a['name']}={a.get('default')}" for a in changed[:4]) + ")")
            else:
                ev.append("arguments: defaults")
        host = record.get("host_name") or record.get("device_name")
        if host:
            ev.append(f"host {host}")
        ms = record.get("execution_time_ms")
        outcome = "passed" if record.get("success") else "failed"
        if isinstance(ms, (int, float)) and ms >= 0:
            secs = ms / 1000
            ev.append(f"{outcome} after {secs:.0f} s" if secs >= 10 else f"{outcome} after {secs:.1f} s")
        elif "success" in record:
            ev.append(outcome)
    except Exception as e:
        print(f"[Sherlock] Jev evidence incomplete: {e}")
    return ev


def _percent(p: Any) -> int:
    try:
        return int(round(float(p) * 100))
    except (TypeError, ValueError):
        return 0


def explain(out: Dict[str, Any], evidence: list) -> str:
    """One self-contained sentence set: verdict, confidence, runners-up, evidence, decision id."""
    probs = out.get("probabilities") or {}
    runners = sorted(((c, p) for c, p in probs.items() if c != out.get("choice")), key=lambda cp: -(cp[1] or 0))
    nxt = [f"{c} {_percent(p)} %" for c, p in runners if _percent(p) >= 1][:2]
    conf = _percent(out.get("confidence"))
    text = f"Jev {conf} %" + (f" (next: {', '.join(nxt)})" if nxt else "") + "."
    if evidence:
        text += " Evidence: " + "; ".join(evidence) + "."
    return text + f" LLM not called (decision {str(out.get('decision_id') or '')[:8]})."


def as_analysis(out: Dict[str, Any], discard_classes: set, record: Optional[Dict[str, Any]] = None,
                arguments: Optional[list] = None, review_markdown: str = "") -> Dict[str, Any]:
    """Jev's gated verdict in the shape Sherlock saves, with its reasons: ``jev`` is stored in the
    result's ``metadata.jev`` so the UI can show probabilities and evidence without another call."""
    evidence = build_evidence(record or {}, arguments, review_markdown, out.get("choice"))
    probs = {c: round(float(p or 0), 4) for c, p in (out.get("probabilities") or {}).items()}
    runner = max(((c, p) for c, p in probs.items() if c != out["choice"]), key=lambda cp: cp[1], default=None)
    return {
        "classification": out["choice"],
        "discard": out["choice"] in discard_classes,
        "explanation": explain(out, evidence),
        "check_type": CHECK_TYPE,
        "jev": {"decision_id": out.get("decision_id"), "choice": out["choice"],
                "confidence": out.get("confidence"), "probabilities": probs,
                "runner_up": runner[0] if runner else None, "evidence": evidence},
    }


def record_llm_verdict(out: Optional[Dict[str, Any]], record: Dict[str, Any],
                       llm_analysis: Optional[Dict[str, Any]], gate: float, nickname: str = "Sherlock") -> None:
    """Add the LLM's verdict to Jev's logged decision, for the agreement report."""
    if not (out or {}).get("decision_id") or not out.get("success"):
        return
    llm_class = (llm_analysis or {}).get("classification")
    refs = {"script_result_id": record.get("id"), "gate": gate, "sherlock": llm_class,
            "audit": bool(out.get("gated"))}
    try:
        decisions.set_refs(out["decision_id"], record.get("team_id"), refs)
    except Exception as e:
        print(f"[{nickname}] Jev refs not updated: {e}")
        return
    agree = "n/a" if not llm_class else ("agree" if out["choice"] == llm_class else "DISAGREE")
    print(f"[{nickname}] Jev {record.get('id')}: {out['choice']} llm={llm_class} {agree}"
          f"{' (audit)' if out.get('gated') else ''}")
