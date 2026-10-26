"""
AI gateway (TASK-30 §3.6) — the one entry point for single-shot AI calls.

``complete(usage, prompt, ...)`` resolves the usage, calls the model and walks the
fallback chain on error / empty answer. Where the call runs depends on the process:

- **Server processes** (backend_server, discard_worker, server scripts) call
  ``use_local_routing()`` at startup: they resolve from the DB and call providers
  in-process, holding the API keys.
- **Hosts** (the default) POST to the server's ``/server/ai/complete``. Hosts hold no
  provider keys. When the chosen endpoint is ``reach=host`` (a keyless GPU on the
  hosts' LAN that the server cannot see), the server answers with the endpoint
  description and the host calls it itself, then reports stats back; if that direct
  call fails, the host asks the server to continue down the fallback chain.

Result dict (unchanged shape for existing callers, plus routing info):
``{success, content, error, usage{prompt,completion,total}_tokens, provider_used,
model, profile, endpoint, via, split_arm, fallback_used}``.
"""

from __future__ import annotations

import base64
import os
import threading
import time
from typing import Any, Callable, Optional

from . import budgets, call_log, router, tracing, usages
from .budgets import CallerContext
from . import caller as ai_caller
from .config import get_preset
from .usages import UnknownUsageError

EMPTY_RETRIES = 2
RETRY_SLEEP_S = 3
# A free model that the provider rate-limits (HTTP 429) is worth waiting for: the request was refused, so nothing
# was billed, and the next attempt costs nothing either. The account behind the free plan is shared with the paid
# models of the same provider, so a burst elsewhere can throttle it for minutes (2026-10-23: every Flash call
# answered 429 for an hour). A metered model is never waited for: the caller moves on to its fallback chain.
RATE_LIMIT_RETRIES = int(os.environ.get("AI_RATE_LIMIT_RETRIES", "2"))
RATE_LIMIT_BACKOFF_S = tuple(float(x) for x in os.environ.get("AI_RATE_LIMIT_BACKOFF_S", "5,20").split(",") if x)
# Hosts shrink frames before upload so the JSON body stays well under proxy limits
# (nginx default client_max_body_size is 1 MB; a 1920px JPEG is ~200-400 KB).
HOST_UPLOAD_MAX_EDGE = 1920
REMOTE_TIMEOUT_S = 330
# Extra seconds a host waits for the server beyond the call's own budget (routing, upload).
BUDGET_MARGIN_S = 15
DIRECT_CACHE_TTL_S = 60

_local_routing = False
_semaphores: dict[str, threading.BoundedSemaphore] = {}
_semaphores_lock = threading.Lock()
_remote_cache: dict[tuple, tuple[float, Any]] = {}


def use_local_routing() -> None:
    """Mark this process as a server process (resolves + calls providers itself)."""
    global _local_routing
    _local_routing = True


def is_local_routing() -> bool:
    return _local_routing


def _host_context(context: Optional[dict]) -> dict:
    ctx = dict(context or {})
    if not _local_routing and not ctx.get("host_name") and os.getenv("HOST_NAME"):
        ctx["host_name"] = os.getenv("HOST_NAME")
    return {k: v for k, v in ctx.items() if v}


def _resize_b64(image_b64: str, media_type: str, max_edge: Optional[int]) -> tuple[str, str]:
    """Downscale a base64 image so its long edge is <= max_edge (JPEG out). No-op if smaller."""
    if not max_edge:
        return image_b64, media_type
    try:
        import cv2
        import numpy as np
        img = cv2.imdecode(np.frombuffer(base64.b64decode(image_b64), np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            return image_b64, media_type
        h, w = img.shape[:2]
        if max(h, w) <= max_edge:
            return image_b64, media_type
        scale = max_edge / float(max(h, w))
        img = cv2.resize(img, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA)
        ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 88])
        return (base64.b64encode(buf.tobytes()).decode(), "image/jpeg") if ok else (image_b64, media_type)
    except Exception as e:
        print(f"[AI_GATEWAY] image resize skipped: {e}")
        return image_b64, media_type


