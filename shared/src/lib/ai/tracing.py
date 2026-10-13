"""
Langfuse tracing for every AI call (v2 SDK, self-hosted server).

Auto-enabled when LANGFUSE_HOST (+ LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY) is set.
One **trace** per AI call (a gateway completion, a passthrough request, one public-ask
question, one MCP prompt, one agent turn) and one **generation** per model attempt, so a
fallback shows as a failed generation on the unreachable endpoint followed by the one
that answered. Every trace carries the routing identity — usage key, via, layer, split
arm, profile, endpoint, model, team — plus the deployment tags (branch, server, release).

Images are never uploaded: a placeholder with the media type replaces the pixels.
Tracing is best-effort: any Langfuse error is logged at debug level and never reaches
the AI call. The SDK batches and sends in a background thread.
"""

from __future__ import annotations

import logging
import os
import re
import socket
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

IMAGE_PLACEHOLDER = "[image omitted: {media_type}]"
MAX_TEXT = 20000

_client = None
_client_failed = False
_deploy_ctx: Optional[dict] = None


def enabled() -> bool:
    """Whether Langfuse tracing is configured.

    Read at call time, never at import: the server imports the AI modules before it
    loads its .env, so an import-time constant would switch tracing off for good.
    """
    return bool(os.getenv("LANGFUSE_HOST", "").strip())


def trace_url_base() -> Optional[str]:
    """``<LANGFUSE_HOST>/trace`` when Langfuse is on (append a request id for the conversation), else None."""
    host = (os.getenv("LANGFUSE_HOST") or "").strip().rstrip("/")
    return f"{host}/trace" if host and enabled() else None


def get_client():
    """The shared Langfuse client, or None when tracing is off / unavailable."""
    global _client, _client_failed
    if not enabled() or _client_failed:
        return None
    if _client is None:
        try:
            from langfuse import Langfuse
            _client = Langfuse(
                public_key=os.getenv("LANGFUSE_PUBLIC_KEY"),
                secret_key=os.getenv("LANGFUSE_SECRET_KEY"),
                host=os.getenv("LANGFUSE_HOST", "").strip(),
            )
        except Exception as e:  # ImportError or bad config: stop retrying
            logger.warning(f"Langfuse unavailable, AI tracing off: {e}")
            _client_failed = True
            return None
    return _client


def deployment_context() -> dict:
    """{'branch', 'release', 'server'} from VERSION.txt + hostname (cached)."""
    global _deploy_ctx
    if _deploy_ctx is None:
        branch, release = "unknown", "unknown"
        try:
            first = (Path(__file__).resolve().parents[4] / "VERSION.txt").read_text(encoding="utf-8").splitlines()[0]
            if first.startswith("current:"):
                release = first[len("current:"):].strip()
                m = re.match(r"^(.*?)-\d{4}\.\d{2}\.\d{2}", release)
                branch = m.group(1) if m else release
        except Exception:
            pass
        _deploy_ctx = {"branch": branch, "release": release, "server": socket.gethostname()}
    return _deploy_ctx


def _clip(value: Any) -> Any:
    if isinstance(value, str) and len(value) > MAX_TEXT:
        return value[:MAX_TEXT] + f"… [{len(value) - MAX_TEXT} chars cut]"
    return value


def scrub_messages(messages: Any) -> Any:
    """Copy of Anthropic- or OpenAI-shaped messages with image data replaced by a placeholder."""
    if isinstance(messages, str):
        return _clip(messages)
    if isinstance(messages, dict):
        kind = messages.get("type")
        if kind == "image":
            source = messages.get("source") or {}
            return {"type": "image", "note": IMAGE_PLACEHOLDER.format(media_type=source.get("media_type", "image"))}
        if kind == "image_url":
            url = (messages.get("image_url") or {}).get("url", "")
            media = url.split(";", 1)[0].replace("data:", "") if url.startswith("data:") else "url"
            return {"type": "image_url", "note": IMAGE_PLACEHOLDER.format(media_type=media)}
        return {k: scrub_messages(v) for k, v in messages.items()}
    if isinstance(messages, (list, tuple)):
        return [scrub_messages(m) for m in messages]
    if hasattr(messages, "type"):  # SDK / ProviderBlock objects
        return scrub_messages({k: getattr(messages, k, None) for k in ("type", "text", "id", "name", "input")})
    return messages


