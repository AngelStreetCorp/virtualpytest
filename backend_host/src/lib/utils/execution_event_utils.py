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

from shared.src.lib.utils.build_url_utils import buildServerUrl, server_auth_headers
from backend_host.src.lib.utils.host_utils import get_host_instance


_EMIT_TIMEOUT_SECONDS = 10
_EMIT_RETRY_BACKOFF_SECONDS = 0.5


def _post_with_retry(url: str, payload: Dict[str, Any]) -> None:
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
                timeout=_EMIT_TIMEOUT_SECONDS,
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
) -> None:
    """Send execution event to backend_server for websocket broadcast."""
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

    callback_url = buildServerUrl("/server/system/executionEvent")
    threading.Thread(
        target=_post_with_retry,
        args=(callback_url, payload),
        daemon=True,
        name="emit_execution_event",
    ).start()

