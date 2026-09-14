"""Reusable controller lookup helpers for backend_host routes."""

from typing import Iterable, Optional, Sequence, Tuple

from flask import jsonify

from backend_host.src.lib.utils.host_utils import get_controller, get_device_by_id, get_host


def get_verification_controller(
    device_id: str,
    controller_type: str,
    check_device: bool = False,
) -> Tuple[Optional[object], Optional[object], Optional[Tuple[object, int]]]:
    """Return the controller/device pair for verification routes (with common 404 handling)."""

    controller = get_controller(device_id, controller_type)
    device = None

    if not controller:
        error_response = jsonify({
            'success': False,
            'error': f'No {controller_type} controller found for device {device_id}'
        }), 404
        return None, None, error_response

    if check_device:
        device = get_device_by_id(device_id)
        if not device:
            error_response = jsonify({
                'success': False,
                'error': f'Device {device_id} not found'
            }), 404
            return None, None, error_response

    return controller, device, None


def _matches_desktop_keywords(controller: object, keywords: Sequence[str]) -> bool:
    desktop_type = getattr(controller, 'desktop_type', '') or ''
    controller_name = type(controller).__name__
    desktop_type_lower = desktop_type.lower()

    for keyword in keywords:
        lowered_keyword = keyword.lower()
        if lowered_keyword and lowered_keyword in desktop_type_lower:
            return True
        if keyword and keyword in controller_name:
            return True

    return False


def get_desktop_controller(
    device_id: Optional[str],
    controller_type: str,
    desktop_keywords: Iterable[str] = ('desktop',),
    display_name: str = 'desktop',
    check_device: bool = False,
) -> Tuple[Optional[object], Optional[object], Optional[Tuple[object, int]]]:
    """Return a desktop controller that matches one of the provided keywords."""

    host = get_host()
    target_device = device_id or 'host'
    host_device = host.get_device(target_device)

    if not host_device:
        error_response = jsonify({
            'success': False,
            'error': f'Device {target_device} not found'
        }), 404
        return None, None, error_response

    desktop_controllers = host_device.get_controllers(controller_type)
    if not desktop_controllers:
        error_response = jsonify({
            'success': False,
            'error': f'No {display_name} controllers found for device {target_device}'
        }), 404
        return None, None, error_response

    for controller in desktop_controllers:
        if _matches_desktop_keywords(controller, tuple(desktop_keywords)):
            return controller, host_device, None

    error_response = jsonify({
        'success': False,
        'error': f'No {display_name} desktop controller found for device {target_device}'
    }), 404
    return None, None, error_response
