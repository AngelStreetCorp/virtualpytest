"""TASK-134: local relay between the game box and the Anthropic API, so the API key never leaves this machine.

Run on the Mac (key from the repo .env, never printed):  python3 scripts/lol_practice/llm_relay.py [port]
Reach it from vpt-windows with a reverse tunnel:        ssh -R 8787:127.0.0.1:8787 vpt-windows
POST /decide {model, system, user, image_b64?, schema: act|coach}  ->  {text, api_ms, in_tokens, out_tokens, cache_read, cost_usd, stop}
POST /jev {state, options:[{id,facts}], instructions} -> {choice, confidence, probabilities, api_ms, in_tokens, out_tokens, cost_usd}
Only claude-haiku-5-5 and claude-sonnet-5-5 are accepted; there is no substitution: an API error is returned as an error.
"""
import base64  # noqa: F401
import json
import os
import sys
import ssl
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")))
from shared.src.lib.ai import gateway  # noqa: E402
from shared.src.lib.ai.provider_client import CallUsage, anthropic_call_usage  # noqa: E402


def _report(usage: str, endpoint: str, model: str, used, ok: bool, ms: int) -> None:
    """Every relay call is logged in ai_calls (BUG-0721), in a thread so the game loop never waits on it."""
    import threading
    threading.Thread(target=gateway.report_external_call, args=(usage,), daemon=True, kwargs=dict(
        endpoint=endpoint, model=model, call_usage=used, ok=ok, ms=ms, script="lol_practice/llm_relay.py",
        error_type=None if ok else "other")).start()

# $ per million tokens (input, output, cache read, cache write 5 min), Anthropic list prices 2026-10
PRICES = {"claude-haiku-5-5": (0.10, 0.50, 0.01, 0.125), "claude-sonnet-5-5": (2.0, 10.0, 0.20, 2.5)}
# Haiku 5.5 may switch thinking off; Sonnet 5.5 rejects "disabled", so "between_tools" (no thinking before the answer) is used
THINKING = {"claude-haiku-5-5": {"type": "disabled"}, "claude-sonnet-5-5": {"type": "between_tools"}}
CTX = ssl.create_default_context(cafile="/etc/ssl/cert.pem") if os.path.exists("/etc/ssl/cert.pem") else None
# Structured output: the reply is always one JSON object {a, t}; a malformed or truncated reply is impossible (harness defect fixed 2026-10-18,
# Haiku had 12 % unparseable replies when it reasoned in text)
ACTIONS = ["last_hit", "attack", "q", "e", "r", "move_lane", "retreat", "recall", "wait"]
SCHEMA = {"type": "object", "properties": {"a": {"type": "string", "enum": ACTIONS}, "t": {"type": ["string", "null"]}},
          "required": ["a", "t"], "additionalProperties": False}
# Round 2: the coach answers with a strategy object instead of one action
STRATEGIES = ["farm_safe", "push", "freeze", "fight", "avoid"]
COACH_SCHEMA = {"type": "object", "properties": {"mode": {"type": "string", "enum": STRATEGIES}, "recall_now": {"type": "boolean"},
                                                 "buy": {"type": ["string", "null"]}, "reason": {"type": "string"}},
                "required": ["mode", "recall_now", "buy", "reason"], "additionalProperties": False}
SCHEMAS = {"act": SCHEMA, "coach": COACH_SCHEMA}
KEY = os.environ.get("ANTHROPIC_API_KEY", "")
OR_KEY = os.environ.get("OPENROUTER_API_KEY", "")