def _semaphore(hop: router.Hop) -> Optional[threading.BoundedSemaphore]:
    limit = hop.endpoint.get("max_concurrency")
    if not limit:
        return None
    with _semaphores_lock:
        key = f"{hop.endpoint_name}:{limit}"
        if key not in _semaphores:
            _semaphores[key] = threading.BoundedSemaphore(int(limit))
        return _semaphores[key]


def _usage_dict(tokens: tuple[int, int], used: Any = None) -> dict:
    """The result's ``usage``: ``prompt_tokens`` is the whole prompt; the cache_* counts are the part of it
    read from / written to the prompt cache (priced apart, see ``prices.compute``)."""
    return {
        "prompt_tokens": tokens[0],
        "completion_tokens": tokens[1],
        "total_tokens": tokens[0] + tokens[1],
        "cache_read_tokens": int(getattr(used, "cache_read", 0) or 0),
        "cache_write_tokens": int(getattr(used, "cache_write", 0) or 0),
    }


def _result(ok: bool, *, content: str = "", error: str = "", hop: Optional[router.Hop] = None,
            resolution: Optional[router.Resolution] = None, tokens: tuple[int, int] = (0, 0),
            fallback_used: bool = False, sources: Optional[list] = None, busy: bool = False,
            used: Any = None) -> dict:
    return {
        "success": ok,
        "content": content,
        "error": error,
        "usage": _usage_dict(tokens, used),
        "provider_used": hop.preset if hop else "none",
        "model": hop.model if hop else None,
        "profile": hop.profile_name if hop else None,
        "endpoint": hop.endpoint_name if hop else None,
        "via": resolution.via_key if resolution else None,
        "split_arm": resolution.split_arm if resolution else "",
        "request_id": resolution.request_id if resolution else None,
        "fallback_used": fallback_used,
        "sources": sources or [],
        # True when the call ran out of its timeout_s budget (endpoint slot or answer): the
        # model is saturated, not broken — callers with a budget back off and retry later.
        "busy": busy,
    }


def _budget_blocked(resolution: router.Resolution) -> bool:
    """Walk every AI budget bucket that may apply to this call (TASK-87 phase 5 / BUG-0559).

    The resolution has the team_id, usage, primary hop's model + endpoint. The X-VPT-Caller
    context (when bound) adds user_id and project_id. The resolver picks the most-specific
    matching bucket and refuses the call if any block bucket is over its limit."""
    try:
        hop = resolution.primary
        caller_ctx = ai_caller.current() or {}
        ctx = CallerContext(
            team_id=resolution.team_id,
            user_id=caller_ctx.get('user_id') or None,
            usage_key=resolution.usage,
            model=(hop.model if hop else None),
            endpoint=((hop.endpoint or {}).get('name') or (hop.endpoint or {}).get('id')) if hop else None,
            project_id=caller_ctx.get('project_id') or None,
        )
        return budgets.blocked(ctx)
    except Exception:
        return budgets.blocked_team(resolution.team_id)


def _is_timeout(exc: BaseException) -> bool:
    try:
        import requests
        if isinstance(exc, requests.exceptions.Timeout):
            return True
    except ImportError:  # pragma: no cover
        pass
    try:
        import httpx
        if isinstance(exc, httpx.TimeoutException):
            return True
    except ImportError:  # pragma: no cover
        pass
    import anthropic
    return isinstance(exc, anthropic.APITimeoutError)


def needs_web(usage: str) -> bool:
    """True when ``usage`` must be answered with a live web search (never without one)."""
    try:
        return "web" in usages.needs(usage)
    except UnknownUsageError:
        return False


def web_mechanism(hop: router.Hop) -> Optional[str]:
    return get_preset(hop.preset).web_search


