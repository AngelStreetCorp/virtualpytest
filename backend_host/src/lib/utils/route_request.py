"""Shared request parsing helpers for backend_host routes."""

from typing import Any, Dict, Optional

from flask import request

from backend_host.src.lib.utils.route_response import bad_request


def get_json_payload(default: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Return the JSON payload or an empty dict when no body is present."""
    payload = request.get_json(silent=True)
    if payload is None:
        return default if default is not None else {}
    return payload


def require_field(
    payload: Dict[str, Any],
    field: str,
    *,
    message: Optional[str] = None,
    allow_empty: bool = False
) -> tuple:
    """
    Validate that a required field exists in the payload and is not empty (unless allowed).

    Returns:
        (value, None) when present.
        (None, response) when missing.
    """
    if field not in payload:
        return None, bad_request(message or f'{field} is required')

    value = payload[field]
    if value is None:
        return None, bad_request(message or f'{field} is required')

    if not allow_empty and isinstance(value, str) and value.strip() == '':
        return None, bad_request(message or f'{field} is required')

    return value, None
