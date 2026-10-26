"""
Decision models (TASK-38 / TASK-39): a typed, closed decision over a text state.

A decision model (TypeSafe's Jev, ``typesafe/jev-1.13`` on OpenRouter) is not a chat
model: it reads a ``state`` (text or JSON) and typed ``questions`` and answers with
calibrated probabilities, no text, no reasoning. It is text only. The harness lists the
legal options with their facts; the model only picks ("Jev-style", TASK-38 §1).

A decision profile is an ordinary ``ai_profiles`` row on an OpenRouter endpoint whose
``extra`` holds ``{"api": "decisions"}``. A decision usage may also be routed (Settings -> AI) to an
ordinary chat profile: ``decide`` then asks the same typed questions as JSON over the chat gateway
(``_decide_chat``; choice and noul, not score) and returns the same answer shape. A decision profile
must not sit behind a chat usage. Resolve with ``router.resolve_profile`` (pinned, no
fallback) or ``router.resolve`` (a ``text.decision`` route); every attempt is counted by
``router.record`` like a chat call.

Only the server holds the provider key. On a host (any process that is not the server,
``gateway.is_local_routing()`` False) ``decide`` / ``choose`` send the call to the server's
``POST /server/ai/decide``, which re-resolves (the same pinned profile, or the usage with this
host's context), calls the model, counts it and writes the log, and returns the same result.

Every call made for a team is logged to ``ai_decisions`` (state, questions, answers with
probabilities, cost, ``refs``); ``set_outcome`` attaches what really happened later. Those
rows set the decision thresholds and are the fine-tuning set for a local decision model
(TASK-38 §5). The result carries ``decision_id`` (None when not logged).

Every logged row's ``refs`` also carries the host it ran under -- ``tier`` (``rule`` / ``cv`` /
``model``), ``load_1m`` / ``load_5m`` / ``load_15m`` and ``cpu_count`` -- stamped by
``stamp_refs`` (TASK-68), so speed / accuracy / cost per tier is one query over one table.

    res = router.resolve_profile("jev", "text.decision", team_id)
    out = choose(res, state="...", options=[{"id": "home", "facts": "Home screen, tabs on top"}, ...],
                 instructions="Which screen is this?")
    out["choice"], out["confidence"], out["probabilities"]

Result of ``decide``: ``{success, answers, error, usage{input_tokens, output_tokens},
cost, ms, model, profile, endpoint, decision_id}``. ``choose`` adds ``choice``, ``confidence``,
``probabilities`` and ``reason`` (always None: the model gives none).
"""

from __future__ import annotations

import json
import os
import time
from typing import Any, Optional
from urllib.parse import urlsplit

from . import router
from . import tracing
from .provider_client import CallUsage, classify_error
from .secrets_store import get_secret
from shared.src.lib.utils import phase_timing

DECISIONS_PATH = "/api/alpha/decisions"
DEFAULT_TIMEOUT_S = 30
QUESTION_TYPES = ("choice", "noul", "score")

# Which tier answered (TASK-68). `rule` = the fingerprint matcher, `cv` = a deterministic check,
# `model` = Jev / Laya / OneJev actually ran. Only `model` costs money and latency, so grouping
# ai_decisions by refs->>'tier' is what makes the local-vs-Jev A/B one query.
TIER_RULE = "rule"
TIER_CV = "cv"
TIER_MODEL = "model"
TIERS = (TIER_RULE, TIER_CV, TIER_MODEL)
DEFAULT_TIER = TIER_MODEL  # reaching a logged decision means a model ran


_OFF = ("false", "0", "no", "off")
_logged_disabled = False


def enabled(usage: Optional[str] = None) -> bool:
    """The Jev switch: server ``.env`` ``JEV_ENABLED`` (unset = on; false/0/no/off = off) and,
    when ``usage`` is given, ``JEV_DISABLED_USAGES`` (comma-separated usage keys; a key also
    disables its children, e.g. ``text.decision.sherlock``). Read per call, so a service restart
    is enough. Hosts reach Jev through the server, which answers ``disabled`` when it is off."""
    if os.environ.get("JEV_ENABLED", "").strip().lower() in _OFF:
        return False
    if usage:
        for key in os.environ.get("JEV_DISABLED_USAGES", "").split(","):
            key = key.strip()
            if key and (usage == key or usage.startswith(key + ".")):
                return False
    return True