def call(model: str, system: str, user: str, image_b64: str = "", schema: str = "act") -> dict:
    content = [{"type": "text", "text": user}]
    if image_b64:
        content.insert(0, {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": image_b64}})
    body = {"model": model, "max_tokens": 200 if schema == "act" else 300, "system": system, "messages": [{"role": "user", "content": content}],
            "thinking": THINKING[model],
            "output_config": {"effort": "low", "format": {"type": "json_schema", "schema": SCHEMAS[schema]}}}
    req = urllib.request.Request("https://api.anthropic.com/v1/messages", data=json.dumps(body).encode(), headers={
        "x-api-key": KEY, "anthropic-version": "2023-06-01", "content-type": "application/json"})
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=30, context=CTX) as r:  # noqa: S310
            out = json.loads(r.read())
    except Exception:
        _report("external:lol.relay", "anthropic", model, CallUsage(), False, int((time.monotonic() - t0) * 1000))
        raise
    ms = int((time.monotonic() - t0) * 1000)
    u = out.get("usage") or {}
    _report("external:lol.relay", "anthropic", model, anthropic_call_usage(u), True, ms)
    pi, po, pcr, pcw = PRICES[model]
    inp, outp = u.get("input_tokens", 0), u.get("output_tokens", 0)
    cr, cw = u.get("cache_read_input_tokens", 0) or 0, u.get("cache_creation_input_tokens", 0) or 0
    cost = (inp * pi + outp * po + cr * pcr + cw * pcw) / 1e6
    text = "".join(b.get("text", "") for b in out.get("content", []) if b.get("type") == "text")
    return {"text": text, "api_ms": ms, "in_tokens": inp + cr + cw, "out_tokens": outp, "cache_read": cr,
            "cost_usd": round(cost, 7), "stop": out.get("stop_reason")}


def jev(state, options, instructions: str) -> dict:
    """typesafe/jev-1.13 on OpenRouter's decisions API, the payload shared/src/lib/ai/decisions.py builds (one typed choice question)."""
    body = {"model": "typesafe/jev-1.13", "state": state, "session_id": "task134-bench",
            "questions": {"choice": {"type": "choice", "instructions": instructions,
                                     "criteria": {str(o["id"]): str(o.get("facts") or o["id"]) for o in options}}}}
    req = urllib.request.Request("https://openrouter.ai/api/alpha/decisions", data=json.dumps(body).encode(), headers={
        "Authorization": "Bearer " + OR_KEY, "Content-Type": "application/json"})
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=20, context=CTX) as r:  # noqa: S310
            out = json.loads(r.read())
    except Exception:
        _report("external:lol.relay.jev", "openrouter", "typesafe/jev-1.13", CallUsage(), False,
                int((time.monotonic() - t0) * 1000))
        raise
    ms = int((time.monotonic() - t0) * 1000)
    a = (out.get("answers") or {}).get("choice") or {}
    u = out.get("usage") or {}
    _report("external:lol.relay.jev", "openrouter", "typesafe/jev-1.13",
            CallUsage(tokens_in=int(u.get("input_tokens") or 0), tokens_out=int(u.get("output_tokens") or 0),
                      cost=float(u["cost"]) if isinstance(u.get("cost"), (int, float)) else None), True, ms)
    return {"choice": a.get("choice"), "confidence": a.get("confidence"), "probabilities": a.get("probabilities") or {},
            "api_ms": ms, "in_tokens": u.get("input_tokens", 0), "out_tokens": u.get("output_tokens", 0),
            "cost_usd": u.get("cost") or 0.0, "model": out.get("model")}


class H(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        try:
            req = json.loads(self.rfile.read(int(self.headers.get("content-length", 0))))
            if self.path.startswith("/jev"):
                res, code = jev(req["state"], req["options"], req.get("instructions", "Which option now?")), 200
            else:
                if req.get("model") not in PRICES:
                    raise ValueError("model not allowed")
                res, code = call(req["model"], req["system"], req["user"], req.get("image_b64") or "", req.get("schema", "act")), 200
        except Exception as e:  # noqa: BLE001
            res, code = {"error": f"{type(e).__name__}: {e}"[:300]}, 502
        data = json.dumps(res).encode()
        self.send_response(code)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *a):  # silent
        pass


if __name__ == "__main__":
    if not KEY or not OR_KEY:
        sys.exit("ANTHROPIC_API_KEY and OPENROUTER_API_KEY must be in the environment")
    ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1]) if len(sys.argv) > 1 else 8787), H).serve_forever()
