"""
Completion notifier for async execution flows.

Provides a single place to:
- emit socket updates for internal clients
- optionally POST a completion payload to an external callback URL
"""

from __future__ import annotations

import time
from typing import Any, Dict, Optional

import requests

from backend_server.src.routes.server_system_socket_routes import emit_system_update
from backend_server.src.lib.utils.webhook_utils import resolve_callback_url


def notify_completion(
    payload: Dict[str, Any],
    *,
    callback_url: Optional[str] = None,
    emit_only: bool = False,
) -> Dict[str, Any]:
    """
    Emit standardized completion events and optionally notify an external webhook.

    Payload fields (common):
    - task_id or execution_id
    - execution_type (default: script)
    - status (default: completed/failed inferred from error)
    - result
    - error
    - host_name, device_id, team_id (optional)
    - deployment_id (optional)
    """
    execution_id = payload.get("execution_id") or payload.get("task_id")
    execution_type = payload.get("execution_type") or "script"
    error = payload.get("error")
    result = payload.get("result") or {}
    status = payload.get("status") or ("failed" if error else "completed")
    success = payload.get("success")
    if success is None:
        success = not bool(error) and status != "failed"

    timestamp = payload.get("timestamp") or time.time()

    # Keep existing deployment domain event contract for UI listeners.
    emit_system_update(
        "deployment_execution_changed",
        {
            "domain": "deployment",
            "action": payload.get("action", "script_task_complete"),
            "task_id": execution_id,
            "deployment_id": payload.get("deployment_id"),
            "execution_id": payload.get("deployment_execution_id"),
            "host_name": payload.get("host_name"),
            "device_id": payload.get("device_id"),
            "team_id": payload.get("team_id"),
            "success": success,
            "status": status,
            "result": result,
            "error": error,
            "timestamp": timestamp,
        },
    )

    # Unified execution event contract used by executionSocketWait().
    emit_system_update(
        "execution_update",
        {
            "domain": "execution",
            "execution_type": execution_type,
            "execution_id": execution_id,
            "status": status,
            "host_name": payload.get("host_name"),
            "device_id": payload.get("device_id"),
            "team_id": payload.get("team_id"),
            "progress": payload.get("progress"),
            "message": payload.get("message"),
            "result": result if status != "failed" else None,
            "error": error,
            "timestamp": timestamp,
        },
    )

    webhook_sent = False
    webhook_error = None
    if callback_url and not emit_only:
        resolved_callback_url = resolve_callback_url(callback_url)
        if not resolved_callback_url:
            webhook_error = "Invalid callback_url (must be absolute http/https or resolvable via WEBHOOK_BASE_URL)"
        else:
            callback_payload = {
                "event_type": "execution.completed",
                "execution_type": execution_type,
                "execution_id": execution_id,
                "status": status,
                "success": success,
                "host_name": payload.get("host_name"),
                "device_id": payload.get("device_id"),
                "team_id": payload.get("team_id"),
                "deployment_id": payload.get("deployment_id"),
                "deployment_execution_id": payload.get("deployment_execution_id"),
                "result": result,
                "error": error,
                "timestamp": timestamp,
            }
            try:
                requests.post(resolved_callback_url, json=callback_payload, timeout=10)
                webhook_sent = True
            except Exception as exc:
                webhook_error = str(exc)

    return {
        "success": True,
        "webhook_sent": webhook_sent,
        "webhook_error": webhook_error,
    }