def disabled_result() -> dict:
    """What ``decide`` / ``choose`` return when Jev is off: not an error, callers keep their own path.
    Logs once per process."""
    global _logged_disabled
    if not _logged_disabled:
        _logged_disabled = True
        print("[Jev] disabled by JEV_ENABLED")
    return {"success": False, "error": "jev_disabled", "disabled": True}


def is_decision_profile(hop: router.Hop) -> bool:
    return ((hop.profile.get("extra") or {}).get("api")) == "decisions"


def decisions_url(hop: router.Hop) -> str:
    """The Decisions API on the endpoint's host. OpenRouter serves it at
    ``https://openrouter.ai/api/alpha/decisions``, beside (not under) ``/api/v1``."""
    parts = urlsplit(hop.base_url or "")
    if not parts.scheme or not parts.netloc:
        raise ValueError(f"endpoint {hop.endpoint_name} has no usable base_url")
    return f"{parts.scheme}://{parts.netloc}{DECISIONS_PATH}"


def _result(ok: bool, *, hop: Optional[router.Hop] = None, answers: Optional[dict] = None, error: str = "",
            tokens: tuple[int, int] = (0, 0), cost: Optional[float] = None, ms: int = 0) -> dict:
    return {
        "success": ok,
        "answers": answers or {},
        "error": error,
        "usage": {"input_tokens": tokens[0], "output_tokens": tokens[1]},
        "cost": cost,
        "ms": ms,
        "model": hop.model if hop else None,
        "profile": hop.profile_name if hop else None,
        "endpoint": hop.endpoint_name if hop else None,
    }


def decide(resolution: router.Resolution, state: Any, questions: dict, *,
           timeout_s: Optional[int] = None, refs: Optional[dict] = None, log: bool = True) -> dict:
    """Ask ``questions`` about ``state``, trying the resolution's hops in order. Never raises.

    ``questions``: ``{name: {"type": "choice" | "noul" | "score", "instructions": str,
    "criteria": ...}}`` exactly as the Decisions API takes them (choice: ``{option: criterion}``;
    noul: ``{"true": ..., "false": ...}``; score: ``[level, ...]``). ``refs`` (e.g.
    ``{"alert_id": ...}``) is stored with the log row to match the outcome later.
    """
    if not enabled(getattr(resolution, "usage", None)):
        return disabled_result()
    from . import gateway
    if not gateway.is_local_routing():
        return _decide_remote(resolution, state, questions, timeout_s, refs, log)
    out = _decide(resolution, state, questions, timeout_s)
    out["decision_id"] = _log(resolution, state, questions, out, refs) if log else None
    return out


def _decide_remote(resolution: router.Resolution, state: Any, questions: dict, timeout_s: Optional[int],
                   refs: Optional[dict], log: bool) -> dict:
    """A host's call, run by the server (``POST /server/ai/decide``). Never raises."""
    from . import gateway
    pinned = resolution.layer == "pinned" and resolution.hops
    payload = {
        "usage": resolution.usage,
        "profile": resolution.primary.profile_name if pinned else None,
        "team_id": resolution.team_id,
        "context": gateway._host_context(None),
        "state": state,
        "questions": questions,
        "refs": refs,
        "log": log,
        "timeout_s": timeout_s,
    }
    try:
        out = gateway._server_post("/server/ai/decide", payload,
                                   (timeout_s or DEFAULT_TIMEOUT_S) + gateway.BUDGET_MARGIN_S)
    except Exception as e:
        out = {"success": False, "error": f"server decide call failed: {e}"}
    result = {**_result(False), "decision_id": None, **out}
    result["success"] = bool(out.get("success"))
    if out.get("disabled"):
        return disabled_result()
    return result


def _answers_match(questions: dict, answers: dict) -> list[str]:
    """Names of questions whose answer is missing or of another type."""
    return sorted(name for name, q in questions.items()
                  if (answers.get(name) or {}).get("type") != q["type"])


