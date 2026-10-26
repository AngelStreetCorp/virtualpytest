"""
Who is making this AI call (TASK-87).

A ``contextvars`` value filled **once per entry point** (Flask request, script run, monitoring
worker, scheduled job, agent session, MCP proxy, public Ask) and read by ``router.record`` when it
writes the call log. No call site passes it, so adding a call site needs no attribution code.

Fields (all optional strings): ``origin`` (``ui`` | ``api`` | ``script`` | ``chat`` | ``monitoring`` |
``background`` | ``mcp`` | ``public`` | ``settings_test`` | ``eval``), ``user_id``, ``route``, ``script_name``,
``script_result_id``, ``campaign_id``, ``host_name``, ``device_id``, ``device_model``,
``userinterface_name``, ``session_id``, ``client_hash`` (public Ask), ``job`` (scheduled job name),
``ref_type`` / ``ref_id`` / ``ref_kind`` (what the call was about: an alert, its id, its incident type).

Rules:
- Flask entry points bind in ``before_request`` and clear in ``teardown_request``.
- Code that starts a thread for a call copies the context: ``ctx = contextvars.copy_context();
  Thread(target=lambda: ctx.run(work))`` (``run_in_context`` below).
- A process that only ever does one kind of work (the alert-triage worker, a script child) sets a
  *process default* with ``set_process_default``; a bound context always wins over it.
- The context travels in the ``X-VPT-Caller`` header in both directions: ``call_host`` (server → host) and
  ``server_auth_headers`` (host → server) add it; the server and host before_request hooks bind it.
"""

from __future__ import annotations

import contextvars
import json
import os
from contextlib import contextmanager
from typing import Any, Callable, Iterator, Optional

FIELDS = ("origin", "user_id", "route", "script_name", "script_result_id", "campaign_id", "host_name",
          "device_id", "device_model", "userinterface_name", "session_id", "client_hash", "job", "ref_type", "ref_id",
          "ref_kind", "project_id")
ORIGINS = ("ui", "api", "script", "chat", "monitoring", "background", "mcp", "public", "settings_test", "eval",
           "unknown")
HEADER = "X-VPT-Caller"
_MAX_VALUE = 200

_current: contextvars.ContextVar[Optional[dict]] = contextvars.ContextVar("ai_caller", default=None)
_process_default: dict = {}
_env_loaded = False


def _clean(fields: dict) -> dict:
    return {k: str(v)[:_MAX_VALUE] for k, v in fields.items() if k in FIELDS and v not in (None, "")}


def set_process_default(**fields: Any) -> None:
    """Defaults for every call of this process that has no bound context (a single-purpose worker)."""
    global _env_loaded
    _env_loaded = True  # an explicit default replaces the environment-derived one
    _process_default.clear()
    _process_default.update(_clean(fields))


def current() -> dict:
    """The effective caller: process default overlaid by the bound context, never None."""
    global _env_loaded
    if not _env_loaded:
        _env_loaded = True
        _process_default.update(_env_fields())
    return {**_process_default, **(_current.get() or {})}


def bind(**fields: Any) -> contextvars.Token:
    """Bind ``fields`` (merged over the current context). Reset with ``unbind(token)``."""
    return _current.set({**(_current.get() or {}), **_clean(fields)})


def update(**fields: Any) -> None:
    """Merge ``fields`` into the current context without a token (a script learns its result id late)."""
    _current.set({**(_current.get() or {}), **_clean(fields)})


def unbind(token: contextvars.Token) -> None:
    try:
        _current.reset(token)
    except ValueError:  # token from another context (greenlet / thread hop): just clear
        _current.set(None)


def clear() -> None:
    _current.set(None)


@contextmanager
def bound(**fields: Any) -> Iterator[dict]:
    token = bind(**fields)
    try:
        yield current()
    finally:
        unbind(token)


def run_in_context(fn: Callable[[], Any]) -> Callable[[], Any]:
    """Wrap ``fn`` so it runs with the caller's context (for ``threading.Thread(target=...)``)."""
    ctx = contextvars.copy_context()
    return lambda: ctx.run(fn)


def from_wire(data: Any) -> dict:
    """Validated caller dict from a payload or header (unknown keys dropped, values clipped)."""
    return _clean(data) if isinstance(data, dict) else {}


def header_value() -> Optional[str]:
    """JSON for the ``X-VPT-Caller`` header, or None when there is nothing to forward."""
    data = {k: v for k, v in current().items() if k != "route"}
    return json.dumps(data, separators=(",", ":")) if data else None


def parse_header(value: Optional[str]) -> dict:
    try:
        return from_wire(json.loads(value)) if value else {}
    except (TypeError, ValueError):
        return {}


def _env_fields() -> dict:
    """A script child process inherits its identity from the host executor's environment
    (``VPT_SCRIPT_REF`` and friends, set by ``script_executor``); hosts know their ``HOST_NAME``."""
    env = os.environ
    return _clean({
        "origin": "script" if env.get("VPT_SCRIPT_REF") else None,
        "script_name": env.get("VPT_SCRIPT_DISPLAY_NAME") or env.get("VPT_SCRIPT_REF"),
        "campaign_id": env.get("VPT_CAMPAIGN_ID"),
        "user_id": env.get("VPT_CALLER_USER"),
        "host_name": env.get("HOST_NAME"),
    })
