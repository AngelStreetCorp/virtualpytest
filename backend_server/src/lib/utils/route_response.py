"""
Route Response Helpers

Centralized response builders for server routes.
Eliminates repetitive jsonify/error boilerplate across route handlers.
"""

from flask import jsonify


def error_response(message: str, status_code: int = 500):
    """Return a standard error JSON response."""
    return jsonify({'error': str(message)}), status_code


def validation_error_response(message: str):
    """Return a 400 validation error response."""
    return jsonify({'error': str(message)}), 400


def success_response(data: dict, status_code: int = 200):
    """Return a success JSON response."""
    return jsonify(data), status_code


def service_result_response(result: dict, *, success_key: str = 'success',
                            error_key: str = 'error', status_code_key: str = 'status_code',
                            data_keys: list = None, default_error_status: int = 500):
    """
    Convert a service result dict to a Flask response.

    Service results typically have:
    - result['success']: bool
    - result['error']: str (when success=False)
    - result.get('status_code', 500): optional HTTP status
    - result[key]: data to return on success (e.g. 'devices', 'alerts', 'requirement')

    Args:
        result: Dict from service layer with success/error keys
        success_key: Key for success flag (default 'success')
        error_key: Key for error message (default 'error')
        status_code_key: Key for optional status code (default 'status_code')
        data_keys: If provided, on success return only these keys merged into response.
                   If None, return entire result minus success_key/error_key/status_code_key.
        default_error_status: Status code when result indicates failure (default 500)

    Returns:
        Tuple of (response, status_code)
    """
    if result.get(success_key):
        if data_keys:
            payload = {k: result[k] for k in data_keys if k in result}
        else:
            payload = {k: v for k, v in result.items()
                       if k not in (success_key, error_key, status_code_key)}
        return jsonify(payload), 200
    else:
        status = result.get(status_code_key, default_error_status)
        return jsonify({error_key: result.get(error_key, 'Unknown error')}), status


def service_result_simple(result: dict, success_data_key: str = None, success_status: int = 200,
                         success_payload=None, success_wrapper=None):
    """
    Convert a simple service result to a Flask response.

    Args:
        result: Dict with 'success', 'error', optional 'status_code'
        success_data_key: If set, on success use result[success_data_key] as payload
        success_status: HTTP status on success (default 200)
        success_payload: If set, use this as success body (overrides success_data_key)
        success_wrapper: If set with success_data_key, call with result[success_data_key] to build payload
    """
    if result.get('success'):
        if success_payload is not None:
            return jsonify(success_payload), success_status
        if success_data_key and success_data_key in result:
            data = result[success_data_key]
            if success_wrapper:
                return jsonify(success_wrapper(data)), success_status
            return jsonify(data), success_status
        payload = {k: v for k, v in result.items()
                   if k not in ('success', 'error', 'status_code')}
        return jsonify(payload), success_status
    status = result.get('status_code', 500)
    return jsonify({'error': result.get('error', 'Unknown error')}), status