def _call_hop(hop: router.Hop, usage: str, prompt: str, image_b64: Optional[str], media_type: str,
              system: Optional[str], max_tokens: int, temperature: Optional[float],
              timeout_s: Optional[int] = None,
              on_attempt: Optional[Callable[[bool, int, Any, str, Optional[str]], None]] = None) -> tuple[str, tuple[int, int], list]:
    """One hop, with the empty-answer retries. Returns (text, tokens, sources); raises on provider
    error or refusal (``ModelRefusal``: no retry on the same hop, the caller moves to the next).

    ``on_attempt(answered, ms, call_usage, text, stop_reason)`` fires after every billed response, so an empty answer
    that is retried is counted too (each attempt is billed)."""
    from .provider_client import (raise_on_refusal, response_sources, response_text, response_tokens,
                                  response_usage, single_completion, normalize_stop_reason)

    if image_b64 is not None:
        image_b64, media_type = _resize_b64(image_b64, media_type, hop.image_max_edge)
    client = hop.client(timeout=timeout_s) if timeout_s else hop.client()
    web = web_mechanism(hop) if needs_web(usage) else None
    tokens = (0, 0)
    retries = 0 if hop.preset == "minimax_vlm" else EMPTY_RETRIES  # BUG-0515: the same image answers empty again
    for attempt in range(retries + 1):
        attempt_started = time.time()
        resp = raise_on_refusal(single_completion(
            client,
            model=hop.model,
            prompt=prompt,
            image_b64=image_b64,
            media_type=media_type,
            system=system,
            max_tokens=hop.max_tokens(max_tokens),
            temperature=hop.temperature(temperature),
            extra_body=hop.extra_body(usage),
            web_search=web,
        ))
        tokens = response_tokens(resp)
        text = response_text(resp)
        if on_attempt:
            on_attempt(bool(text), int((time.time() - attempt_started) * 1000), response_usage(resp), text,
                       normalize_stop_reason(resp))
        if text:
            return text, tokens, response_sources(resp)
        if attempt < retries and not router.breaker_open_for(usage, hop):
            print(f"[AI_GATEWAY] {usage}: empty answer from {hop.profile_name} "
                  f"(attempt {attempt + 1}/{retries + 1}) - retrying")
            time.sleep(RETRY_SLEEP_S)
        elif attempt < retries:
            break  # best-effort usage: the breaker opened on this empty answer, no more paid retries
    return "", tokens, []


def _format_error(hop: router.Hop, exc: Exception) -> str:
    try:
        import requests
        if isinstance(exc, requests.HTTPError) and exc.response is not None:
            return (f"{hop.endpoint_name} ({hop.preset}) HTTP {exc.response.status_code} "
                    f"for model '{hop.model}': {(exc.response.text or '')[:300]}")
    except Exception:
        pass
    return f"{hop.endpoint_name} ({hop.preset}) call failed for model '{hop.model}': {exc}"


