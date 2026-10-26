"""Atlas voice fast path (TASK-140).

One spoken command → one model call → a hint for Atlas's quick step: open a page, take
control of a named device, goto a node, stop. Atlas validates and runs the hint inside the session; anything else
goes to the normal Atlas turn as words. Two inputs are offered for testing:

- ``transcript``: the browser's speech-to-text, then the model picks the tool from the text;
- ``audio``: the model hears the recording (16 kHz WAV) and picks the tool itself.

Safety (TASK-112 rules): the device must be one the caller's Atlas context lists — no guessing, no
substitution; nothing runs here, the Atlas quick step checks and runs the hint.
Routing and tracking: usage ``agent.voice``; the model is an AI router profile (Settings → AI) on its endpoint's
own key, and every call is written to the AI call log and traced to Langfuse like any other caller.
Test spend is also capped by ``VOICE_SPEND_CAP_USD``.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import requests

from shared.src.lib.ai import router as ai_router
from shared.src.lib.ai import tracing as ai_tracing
from shared.src.lib.ai.config import get_preset
from shared.src.lib.ai.provider_client import CallUsage, openai_call_usage
from shared.src.lib.ai.secrets_store import get_secret

logger = logging.getLogger(__name__)

USAGE = "agent.voice"
SPEND_CAP_USD = float(os.getenv("VOICE_SPEND_CAP_USD", "3.0"))

# Router profiles of the two models measured on 2026-10-20 (TASK-140 G3): 9/9 on the spoken test set.
PROFILES: dict[str, str] = {
    "voxtral": "voice-voxtral",          # mistralai/voxtral-small-24b-2507 on the openrouter endpoint
    "gemini-lite": "voice-gemini-lite",  # google/gemini-3.5-flash-lite on the openrouter endpoint
}

# Spoken page names → app paths (subset of page_interaction.NAVIGATION_ALIASES).
PAGES: dict[str, str] = {
    "dashboard": "/", "devices": "/device-control", "atlas": "/ai-agent", "agent dashboard": "/agent-dashboard",
    "test builder": "/builder/test-builder", "campaign builder": "/builder/campaign-builder",
    "test cases": "/test-plan/test-cases", "campaigns": "/test-plan/campaigns",
    "requirements": "/test-plan/requirements", "coverage": "/test-plan/coverage",
    "run tests": "/test-execution/run-tests", "deployments": "/test-execution/deployments",
    "incidents": "/monitoring/incidents", "heatmap": "/monitoring/heatmap", "ai queue": "/monitoring/ai-queue",
    "system monitoring": "/monitoring/system", "test reports": "/test-results/reports",
    "model reports": "/test-results/model-reports", "dependency report": "/test-results/dependency-report",
}

_SPEND_LOCK = threading.Lock()


def _spend_path() -> Path:
    base = os.getenv("VPT_CONFIG_DIR", "").strip() or "~/.config/virtualpytest"
    return Path(base).expanduser() / "voice_spend.json"


def spent_usd() -> float:
    try:
        return float(json.loads(_spend_path().read_text()).get("usd", 0.0))
    except (FileNotFoundError, ValueError):
        return 0.0


def _add_spend(cost: float) -> None:
    with _SPEND_LOCK:
        path = _spend_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"usd": round(spent_usd() + max(cost, 0.0), 6)}))


def _tools(device_names: list[str], actions: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    device = {"type": "string", "description": "device name exactly as listed"}
    if device_names:
        device["enum"] = device_names
    spec = [
        ("navigate_to_page", "Open a page of the web app.",
         {"page": {"type": "string", "enum": sorted(PAGES)}}, ["page"]),
        ("take_control", "Take control of a device by name.", {"device": device}, ["device"]),
        ("navigate_to_node", ("Run goto: move a device to a node (screen) of its navigation tree. "
                              "Device is optional: the one in use when not said."),
         {"node": {"type": "string", "description": "node name, in English as the user would label it"},
          "device": device}, ["node"]),
        ("abort", "Stop everything now.", {}, []),
        ("ask_atlas", "Anything else: questions, several steps, unclear requests. Give the user's words.",
         {"text": {"type": "string", "description": "what the user said, word for word"}}, ["text"]),
    ]
    if actions:
        # The device in control (TASK-160): one of ITS OWN listed actions, nothing else. The enum is the allow-list.
        listing = "; ".join(f"{a['id']} = {a['label']}" for a in actions[:60])
        spec.insert(0, ("device_action", f"Do one action of the device in control. Actions: {listing}",
                        {"action": {"type": "string", "enum": [a["id"] for a in actions]},
                         "params": {"type": "object", "description": "only to change a listed parameter, e.g. {\"cm\": 30}"}},
                        ["action"]))
    return [{"type": "function", "function": {"name": n, "description": d,
                                               "parameters": {"type": "object", "properties": p, "required": r}}}
            for n, d, p, r in spec]


def _system(lang: str, device_names: list[str], current_device: str, controlled: bool = False) -> str:
    devices = ", ".join(device_names) or "none known"
    return ("You are the voice command layer of Atlas, the assistant of a device-test lab app. The user speaks "
            f"(app language: {lang}; they may speak English, French or German). Call exactly one tool. "
            f"Known devices: {devices}. Device in use: {current_device or 'none'}. "
            + ("The device in use is under the user's control: a spoken command for it is a device_action. " if controlled else "")
            + "Use ask_atlas for anything that is not one simple command, or when unsure.")


def _refused(mode: str, model_key: str, result: dict[str, Any]) -> dict[str, Any]:
    """A command refused before any model call (unknown model, budget, routing, key): logged, never silent."""
    print(f"[VOICE] mode={mode} model={model_key} result=refused error={result.get('error')}")
    return result


def classify(*, mode: str, model_key: str, lang: str, devices: list[dict[str, Any]], current_device: str,
             team_id: str, text: str = "", audio_b64: str = "",
             actions: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Return {tool, args, model, latency_ms, cost_usd} or {error}."""
    profile = PROFILES.get(model_key)
    if not profile:
        return _refused(mode, model_key, {"error": f"unknown model '{model_key}'"})
    if spent_usd() >= SPEND_CAP_USD:
        return _refused(mode, model_key, {"error": f"voice test budget of ${SPEND_CAP_USD:.2f} is used up"})
    try:
        # The user picked the model, so the profile is pinned; this is a real call, not a scoring run, so it
        # is counted and traced as agent.voice (resolve_profile labels pinned calls eval:<usage>).
        resolution = dataclasses.replace(ai_router.resolve_profile(profile, USAGE, team_id=team_id), label="")
    except Exception as exc:  # noqa: BLE001 - routing errors are reported to the user as-is
        return _refused(mode, model_key, {"error": f"voice model not available: {exc}"})
    hop = resolution.primary
    key = get_secret(hop.endpoint.get("secret_name"))
    if not key or not hop.base_url:
        return _refused(mode, model_key, {"error": f"no key for the '{hop.endpoint_name}' AI endpoint (Settings → AI)"})
    names = sorted({str(d.get("device_name") or "").strip() for d in devices if d.get("device_name")})
    if mode == "audio":
        if not audio_b64:
            return _refused(mode, model_key, {"error": "no audio"})
        content: Any = [{"type": "input_audio", "input_audio": {"data": audio_b64, "format": "wav"}}]
    else:
        if not text.strip():
            return _refused(mode, model_key, {"error": "no text"})
        content = text.strip()
    messages = [{"role": "system", "content": _system(lang, names, current_device, bool(actions))},
                {"role": "user", "content": content}]
    body = {
        "model": hop.model,
        "messages": messages,
        "tools": _tools(names, actions),
        "tool_choice": "required" if model_key == "gemini-lite" else "auto",
        "max_tokens": 300,
        "usage": {"include": True},
    }
    attempt = ai_tracing.Attempt(hop)
    started = time.time()
    data: dict[str, Any] = {}
    error = ""
    try:
        resp = requests.post(f"{hop.base_url.rstrip('/')}/chat/completions", json=body, timeout=min(hop.timeout, 30),
                             headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                                      **get_preset(hop.preset).extra_headers})
        if resp.status_code == 200:
            data = resp.json()
        else:
            error = f"HTTP {resp.status_code}"
    except requests.RequestException as exc:
        error = exc.__class__.__name__
    latency_ms = int((time.time() - started) * 1000)
    usage = openai_call_usage(data.get("usage") or {})
    message = ((data.get("choices") or [{}])[0].get("message") or {}) if data else {}
    calls = message.get("tool_calls") or []
    fn = (calls[0].get("function") or {}) if calls else {}
    try:
        args = json.loads(fn.get("arguments") or "{}") if fn else {}
    except ValueError:
        args = {}
    if not isinstance(args, dict):
        args = {}
    tool = fn.get("name") if fn else ("ask_atlas" if data else None)
    if tool == "ask_atlas":
        # Atlas gets the user's own words (the browser transcript), never the model's reply to them.
        args = {"text": text.strip() or str(args.get("text") or "")}
    ok = bool(data)
    output = json.dumps({"tool": tool, "args": args}, ensure_ascii=False) if ok else None
    attempt.finish(ok=ok, output=output, error=error or None, tokens=(usage.tokens_in, usage.tokens_out), usage=usage)
    ai_router.record(resolution, hop, ok=ok, ms=latency_ms, tokens_in=usage.tokens_in, tokens_out=usage.tokens_out,
                     usage=usage, error_type=None if ok else "other", extra={"tool_calls": 1 if calls else 0})
    cost = float(usage.cost or 0.0)
    _add_spend(cost)

    def finish(outcome: dict[str, Any]) -> None:
        """Trace the call with what it led to (ran, failed, handed to Atlas and why), once it is known."""
        result = outcome.get("action")
        ai_tracing.trace_call(
            name=f"Atlas voice command ({mode})", usage=USAGE, input=messages, attempts=[attempt],
            resolution=resolution, output=json.dumps({"tool": tool, "args": args, "outcome": outcome}, ensure_ascii=False),
            ok=ok, team_id=team_id,
            extra={"voice_mode": mode, "voice_model": model_key, "voice_tool": tool, "voice_result": result,
                   "voice_reason": outcome.get("reason"),
                   "understood": tool not in (None, "ask_atlas")})
        # print, like the [AI] lines: the server journal shows stdout.
        print(f"[VOICE] mode={mode} model={model_key} heard={(text or '')[:120]!r} tool={tool} args={args} "
              f"result={result} reason={outcome.get('reason') or '-'} ms={latency_ms} cost={cost}")

    if not ok:
        ai_tracing.trace_call(name=f"Atlas voice command ({mode})", usage=USAGE, input=messages, attempts=[attempt],
                              resolution=resolution, ok=False, error=error or None, team_id=team_id,
                              extra={"voice_mode": mode, "voice_model": model_key, "voice_result": "model_error"})
        print(f"[VOICE] mode={mode} model={model_key} result=model_error error={error} ms={latency_ms}")
        return {"error": f"voice model {error}", "latency_ms": latency_ms}
    return {"model": hop.model, "profile": hop.profile_name, "latency_ms": latency_ms, "cost_usd": round(cost, 6),
            "tool": tool, "args": args, "_finish": finish}


