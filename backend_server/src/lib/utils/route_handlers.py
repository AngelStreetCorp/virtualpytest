"""
Route Handlers - Decorators and Validation Helpers

Centralizes exception handling, JSON/team_id validation for route handlers.
"""

import functools
from flask import request, jsonify
from werkzeug.exceptions import HTTPException


def handle_route_exceptions(log_prefix: str = None):
    """
    Decorator that catches Exception and returns jsonify({'error': str(e)}), 500.
    Eliminates repetitive try/except boilerplate in route handlers.

    Re-raises HTTPException (e.g. Werkzeug's BadRequest from an unguarded
    request.get_json() call) so Flask's own error handling returns the
    intended status code — previously every 400 raised this way was masked
    as a 500, since HTTPException is also an Exception (BUG discovered
    2026-09-07 backfilling non-regression tests).
    """
    def decorator(f):
        @functools.wraps(f)
        def wrapped(*args, **kwargs):
            try:
                return f(*args, **kwargs)
            except HTTPException:
                raise
            except Exception as e:
                if log_prefix:
                    print(f"[{log_prefix}] Error: {e}")
                return jsonify({'error': str(e)}), 500
        return wrapped
    return decorator


def require_json():
    """
    Returns (None, None) if request has valid JSON.
    Returns (error_response, status_code) if JSON is missing or invalid.
    Use: err = require_json(); if err: return err
    """
    if request.get_json(silent=True) is None and request.get_data():
        return jsonify({'error': 'Invalid or missing JSON body'}), 400
    return None


def require_team_id_from_args():
    """
    Returns (team_id, None) if team_id is present in query args.
    Returns (None, error_response_tuple) if missing.
    """
    team_id = request.args.get('team_id')
    if not team_id:
        return None, (jsonify({'error': 'team_id is required'}), 400)
    return team_id, None


def require_team_id_from_body_or_args():
    """
    Returns (team_id, None) if team_id is in JSON body or query args.
    Returns (None, error_response_tuple) if missing.
    """
    data = request.get_json(silent=True) or {}
    team_id = data.get('team_id') or request.args.get('team_id')
    if not team_id:
        return None, (jsonify({'error': 'team_id is required'}), 400)
    return team_id, None


def require_team_id_from_body_or_args_message():
    """Variant: returns {'message': 'team_id is required'} for routes using 'message' key."""
    data = request.get_json(silent=True) or {}
    team_id = data.get('team_id') or request.args.get('team_id')
    if not team_id:
        return None, (jsonify({'message': 'team_id is required'}), 400)
    return team_id, None


def get_team_id_from_args():
    """Get team_id from query args; returns None if missing."""
    return request.args.get('team_id')


def get_team_id_from_body_or_args():
    """Get team_id from JSON body or query args; returns None if missing."""
    data = request.get_json(silent=True) or {}
    return data.get('team_id') or request.args.get('team_id')