def execute(resolution: router.Resolution, prompt: str, *, image_b64: Optional[str] = None,
            media_type: str = "image/jpeg", system: Optional[str] = None, max_tokens: int = 1000,
            temperature: Optional[float] = 0.0, start: int = 0, timeout_s: Optional[int] = None) -> dict:
    """Run a resolved call on this process, trying ``resolution.hops[start:]`` in order.

    ``timeout_s`` is the caller's budget per hop: at most that long waiting for a free slot on a
    ``max_concurrency`` endpoint and at most that long for the answer. Running out of it
    returns ``busy=True`` instead of queueing behind other callers for minutes.

    Host-reach endpoints are skipped here (the server cannot reach them); the gateway
    route hands those to the host instead. Every call is traced to Langfuse (one trace,
    one generation per attempted hop).
    """
    if _budget_blocked(resolution):
        # A team (or finer bucket — usage / model / endpoint / user / project) over its blocking
        # monthly budget gets no model call (TASK-87 phase 4 + BUG-0559 phase 5).
        return {**_result(False, error=budgets.BLOCKED_MESSAGE, resolution=resolution), "budget_blocked": True}
    attempts: list[tracing.Attempt] = []
    result = _execute_hops(resolution, prompt, attempts, image_b64=image_b64, media_type=media_type,
                           system=system, max_tokens=max_tokens, temperature=temperature, start=start,
                           timeout_s=timeout_s)
    trace_input: dict = {"prompt": prompt}
    if system:
        trace_input["system"] = system
    if image_b64 is not None:
        trace_input["image"] = tracing.IMAGE_PLACEHOLDER.format(media_type=media_type)
    # The Langfuse trace id is the call's request id and comes back in the result, so
    # whoever stores the frame (a TASK-27 training sample) can link it to the trace.
    trace_id = resolution.request_id
    tracing.trace_call(
        name=f"AI {resolution.stats_label}",
        usage=resolution.stats_label,
        trace_id=trace_id,
        input=trace_input,
        attempts=attempts,
        resolution=resolution,
        output=result.get("content") or None,
        ok=bool(result.get("success")),
        error=result.get("error") or None,
        team_id=resolution.team_id,
        session_id=resolution.request_id,
    )
    result["trace_id"] = trace_id if tracing.enabled() else None
    return result