def _find_device(name: str, devices: list[dict[str, Any]]) -> dict[str, Any] | None:
    wanted = (name or "").strip().lower()
    matches = [d for d in devices if str(d.get("device_name") or "").strip().lower() == wanted]
    return matches[0] if len(matches) == 1 else None


def to_hint(command: dict[str, Any], *, devices: list[dict[str, Any]], host_name: str, device_id: str,
            userinterface_name: str) -> dict[str, Any]:
    """Turn a classified voice command into an Atlas quick-step hint with the real tool arguments.

    Nothing runs here: the browser sends the words to the Atlas session with the hint, and Atlas's quick step
    validates and runs it there, so the action is in the chat and Atlas remembers it (TASK-140 Q5).
    """
    tool, args = command.get("tool"), command.get("args") or {}
    if tool == "abort":
        return {"action": "abort"}
    if tool == "navigate_to_page":
        page = str(args.get("page") or "").lower()
        if page not in PAGES:
            return {"action": "atlas", "reason": "unknown page"}
        return {"action": "hint", "hint": {"tool": "navigate_to_page", "args": {"page_name": page}}}
    if tool not in ("take_control", "navigate_to_node"):
        return {"action": "atlas"}

    target = None
    if args.get("device"):
        target = _find_device(str(args["device"]), devices)
        if target is None:
            # Named a device we cannot resolve exactly: never substitute (BUG-0323 / BUG-0355).
            return {"action": "atlas", "reason": f"device '{args['device']}' not found"}
    elif host_name and device_id:
        target = {"host_name": host_name, "device_id": device_id}
    if not target:
        return {"action": "atlas", "reason": "no device"}

    params: dict[str, Any] = {"host_name": target.get("host_name"), "device_id": target.get("device_id")}
    if tool == "navigate_to_node":
        ui = userinterface_name or str(target.get("userinterface_name") or "")
        if not ui or not args.get("node"):
            return {"action": "atlas", "reason": "no interface or node"}
        params.update(userinterface_name=ui, target_node_label=str(args["node"]))
    return {"action": "hint", "hint": {"tool": tool, "args": params}}


