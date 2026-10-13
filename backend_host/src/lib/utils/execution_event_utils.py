"""
Execution Event Utilities

Push host-side async execution lifecycle events back to backend_server so
frontend clients can consume them via /system socket updates without polling.
"""

from __future__ import annotations

from typing import Any, Dict, Optional
import threading
import time
import requests

from shared.src.lib.utils.app_utils import to_native
from shared.src.lib.utils.build_url_utils import buildServerUrl, server_auth_headers
from backend_host.src.lib.utils.host_utils import get_host_instance


_EMIT_TIMEOUT_SECONDS = 10
_EMIT_RETRY_BACKOFF_SECONDS = 0.5
# Terminal events are delivered on the caller's thread (see emit_execution_event),
# so their budget is tighter than the fire-and-forget one: two attempts of 5s
# bound the worst case at ~10.5s on a thread that is about to exit anyway.
_EMIT_BLOCKING_TIMEOUT_SECONDS = 5

# The statuses a client is actually waiting on. Everything else is progress.
TERMINAL_STATUSES = frozenset({'completed', 'error', 'failed', 'aborted'})


def _post_with_retry(url: str, payload: Dict[str, Any],
                     timeout: float = _EMIT_TIMEOUT_SECONDS) -> None:
    # /server/* requires a credential, exactly as register/ping/unregister do in
    # host_utils.py. Without it the server answers 401, and because that is a
    # response rather than an exception it used to be swallowed here: the event
    # never reached the socket and every async execution silently fell back to
    # the frontend's 120s poll timeout.
    last_exc: Optional[BaseException] = None
    for attempt in (1, 2):
        try:
            response = requests.post(
                url,
                json=payload,
                headers=server_auth_headers(),
                timeout=timeout,
            )
            if response.status_code < 400:
                return
            # A rejected POST is not an exception; surface it or the next
            # credential change degrades every execution again, invisibly.
            last_exc = RuntimeError(
                f"server answered {response.status_code}: {response.text[:200]}"
            )
        except Exception as exc:
            last_exc = exc
        if attempt == 1:
            time.sleep(_EMIT_RETRY_BACKOFF_SECONDS)
    print(f"[@execution_event_utils] Failed to emit execution event after retry: {last_exc}")


def emit_execution_event(
    execution_type: str,
    execution_id: str,
    status: str,
    *,
    device_id: Optional[str] = None,
    host_name: Optional[str] = None,
    team_id: Optional[str] = None,
    result: Optional[Dict[str, Any]] = None,
    error: Optional[str] = None,
    progress: Optional[int] = None,
    message: Optional[str] = None,
    blocking: Optional[bool] = None,
) -> None:
    """Send execution event to backend_server for websocket broadcast.

    `blocking` decides whether the POST runs on the caller's thread:

    - **Terminal events** (`completed` / `error` / `failed` / `aborted`) default to
      blocking. These are the ones a client is waiting on, and every one of them is
      emitted from a background execution thread that is about to exit. Delivering
      them inline means the outcome — including a rejection — is observable in the
      thread that produced the result and lands inside that run's own log capture,
      instead of in a detached thread whose failure nobody is left to notice. A 401
      hid a total outage for three weeks that way (BUG-0151 / BUG-0199).
    - **Progress events** (`running`) default to non-blocking, because they are
      emitted from the request handler that still owes the caller an HTTP response.

    Pass `blocking` explicitly to override either default.
    """
    resolved_host_name = host_name
    if not resolved_host_name:
        try:
            host = get_host_instance()
            resolved_host_name = getattr(host, "host_name", None)
        except Exception:
            resolved_host_name = None

    payload: Dict[str, Any] = {
        "execution_type": execution_type,
        "execution_id": execution_id,
        "status": status,
        "timestamp": time.time(),
    }
    if resolved_host_name:
        payload["host_name"] = resolved_host_name
    if device_id:
        payload["device_id"] = device_id
    if team_id:
        payload["team_id"] = team_id
    if result is not None:
        payload["result"] = result
    if error:
        payload["error"] = error
    if progress is not None:
        payload["progress"] = progress
    if message:
        payload["message"] = message

    # requests serializes with allow_nan=False and no numpy support. A numpy value
    # in `result` made requests.post raise before sending; _post_with_retry logged
    # and dropped it, so the terminal event never arrived and the server never
    # released the device lock.
    payload = to_native(payload, nan_to_none=True)

    callback_url = buildServerUrl("/server/system/executionEvent")

    if blocking is None:
        blocking = status in TERMINAL_STATUSES

    if blocking:
        _post_with_retry(callback_url, payload, _EMIT_BLOCKING_TIMEOUT_SECONDS)
        return

    threading.Thread(
        target=_post_with_retry,
        args=(callback_url, payload),
        daemon=True,
        name="emit_execution_event",
    ).start()