def routing_metadata(resolution: Any, hop: Any = None) -> dict:
    meta = {
        "usage": getattr(resolution, "usage", None),
        "via": getattr(resolution, "via_key", None),
        "layer": getattr(resolution, "layer", None),
        "split_arm": getattr(resolution, "split_arm", "") or None,
        "team_id": getattr(resolution, "team_id", None),
    }
    if hop is not None:
        meta.update({
            "profile": hop.profile_name,
            "endpoint": hop.endpoint_name,
            "preset": hop.preset,
            "model": hop.model,
        })
    return {k: v for k, v in meta.items() if v is not None}


class Attempt:
    """One model call (one hop) inside a traced AI call."""

    def __init__(self, hop: Any):
        self.hop = hop
        self.started = datetime.now(timezone.utc)
        self.ended: Optional[datetime] = None
        self.ok = False
        self.output: Optional[str] = None
        self.error: Optional[str] = None
        self.tokens = (0, 0)
        self.fallback = False
        self.usage: Any = None  # CallUsage of the response: carries the provider-reported cost

    def finish(self, *, ok: bool, output: Optional[str] = None, error: Optional[str] = None,
               tokens: tuple = (0, 0), usage: Any = None) -> "Attempt":
        self.ended = datetime.now(timezone.utc)
        self.ok, self.output, self.error, self.tokens = ok, output, error, tokens
        if usage is not None:
            self.usage = usage
        return self

    def cost(self) -> Optional[float]:
        """The cost of this attempt, the figure the call log stores (provider cost, price table, plan, local)."""
        if not self.ok or not (self.tokens[0] or self.tokens[1]):
            return None
        try:
            from . import prices
            return prices.resolve(self.hop, self.tokens[0], self.tokens[1], self.usage)[0]
        except Exception:
            return None


def generation_usage(tokens: tuple, cost: Optional[float]) -> dict:
    """Langfuse v2 ``usage`` of a generation: tokens, plus our cost so Langfuse shows it instead of its own guess."""
    usage: dict = {"input": tokens[0], "output": tokens[1], "unit": "TOKENS"}
    if cost is not None:
        usage["total_cost"] = cost
    return usage


def trace_call(*, name: str, usage: str, input: Any, attempts: list, resolution: Any = None,
               output: Any = None, ok: bool = True, error: Optional[str] = None,
               team_id: Optional[str] = None, session_id: Optional[str] = None,
               user_id: Optional[str] = None, extra: Optional[dict] = None,
               trace_id: Optional[str] = None) -> None:
    """Send one trace with one generation per attempt. Never raises."""
    client = get_client()
    if client is None:
        return
    try:
        ctx = deployment_context()
        served = next((a for a in reversed(attempts) if a.ok), None)
        metadata = {
            **(routing_metadata(resolution, served.hop if served else None) if resolution is not None else {"usage": usage}),
            "ok": ok,
            "fallback_used": bool(served and served.fallback),
            "attempts": len(attempts),
            **(extra or {}),
            **ctx,
        }
        if team_id:
            metadata["team_id"] = team_id
        tags = [t for t in (ctx["branch"], ctx["server"], f"usage:{usage}",
                            f"profile:{served.hop.profile_name}" if served else "failed") if t]
        trace = client.trace(
            id=trace_id,
            name=name,
            session_id=session_id,
            user_id=user_id,
            input=scrub_messages(input),
            output=_clip(output) if output is not None else error,
            metadata=metadata,
            tags=tags,
            release=ctx["release"],
        )
        for attempt in attempts:
            hop = attempt.hop
            trace.generation(
                name=f"{usage} → {hop.profile_name}",
                model=hop.model,
                input=scrub_messages(input),
                output=_clip(attempt.output) if attempt.ok else None,
                usage=generation_usage(attempt.tokens, attempt.cost()),
                metadata={"endpoint": hop.endpoint_name, "preset": hop.preset, "profile": hop.profile_name,
                          "fallback": attempt.fallback},
                start_time=attempt.started,
                end_time=attempt.ended or attempt.started,
                level="DEFAULT" if attempt.ok else "ERROR",
                status_message=None if attempt.ok else (attempt.error or "no answer")[:500],
            )
    except Exception as e:
        logger.debug(f"Langfuse trace failed for {usage}: {e}")