# ------------------------------------------------------------------ spoken answers (TASK-140, owner's voice pick)

SPEAK_USAGE = "agent.voice.speak"
SPEAK_PROFILE = "voice-speech"            # MiniMax speech-2.6-turbo on the minimax endpoint
SPEAK_VOICE = "English_Trustworth_Man"   # owner's pick, also for French and German (language_boost)
_BOOST = {"fr": "French", "de": "German"}


def speak(*, text: str, lang: str, speed: float, team_id: str) -> tuple[bytes | None, str]:
    """MiniMax text-to-speech → (mp3 bytes, error). Recorded in the AI call log (tokens_in = characters) and Langfuse."""
    words = " ".join((text or "").split())[:1000]
    if not words:
        return None, "no text"
    try:
        resolution = dataclasses.replace(ai_router.resolve_profile(SPEAK_PROFILE, SPEAK_USAGE, team_id=team_id), label="")
    except Exception as exc:  # noqa: BLE001 - routing errors are reported as-is
        return None, f"voice not available: {exc}"
    hop = resolution.primary
    key = get_secret(hop.endpoint.get("secret_name"))
    base = urlsplit(hop.base_url or "")
    if not key or not base.netloc:
        return None, f"no key for the '{hop.endpoint_name}' AI endpoint"
    body = {"model": hop.model, "text": words, "stream": False, "language_boost": _BOOST.get(lang[:2], "English"),
            "voice_setting": {"voice_id": SPEAK_VOICE, "speed": max(0.5, min(2.0, float(speed or 1.2)))},
            "audio_setting": {"format": "mp3", "sample_rate": 24000, "bitrate": 64000}}
    attempt = ai_tracing.Attempt(hop)
    started = time.time()
    audio, error = None, ""
    try:
        resp = requests.post(f"{base.scheme}://{base.netloc}/v1/t2a_v2", json=body, timeout=20,
                             headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
        data = resp.json() if resp.status_code == 200 else {}
        status = (data.get("base_resp") or {}).get("status_code")
        hex_audio = (data.get("data") or {}).get("audio")
        if resp.status_code != 200:
            error = f"HTTP {resp.status_code}"
        elif status or not hex_audio:
            error = f"MiniMax {status}: {(data.get('base_resp') or {}).get('status_msg', 'no audio')}"
        else:
            audio = bytes.fromhex(hex_audio)
    except (requests.RequestException, ValueError) as exc:
        error = exc.__class__.__name__
    ms = int((time.time() - started) * 1000)
    ok = audio is not None
    usage = CallUsage(tokens_in=len(words), tokens_out=0)
    attempt.finish(ok=ok, output=f"{len(audio or b'')} bytes mp3" if ok else None, error=error or None,
                   tokens=(len(words), 0), usage=usage)
    ai_router.record(resolution, hop, ok=ok, ms=ms, tokens_in=len(words), tokens_out=0, usage=usage,
                     error_type=None if ok else "other", extra={"chars": len(words)})
    ai_tracing.trace_call(name="Atlas voice answer", usage=SPEAK_USAGE, input=words, attempts=[attempt],
                          resolution=resolution, output=f"{len(audio or b'')} bytes mp3" if ok else None, ok=ok,
                          error=error or None, team_id=team_id,
                          extra={"voice": SPEAK_VOICE, "speed": body["voice_setting"]["speed"], "chars": len(words)})
    print(f"[VOICE] speak chars={len(words)} lang={lang} speed={body['voice_setting']['speed']} ok={ok} "
          f"ms={ms}" + (f" error={error}" if error else ""))
    return audio, error
