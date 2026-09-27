"""Host-side check of the server-minted host-session cookie (BUG-0107 step 2, BUG-0171).

A native host sits behind nginx, whose `auth_request` asks the server whether the
`vpt_host_session` cookie is valid before it proxies `/host/<name>/stream/...` to the
host. The Docker image has no nginx, so the host answers those nginx-shaped paths itself
and has to make the same decision itself: the cookie the server minted (same secret,
same claims) or the shared service X-API-Key that server-side readers present.
"""
import os

import jwt
from flask import request

from shared.src.lib.utils.auth_utils import validate_api_key

HOST_SESSION_COOKIE_NAME = 'vpt_host_session'


def _host_session_secret() -> str:
    # Same resolution order as server_host_session_routes._host_session_secret, so the
    # compose stack agrees on JWT_SECRET without any extra key.
    return (
        os.getenv('HOST_SESSION_SECRET')
        or os.getenv('SUPABASE_JWT_SECRET')
        or os.getenv('FLASK_SECRET_KEY')
        or ''
    )


def host_session_denied(host_name: str):
    """None when the caller may read this host's media, else (error_dict, status)."""
    if request.method == 'OPTIONS':
        return None  # a CORS preflight never carries credentials
    is_valid, _ = validate_api_key()  # heatmap processor, MCP screenshot tool
    if is_valid:
        return None
    token = request.cookies.get(HOST_SESSION_COOKIE_NAME)
    if not token:
        return {'success': False, 'error': 'missing host session'}, 401
    secret = _host_session_secret()
    if not secret:
        return {'success': False, 'error': 'host session secret not configured'}, 401
    try:
        claims = jwt.decode(token, secret, algorithms=['HS256'])
    except jwt.PyJWTError:
        return {'success': False, 'error': 'invalid or expired host session'}, 401
    if claims.get('host') != host_name:
        return {'success': False, 'error': 'host session does not match host'}, 403
    return None