def _log(resolution: router.Resolution, state: Any, questions: dict, out: dict,
         refs: Optional[dict]) -> Optional[str]:
    if not resolution.team_id:
        return None
    from shared.src.lib.database import ai_decisions_db
    return ai_decisions_db.insert_decision({
        "team_id": resolution.team_id,
        "usage_key": resolution.stats_label,
        "request_id": resolution.request_id,
        "profile": out.get("profile"),
        "model": out.get("model"),
        "state": state,
        "questions": questions,
        "answers": out.get("answers") or None,
        "ok": bool(out.get("success")),
        "error": out.get("error") or None,
        "ms": out.get("ms") or 0,
        "tokens_in": (out.get("usage") or {}).get("input_tokens") or 0,
        "cost": out.get("cost"),
        "refs": stamp_refs(refs),
    })


def host_context(tier: Optional[str] = None) -> dict:
    """The host stamp every decision row carries: ``tier`` + load + ``cpu_count``.

    Best-effort and never raises -- a host with no load numbers logs fewer fields, never no row.
    No schema change: ``refs`` is already JSONB and already carries routing/audit metadata.
    """
    out: dict = {"tier": tier if tier in TIERS else DEFAULT_TIER}
    try:
        out.update(phase_timing.load_context())
    except Exception:
        pass
    return out


def stamp_refs(refs: Optional[dict] = None, tier: Optional[str] = None) -> dict:
    """``refs`` plus the host stamp. The caller's own keys win; an explicit ``tier`` wins over both.

    ``tier`` may come from the caller explicitly, or from ``refs['tier']`` when a deterministic
    tier (``rule`` / ``cv``) logged the row; unset -- or a value that is not one of TIERS -- means
    ``model``. Callers that answer without a model can pass ``refs={"tier": "rule"}``, or call
    this directly, and land in the same table.
    """
    try:
        refs = dict(refs or {})
        chosen = tier if tier is not None else refs.get("tier")
        stamped = host_context(chosen)
        stamped.update(refs)
        stamped["tier"] = chosen if chosen in TIERS else DEFAULT_TIER
        return stamped
    except Exception:
        try:
            return dict(refs or {})
        except Exception:
            return {}


def set_outcome(decision_id: str, team_id: str, outcome: dict) -> bool:
    """Attach what really happened to a logged decision (e.g. ``{"real_freeze": False, "by": "human"}``)."""
    from shared.src.lib.database import ai_decisions_db
    return ai_decisions_db.set_outcome(decision_id, team_id, outcome)


def set_refs(decision_id: str, team_id: str, refs: dict) -> bool:
    """Replace a logged decision's ``refs``, e.g. to add today's answer when it came after the call."""
    from shared.src.lib.database import ai_decisions_db
    return ai_decisions_db.set_refs(decision_id, team_id, refs)