def _execute_hops(resolution: router.Resolution, prompt: str, attempts: list, *, image_b64: Optional[str],
                  media_type: str, system: Optional[str], max_tokens: int, temperature: Optional[float],
                  start: int, timeout_s: Optional[int] = None) -> dict:
    errors: list[str] = []
    last_hop: Optional[router.Hop] = None
    busy = False
    web = needs_web(resolution.usage)
    limited = False  # an earlier hop answered HTTP 429 (best-effort usages stop there, see skip_after_rate_limit)
    billed = [0]  # billed requests so far in this call (attempt_index of the next one)
    image_extra = ({"images": 1, "image_bytes": len(image_b64) * 3 // 4} if image_b64 is not None else {})
    for index, hop in enumerate(resolution.hops[start:], start=start):
        fallback = resolution.is_fallback(hop)
        if hop.reach == "host":
            errors.append(f"{hop.endpoint_name}: only reachable from hosts")
            router.record(resolution, hop, ok=False, ms=0, fallback=fallback, outcome="skipped",
                          attempt_index=billed[0])
            continue
        if web and not web_mechanism(hop):
            # Never answer a web usage from model memory: that is how invented facts reach the UI.
            errors.append(f"{hop.endpoint_name} ({hop.preset}): cannot search the web")
            router.record(resolution, hop, ok=False, ms=0, fallback=fallback, outcome="skipped",
                          attempt_index=billed[0])
            continue
        if router.skip_paused(resolution, hop, errors, fallback=fallback, attempt_index=billed[0]):
            # No request is made, so nothing is billed: the 402 that started the pause was.
            continue
        if router.skip_down(resolution, hop, errors, fallback=fallback, attempt_index=billed[0]):
            continue
        if router.skip_after_rate_limit(resolution, hop, errors, fallback=fallback, limited=limited,
                                        attempt_index=billed[0]):
            continue
        if router.skip_breaker(resolution, hop, errors, fallback=fallback, attempt_index=billed[0]):
            continue
        last_hop = hop
        attempt = tracing.Attempt(hop)
        attempt.fallback = fallback
        attempts.append(attempt)
        sem = _semaphore(hop)
        started = time.time()
        acquired = sem.acquire(timeout=timeout_s) if sem and timeout_s else (sem.acquire() if sem else True)
        if not acquired:
            # Every slot of this endpoint stayed taken for the whole budget: saturated. Nothing was
            # billed, but the hop was skipped, so it counts as a failed hop (error_type busy).
            busy = True
            errors.append(f"{hop.endpoint_name}: busy (no free slot within {timeout_s}s)")
            attempt.finish(ok=False, error=errors[-1])
            router.record(resolution, hop, ok=False, ms=int((time.time() - started) * 1000), fallback=fallback,
                          error_type="busy", attempt_index=billed[0])
            continue
        recorded = [0]

        def _on_attempt(answered: bool, ms: int, call_usage: Any, text: str, stop_reason: Optional[str], _hop=hop,
                        _fb=fallback, _rec=recorded) -> None:
            _rec[0] += 1
            router.note_empty(resolution.usage, _hop, answered)
            attempt.usage = call_usage
            extra = {**image_extra, "parse_ok": call_log.parse_ok_for(resolution.usage, text, answered),
                     "stop_reason": stop_reason}
            router.record(resolution, _hop, ok=answered, ms=ms, tokens_in=call_usage.tokens_in,
                          tokens_out=call_usage.tokens_out, fallback=_fb, usage=call_usage,
                          error_type=None if answered else "empty_answer", attempt_index=billed[0], extra=extra)
            billed[0] += 1

        # A free model that the provider throttles is waited for (see RATE_LIMIT_RETRIES): the request was
        # refused, so nothing was billed and the next attempt is free too.
        from . import prices as _prices
        rate_limit_retries = RATE_LIMIT_RETRIES if _prices.is_free(hop) else 0
        failed = False
        try:
            while True:
                try:
                    text, tokens, sources = _call_hop(hop, resolution.usage, prompt, image_b64, media_type, system,
                                                      max_tokens, temperature, timeout_s, on_attempt=_on_attempt)
                    break
                except Exception as e:
                    from .provider_client import RequestNotSent, classify_error, is_connection_error, response_usage
                    ms = int((time.time() - started) * 1000)
                    if (classify_error(e) == "rate_limit" and rate_limit_retries > 0
                            and not isinstance(e, RequestNotSent)):
                        # The provider refused the request (HTTP 429): nothing was billed. The model is free, so
                        # waiting for the next slot costs nothing: try this same hop again. The refused request
                        # is logged like any other request (it was made, it was not billed).
                        router.record(resolution, hop, ok=False, ms=ms, fallback=fallback,
                                      error_type="rate_limit", attempt_index=billed[0], extra=image_extra)
                        billed[0] += 1
                        rate_limit_retries -= 1
                        index = min(RATE_LIMIT_RETRIES - rate_limit_retries - 1, len(RATE_LIMIT_BACKOFF_S) - 1)
                        delay = RATE_LIMIT_BACKOFF_S[index]
                        errors.append(f"{hop.endpoint_name}: rate limited (HTTP 429), retrying in {delay:.0f}s")
                        print(f"[AI] rate limited on {hop.endpoint_name}/{hop.model}: retrying in {delay:.0f}s "
                              f"({rate_limit_retries} left)")
                        time.sleep(delay)
                        continue
                    if isinstance(e, RequestNotSent):  # refused by our own client: no request left, nothing billed
                        errors.append(_format_error(hop, e))
                        router.record(resolution, hop, ok=False, ms=0, fallback=fallback, outcome="skipped",
                                      error_type=classify_error(e), attempt_index=billed[0],
                                      extra={"stop_reason": "not_sent"})
                        attempt.finish(ok=False, error=errors[-1])
                        failed = True
                        break
                    # A refusal is a billed response: keep its tokens.
                    refused = getattr(e, "response", None) if type(e).__name__ == "ModelRefusal" else None
                    router.record(resolution, hop, ok=False, ms=ms, fallback=fallback,
                                  usage=response_usage(refused) if refused is not None else None,
                                  tokens_in=response_usage(refused).tokens_in if refused is not None else 0,
                                  tokens_out=response_usage(refused).tokens_out if refused is not None else 0,
                                  error_type=classify_error(e), attempt_index=billed[0], extra=image_extra)
                    billed[0] += 1
                    if classify_error(e) == "rate_limit":
                        limited = True
                    if is_connection_error(e):
                        router.mark_down(hop)
                    elif timeout_s and _is_timeout(e):
                        busy = True
                    errors.append(_format_error(hop, e))
                    attempt.finish(ok=False, error=errors[-1])
                    failed = True
                    break
        finally:
            if sem:
                sem.release()
        if failed:
            continue
        router.mark_up(hop)
        if text:
            attempt.finish(ok=True, output=text, tokens=tokens)
            return _result(True, content=text, hop=hop, resolution=resolution, tokens=tokens,
                           fallback_used=fallback, sources=sources, used=attempt.usage)
        errors.append(f"{hop.endpoint_name}: empty answer from '{hop.model}'")
        attempt.finish(ok=False, error=errors[-1], tokens=tokens)
    return _result(False, error="; ".join(errors) or "no usable AI profile", hop=last_hop,
                   resolution=resolution, busy=busy)


def complete(usage: str, prompt: str, *, image_b64: Optional[str] = None, media_type: str = "image/jpeg",
             system: Optional[str] = None, max_tokens: int = 1000, temperature: Optional[float] = 0.0,
             team_id: Optional[str] = None, context: Optional[dict] = None,
             timeout_s: Optional[int] = None) -> dict:
    """Single-shot completion for ``usage``. Never raises; failures come back as success=False.

    ``timeout_s``: see ``execute`` (a result with ``busy=True`` means "saturated, retry later").
    """
    context = _host_context(context)
    if _local_routing:
        try:
            resolution = router.resolve(usage, team_id, context)
        except (router.AIRoutingError, UnknownUsageError) as e:
            print(f"[AI_GATEWAY] ❌ {usage}: {e}")
            tracing.trace_call(name=f"AI {usage}", usage=usage, input={"prompt": prompt}, attempts=[],
                               ok=False, error=str(e), team_id=team_id)
            return _result(False, error=str(e))
        return execute(resolution, prompt, image_b64=image_b64, media_type=media_type, system=system,
                       max_tokens=max_tokens, temperature=temperature, timeout_s=timeout_s)
    return _complete_remote(usage, prompt, image_b64=image_b64, media_type=media_type, system=system,
                            max_tokens=max_tokens, temperature=temperature, team_id=team_id, context=context,
                            timeout_s=timeout_s)


# ------------------------------------------------------------------------- host side
def _server_post(path: str, payload: dict, timeout: int) -> dict:
    import requests
    from shared.src.lib.utils.build_url_utils import buildServerUrl, server_auth_headers
    response = requests.post(buildServerUrl(path), json=payload, headers=server_auth_headers(), timeout=timeout)
    try:
        data = response.json()
    except ValueError:
        data = {"success": False, "error": f"HTTP {response.status_code}: {response.text[:300]}"}
    if response.status_code >= 400 and "error" not in data:
        data["error"] = f"HTTP {response.status_code}"
    return data


def _complete_remote(usage: str, prompt: str, *, image_b64: Optional[str], media_type: str,
                     system: Optional[str], max_tokens: int, temperature: Optional[float],
                     team_id: Optional[str], context: dict, timeout_s: Optional[int] = None) -> dict:
    if image_b64 is not None:
        image_b64, media_type = _resize_b64(image_b64, media_type, HOST_UPLOAD_MAX_EDGE)
    payload = {
        "usage": usage,
        "prompt": prompt,
        "image_b64": image_b64,
        "media_type": media_type,
        "system": system,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "team_id": team_id,
        "context": context,
    }
    wait = REMOTE_TIMEOUT_S
    if timeout_s:
        payload["timeout_s"] = timeout_s
        # One slot wait + one answer per hop, plus a margin; never longer than the default.
        wait = min(REMOTE_TIMEOUT_S, 2 * timeout_s + BUDGET_MARGIN_S)
    try:
        data = _server_post("/server/ai/complete", payload, wait)
    except Exception as e:
        if timeout_s and _is_timeout(e):
            return _result(False, error=f"AI gateway: no answer within {wait}s", busy=True)
        return _result(False, error=f"AI gateway unreachable: {e}")
    direct = data.get("direct")
    if not direct:
        return {**_result(False), **data}
    # The server says: this endpoint is only reachable from hosts — call it here.
    result = _call_direct(direct, usage, payload, team_id)
    if result.get("success"):
        return result
    try:
        data = _server_post("/server/ai/complete", {**payload, "start": 1, "direct_error": result.get("error")},
                            REMOTE_TIMEOUT_S)
    except Exception as e:
        return _result(False, error=f"{result.get('error')}; AI gateway unreachable: {e}")
    return {**_result(False), **data}


def report_direct_call(usage: str, team_id: Optional[str], hop_info: dict, *, split_arm: str = "", ok: bool,
                       ms: int, call_usage: Any, error_type: Optional[str] = None,
                       fallback_used: bool = False, request_id: Optional[str] = None,
                       extra: Optional[dict] = None) -> None:
    """Tell the server about a call this host made straight to a host-reach endpoint, so it is counted."""
    try:
        _server_post("/server/ai/stats", {
            "usage": usage, "team_id": team_id, "profile": hop_info["profile"], "endpoint": hop_info["endpoint"],
            "split_arm": split_arm, "ok": ok, "ms": ms, "fallback": fallback_used, "error_type": error_type,
            "model": hop_info.get("model"), "request_id": request_id, "extra": extra or {},
            "tokens_in": call_usage.tokens_in, "tokens_out": call_usage.tokens_out,
            "tokens_cache_read": call_usage.cache_read, "tokens_cache_write": call_usage.cache_write,
            "tokens_reasoning": call_usage.reasoning, "web_searches": call_usage.web_searches,
            "cost": call_usage.cost,
        }, 10)
    except Exception as e:
        print(f"[AI_GATEWAY] stats report failed: {e}")


def _load_server_env() -> None:
    """SERVER_URL / API_KEY for a plain script (Mac bench, LoL relay) from the main checkout's .env, if unset.
    Only those two keys are read; nothing is printed or exported beyond this process."""
    if os.environ.get("SERVER_URL") and os.environ.get("API_KEY"):
        return
    here = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", ".."))
    for path in (os.path.expanduser("~/virtualpytest/.env"), os.path.join(here, ".env")):
        if not os.path.exists(path):
            continue
        for line in open(path, encoding="utf-8", errors="ignore"):
            k, _, v = line.strip().partition("=")
            if k in ("SERVER_URL", "API_KEY") and v and not os.environ.get(k):
                os.environ[k] = v.strip().strip("'\"")
        return


def report_external_call(usage: str, *, endpoint: str, model: str, call_usage: Any, ok: bool, ms: int,
                         script: str, error_type: Optional[str] = None, team_id: Optional[str] = None) -> None:
    """Log a call a script made with its own client (a bench, the LoL relay, a Mac-side review) in ``ai_calls``.

    Prefer ``gateway.complete``; this is for callers that must hit a provider themselves (a pinned model, a body the
    gateway does not build). ``usage`` is the stats label (``external:<what>``), ``endpoint`` the ai_endpoints name
    whose price applies (``anthropic``, ``openrouter``, ``minimax``), ``call_usage`` a ``CallUsage``
    (``anthropic_call_usage`` / ``openai_call_usage``). The row goes through ``POST /server/ai/stats`` with
    ``origin=script`` and ``script_name``. Never raises."""
    try:
        _load_server_env()
        with ai_caller.bound(origin="script", script_name=script):
            _server_post("/server/ai/stats", {
                "usage": usage, "team_id": team_id, "profile": f"external:{script}", "endpoint": endpoint,
                "model": model, "ok": ok, "ms": ms, "fallback": False, "error_type": error_type,
                "tokens_in": call_usage.tokens_in, "tokens_out": call_usage.tokens_out,
                "tokens_cache_read": call_usage.cache_read, "tokens_cache_write": call_usage.cache_write,
                "tokens_reasoning": call_usage.reasoning, "web_searches": call_usage.web_searches,
                "cost": call_usage.cost,
            }, 10)
    except Exception as e:  # noqa: BLE001 - logging never breaks the caller
        print(f"[AI_GATEWAY] external call report failed: {e}")


def _call_direct(direct: dict, usage: str, payload: dict, team_id: Optional[str]) -> dict:
    """Call a keyless host-reach endpoint described by the server. Reports stats back."""
    from .provider_client import (CallUsage, classify_error, create_client, raise_on_refusal, response_text,
                                  response_usage, single_completion)

    hop_info = direct["hop"]
    started = time.time()
    text, error, error_type = "", "", None
    used = CallUsage()
    try:
        client = create_client(hop_info["preset"], None, base_url=hop_info["base_url"],
                               timeout=int(hop_info.get("timeout_s") or 120))
        resp = raise_on_refusal(single_completion(
            client,
            model=hop_info["model"],
            prompt=payload["prompt"],
            image_b64=payload["image_b64"],
            media_type=payload["media_type"],
            system=payload["system"],
            max_tokens=int(direct.get("max_tokens") or payload["max_tokens"]),
            temperature=direct.get("temperature", payload["temperature"]),
            extra_body=direct.get("extra_body") or {},
        ))
        text, used = response_text(resp), response_usage(resp)
        if not text:
            error, error_type = f"{hop_info['endpoint']}: empty answer from '{hop_info['model']}'", "empty_answer"
    except Exception as e:
        error = f"{hop_info['endpoint']} (direct) call failed for model '{hop_info['model']}': {e}"
        error_type = classify_error(e)
    ms = int((time.time() - started) * 1000)
    image_extra = ({"images": 1, "image_bytes": len(payload["image_b64"]) * 3 // 4}
                   if payload.get("image_b64") is not None else {})
    report_direct_call(usage, team_id, hop_info, split_arm=direct.get("split_arm", ""), ok=bool(text), ms=ms,
                       call_usage=used, error_type=error_type, request_id=direct.get("request_id"),
                       extra={**image_extra, "parse_ok": call_log.parse_ok_for(usage, text, bool(text))})
    tokens = (used.tokens_in, used.tokens_out)
    return {
        "success": bool(text),
        "content": text,
        "error": error,
        "usage": _usage_dict(tokens, used),
        "provider_used": hop_info["preset"],
        "model": hop_info["model"],
        "profile": hop_info["profile"],
        "endpoint": hop_info["endpoint"],
        "via": direct.get("via"),
        "split_arm": direct.get("split_arm", ""),
        "request_id": direct.get("request_id"),
        "fallback_used": False,
    }


def describe(usage: str, team_id: Optional[str] = None, context: Optional[dict] = None) -> dict:
    """Routing summary for ``usage`` (``Resolution.summary()`` shape). Raises AIRoutingError."""
    context = _host_context(context)
    if _local_routing:
        return router.resolve(usage, team_id, context).summary()
    data = _server_post("/server/ai/resolve", {"usage": usage, "team_id": team_id, "context": context}, 10)
    if not data.get("routing"):
        raise router.AIRoutingError(data.get("error") or f"No AI route for '{usage}'")
    return data["routing"]


def is_available(usage: str, team_id: Optional[str] = None, context: Optional[dict] = None) -> bool:
    """True if ``usage`` currently resolves to a callable model (config check, cached on hosts)."""
    context = _host_context(context)
    if _local_routing:
        return router.is_available(usage, team_id, context)
    key = (usage, team_id, tuple(sorted(context.items())))
    cached = _remote_cache.get(key)
    if cached and time.time() - cached[0] < DIRECT_CACHE_TTL_S:
        return cached[1]
    try:
        data = _server_post("/server/ai/resolve", {"usage": usage, "team_id": team_id, "context": context}, 10)
        available = bool(data.get("available"))
    except Exception as e:
        print(f"[AI_GATEWAY] availability check failed for {usage}: {e}")
        available = False
    _remote_cache[key] = (time.time(), available)
    return available