def trace_reported_call(*, usage: str, team_id: Optional[str], profile: str, endpoint: str, ok: bool,
                        ms: int, tokens: tuple, split_arm: str = "", cost: Optional[float] = None) -> None:
    """Trace a call a host made directly to a reach=host endpoint (no prompt/answer, stats only)."""
    client = get_client()
    if client is None:
        return
    try:
        ctx = deployment_context()
        end = datetime.now(timezone.utc)
        trace = client.trace(
            name=f"AI {usage} (host direct)",
            metadata={"usage": usage, "profile": profile, "endpoint": endpoint, "ok": ok, "team_id": team_id,
                      "split_arm": split_arm or None, "reported_by_host": True, **ctx},
            tags=[ctx["branch"], ctx["server"], f"usage:{usage}", f"profile:{profile}"],
            release=ctx["release"],
        )
        trace.generation(name=f"{usage} → {profile}", model=profile,
                         usage=generation_usage(tokens, cost),
                         start_time=end - timedelta(milliseconds=ms), end_time=end,
                         level="DEFAULT" if ok else "ERROR")
    except Exception as e:
        logger.debug(f"Langfuse trace failed for reported {usage}: {e}")


def flush() -> None:
    client = get_client()
    if client is not None:
        try:
            client.flush()
        except Exception:
            pass


def traced_create(client: Any, hop: Any, attempts: list, *, fallback: bool = False, resolution: Any = None,
                  **create_kwargs: Any) -> Any:
    """``client.messages.create(**create_kwargs)`` recorded as one attempt of a tool loop.

    The answer text (or the tool calls the model asked for) becomes the generation output.
    With ``resolution`` the request is also counted (``router.record``: one billed request, ok or
    failed). Re-raises the provider error after recording it.
    """
    import time

    from . import router
    from .provider_client import classify_error, response_text, response_tokens, response_usage

    attempt = Attempt(hop)
    attempt.fallback = fallback
    attempts.append(attempt)
    started = time.time()
    try:
        response = client.messages.create(**create_kwargs)
    except Exception as e:
        attempt.finish(ok=False, error=str(e)[:500])
        if resolution is not None:
            router.record(resolution, hop, ok=False, ms=int((time.time() - started) * 1000), fallback=fallback,
                          error_type=classify_error(e), attempt_index=len(attempts) - 1)
        raise
    blocks = list(getattr(response, "content", None) or [])
    tool_calls = [f"{getattr(b, 'name', '?')}({getattr(b, 'input', {})})" for b in blocks
                  if getattr(b, "type", None) == "tool_use"]
    text = response_text(response)
    output = "\n".join(filter(None, [text, *(f"→ tool {c}" for c in tool_calls)]))
    used = response_usage(response)
    attempt.finish(ok=True, output=output or None, tokens=response_tokens(response), usage=used)
    if resolution is not None:
        router.record(resolution, hop, ok=True, ms=int((time.time() - started) * 1000), tokens_in=used.tokens_in,
                      tokens_out=used.tokens_out, fallback=fallback, usage=used, attempt_index=len(attempts) - 1)
    return response