def _decide(resolution: router.Resolution, state: Any, questions: dict, timeout_s: Optional[int]) -> dict:
    import requests

    bad = [name for name, q in (questions or {}).items() if (q or {}).get("type") not in QUESTION_TYPES]
    if not questions or bad:
        return _result(False, error=f"questions must be typed {QUESTION_TYPES}; bad: {bad or 'none given'}")
    errors: list[str] = []
    last_hop: Optional[router.Hop] = None
    attempts: list[tracing.Attempt] = []
    for hop in resolution.hops:
        if not is_decision_profile(hop):
            # Settings -> AI may route a decision usage to an ordinary chat profile (e.g. MiniMax M3):
            # same questions, same answer shape, asked as JSON over the chat gateway.
            # That path goes through gateway.execute, which traces it itself.
            out = _decide_chat(resolution, hop, state, questions, timeout_s, errors)
            if out is not None:
                return out
            last_hop = hop
            continue
        if hop.reach == "host":
            errors.append(f"{hop.endpoint_name}: only reachable from hosts")
            continue
        key = get_secret(hop.endpoint.get("secret_name"))
        if not key:
            errors.append(f"{hop.endpoint_name}: no API key")
            continue
        fallback = resolution.is_fallback(hop)
        if router.skip_paused(resolution, hop, errors, fallback=fallback):
            continue
        last_hop = hop
        started = time.time()
        attempt = tracing.Attempt(hop)
        attempt.fallback = fallback
        try:
            response = requests.post(
                decisions_url(hop),
                json={"model": hop.model, "state": state, "questions": questions,
                      "session_id": resolution.request_id},
                headers={"Authorization": f"Bearer {key}",
                         "Content-Type": "application/json"},
                timeout=min(hop.timeout, timeout_s or DEFAULT_TIMEOUT_S),
            )
            response.raise_for_status()
            body = response.json()
        except Exception as e:
            ms = int((time.time() - started) * 1000)
            router.record(resolution, hop, ok=False, ms=ms, fallback=fallback,
                          error_type=classify_error(e))
            detail = getattr(getattr(e, "response", None), "text", "") or str(e)
            attempt.finish(ok=False, error=detail[:300])
            attempts.append(attempt)
            errors.append(f"{hop.endpoint_name} decisions call failed for '{hop.model}': {detail[:300]}")
            continue
        ms = int((time.time() - started) * 1000)
        usage = body.get("usage") or {}
        tokens = (int(usage.get("input_tokens") or 0), int(usage.get("output_tokens") or 0))
        answers = body.get("answers") or {}
        wrong = _answers_match(questions, answers)
        ok = not wrong
        cost = usage.get("cost")
        router.record(resolution, hop, ok=ok, ms=ms, tokens_in=tokens[0], tokens_out=tokens[1], fallback=fallback,
                      usage=CallUsage(tokens_in=tokens[0], tokens_out=tokens[1],
                                      cost=float(cost) if isinstance(cost, (int, float)) else None),
                      error_type=None if ok else "parse")
        attempt.finish(ok=ok, output=json.dumps(answers, ensure_ascii=False, default=str),
                       error=None if ok else f"answer missing or mistyped {wrong}",
                       tokens=tokens,
                       usage=CallUsage(tokens_in=tokens[0], tokens_out=tokens[1],
                                       cost=float(cost) if isinstance(cost, (int, float)) else None))
        attempts.append(attempt)
        if ok:
            _trace_decision(resolution, attempts, state, questions, ok=True, output=answers)
            return _result(True, hop=hop, answers=answers, tokens=tokens, cost=usage.get("cost"), ms=ms)
        errors.append(f"{hop.endpoint_name}: answer missing or mistyped {wrong}")
    _trace_decision(resolution, attempts, state, questions, ok=False,
                    error="; ".join(errors) or "no decision profile")
    return _result(False, hop=last_hop, error="; ".join(errors) or "no decision profile")


def _trace_decision(resolution: router.Resolution, attempts: list, state: Any, questions: dict,
                    *, ok: bool, output: Any = None, error: Optional[str] = None) -> None:
    """Send the Langfuse trace for a decision-model call (TASK-143).

    The decisions API is called by hand, not through the chat gateway, so it was counted
    in the call log but left no trace -- 15 usage keys (``text.decision*``) were invisible
    in Langfuse. This closes that gap: one trace, one generation per attempted hop, the
    same shape the gateway produces. The chat fallback (``_decide_chat``) is traced by
    ``gateway.execute`` itself, so it is not traced twice.
    """
    if not attempts:
        return
    label = resolution.stats_label
    tracing.trace_call(
        name=f"AI {label}",
        usage=label,
        trace_id=resolution.request_id,
        input={"state": state, "questions": questions},
        attempts=attempts,
        resolution=resolution,
        output=output,
        ok=ok,
        error=error,
        team_id=resolution.team_id,
        session_id=resolution.request_id,
    )


CHAT_MAX_TOKENS = 1500  # room for a reasoning model's thinking before the JSON answer


def _chat_prompt(state: Any, questions: dict) -> str:
    """The Decisions API contract as a chat prompt: JSON out, probabilities in [0, 1]."""
    import json
    spec = {}
    for name, q in questions.items():
        if q["type"] == "choice":
            spec[name] = {"question": q.get("instructions"), "options": q.get("criteria"),
                          "answer": '{"probabilities": {"<option id>": <0..1>, ...}} summing to 1'}
        else:  # noul
            spec[name] = {"question": q.get("instructions"), "true_means": (q.get("criteria") or {}).get("true"),
                          "false_means": (q.get("criteria") or {}).get("false"),
                          "answer": '{"p": <probability the answer is true, 0..1>}'}
    return ("You are a calibrated decision model. Read the state, then answer every question.\n"
            "Reply with ONE JSON object only, no prose, no code fence: {\"<question name>\": <its answer>, ...}.\n\n"
            f"STATE:\n{json.dumps(state, ensure_ascii=False, default=str)}\n\n"
            f"QUESTIONS:\n{json.dumps(spec, ensure_ascii=False)}")


