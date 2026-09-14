"""Common response helpers for backend_host routes."""

from typing import Any, Dict, Optional

from flask import jsonify

from backend_host.src.lib.utils.host_utils import get_device_by_id


def _normalize_extra(extra: Dict[str, Any]) -> Dict[str, Any]:
    """Filter out None values from the extra payload."""
    return {key: value for key, value in extra.items() if value is not None}


def error_response(message: str, *, status: int = 400, **extra: Any):
    """Build a standardized error JSON response."""
    payload = {'success': False, 'error': message}
    payload.update(_normalize_extra(extra))
    return jsonify(payload), status


def bad_request(message: str, **extra: Any):
    """400 response shortcut."""
    return error_response(message, status=400, **extra)


def not_found(message: str, **extra: Any):
    """404 response shortcut."""
    return error_response(message, status=404, **extra)


def device_not_found(device_id: str):
    """Device not found helper."""
    return not_found(f'Device {device_id} not found')


def controller_not_found(
    controller_name: str,
    target_description: str,
    *,
    capabilities: Optional[Any] = None,
    **extra: Any
) -> tuple:
    """Controller missing helper with optional capabilities payload."""
    payload_extra = {'available_capabilities': capabilities} if capabilities is not None else {}
    payload_extra.update(_normalize_extra(extra))
    return not_found(
        f'No {controller_name} controller found for {target_description}',
        **payload_extra
    )


def controller_missing_for_device(
    controller_name: str,
    device_id: str,
    *,
    target_description: Optional[str] = None
) -> tuple:
    """Helper that looks up the device and returns the appropriate missing controller error."""
    device = get_device_by_id(device_id)
    if not device:
        return device_not_found(device_id)
    description = target_description or f'device {device_id}'
    return controller_not_found(
        controller_name,
        description,
        capabilities=device.get_capabilities()
    )