def _json_object(text: str) -> dict:
    import json
    text = (text or "").strip()
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return {}
    try:
        data = json.loads(text[start:end + 1])
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _chat_answers(questions: dict, data: dict) -> dict:
    """Decisions-API-shaped answers from a chat model's JSON; a question it did not answer is left out."""
    answers: dict = {}
    for name, q in questions.items():
        raw = data.get(name)
        if not isinstance(raw, dict):
            continue
        if q["type"] == "choice":
            ids = list((q.get("criteria") or {}).keys())
            probs = {i: max(0.0, float(v)) for i, v in (raw.get("probabilities") or {}).items()
                     if i in ids and isinstance(v, (int, float))}
            total = sum(probs.values())
            if not probs or total <= 0:
                continue
            probs = {i: round(v / total, 4) for i, v in probs.items()}
            best = max(probs, key=probs.get)
            answers[name] = {"type": "choice", "choice": best, "confidence": probs[best], "probabilities": probs}
        elif q["type"] == "noul":
            p = raw.get("p")
            if isinstance(p, (int, float)) and 0 <= p <= 1:
                answers[name] = {"type": "noul", "noul": float(p)}
    return answers


def _decide_chat(resolution: router.Resolution, hop: router.Hop, state: Any, questions: dict,
                 timeout_s: Optional[int], errors: list) -> Optional[dict]:
    """Ask a chat-model hop the decision questions. Returns the success result, or None (reason appended
    to ``errors``) so the caller moves to the next hop. ``score`` questions need a decision model."""
    import dataclasses
    from . import gateway
    if any(q["type"] == "score" for q in questions.values()):
        errors.append(f"{hop.profile_name}: 'score' questions need a decision profile (extra.api == 'decisions')")
        return None
    started = time.time()
    res = gateway.execute(dataclasses.replace(resolution, hops=[hop]), _chat_prompt(state, questions),
                          max_tokens=CHAT_MAX_TOKENS, temperature=0.0,
                          timeout_s=min(hop.timeout, timeout_s or DEFAULT_TIMEOUT_S))
    if not res.get("success"):
        errors.append(f"{hop.profile_name}: {str(res.get('error'))[:300]}")
        return None
    answers = _chat_answers(questions, _json_object(res.get("content") or ""))
    wrong = _answers_match(questions, answers)
    if wrong:
        errors.append(f"{hop.profile_name}: answer missing or not JSON for {wrong}")
        return None
    usage = res.get("usage") or {}
    return _result(True, hop=hop, answers=answers, ms=int((time.time() - started) * 1000),
                   tokens=(int(usage.get("prompt_tokens") or 0), int(usage.get("completion_tokens") or 0)))


def choose(resolution: router.Resolution, state: Any, options: list[dict], *, instructions: str,
           timeout_s: Optional[int] = None, refs: Optional[dict] = None, log: bool = True) -> dict:
    """One closed choice: ``options`` is ``[{"id": str, "facts": str}, ...]`` (ids unique).

    Adds ``choice`` (an option id or None), ``confidence``, ``probabilities`` and ``reason``
    (None: a decision model gives no reasoning; read ``confidence`` instead).
    """
    if not enabled(getattr(resolution, "usage", None)):
        return {**disabled_result(), "answers": {}, "decision_id": None, "choice": None,
                "confidence": None, "probabilities": {}, "reason": None}
    ids = [str(o.get("id")) for o in options or []]
    if not ids or len(set(ids)) != len(ids):
        out = _result(False, error="options need unique ids")
    else:
        criteria = {str(o["id"]): str(o.get("facts") or o["id"]) for o in options}
        out = decide(resolution, state, {"choice": {"type": "choice", "instructions": instructions,
                                                    "criteria": criteria}}, timeout_s=timeout_s,
                     refs=refs, log=log)
    answer = (out.get("answers") or {}).get("choice") or {}
    choice = answer.get("choice") if answer.get("choice") in ids else None
    if out["success"] and choice is None:
        out.update(success=False, error=f"answer {answer.get('choice')!r} is not one of the options")
    out.setdefault("decision_id", None)
    out.update(choice=choice, confidence=answer.get("confidence"),
               probabilities=answer.get("probabilities") or {}, reason=None)
    return out
