"""
Host Session Gate (BUG-0107 step 2, generalized)

Started as a VNC-only fix and widened to every proxied `/host/<name>/...`
media path consumed by a browser or a known server-to-server caller (VNC,
live HLS `stream/`) once the same question came up for streams: an IP
allowlist cannot survive going public — a real customer has no fixed IP to
allowlist, and widening it to arbitrary IPs is the same "allow all" hole
BUG-0107 fixed in the first place.

NOT applied to `/host/<name>/phone/socket.io/` (TASK-19, 2026-09-16): that
location's client is the native phone_agent Android app, which holds neither
this cookie (no browser session) nor the shared service X-API-Key (never
baked into a public APK) — only its own one-time pairing token or rotating
device_secret, exchanged over the first Socket.IO message after the
WebSocket upgrade, which nginx's `auth_request` cannot see before deciding
whether to allow the upgrade. Gating that location here 401s every real
phone connecting from outside the host's LAN (verified live 2026-09-16). Its
protection is nginx `limit_req` plus a hello-attempt lockout, both in
features/mobile-app/backend_host/bridge.py — the actual per-device
credential check already happens in that `hello` handler.

Why a separate cookie instead of reusing `vpt_jwt` (the existing navigation
cookie from installFetchAuth.ts): that cookie is written via `document.cookie`
by page JS, so it cannot be HttpOnly, and it is a general-purpose credential —
everything the user's role can do, for up to an hour. Gating a live
remote-desktop socket or a device's video feed with it would mean any XSS
that reads it also gets that access. This cookie is minted server-side via
`Set-Cookie` (real HttpOnly, unreadable by page JS), scoped to exactly one
host's path, and short-lived.

Endpoints:
  POST /server/host-session/session    - frontend calls this before rendering
                                          a VNC iframe or an HLS player pointed
                                          at a `/host/<name>/...` URL; requires
                                          a normal Supabase user JWT. HLS
                                          playback re-fetches segments for as
                                          long as it runs, unlike VNC's one-time
                                          websocket handshake, so the frontend
                                          re-mints this periodically while a
                                          player stays mounted (see
                                          buildUrlUtils.ts: ensureHostSession).
  GET  /server/host-session/authorize  - nginx `auth_request` target, called
                                          for every request under a gated path.
                                          No user JWT here — an iframe/HLS
                                          navigation can't carry one. Accepts
                                          EITHER the cookie (browser traffic)
                                          OR the shared service X-API-Key
                                          (server-to-server callers like the
                                          MCP screenshot tool and the heatmap
                                          processor, which fetch these same
                                          URLs directly with no browser
                                          session at all).
"""

import os
import re
import time

import jwt
from flask import Blueprint, jsonify, make_response, request

from backend_server.src.lib.auth_middleware import _is_valid_service_api_key, require_user_auth
from backend_server.src.lib.utils.route_handlers import handle_route_exceptions

server_host_session_bp = Blueprint('server_host_session', __name__, url_prefix='/server/host-session')

HOST_SESSION_COOKIE_NAME = 'vpt_host_session'
HOST_SESSION_TTL_SECONDS = 600

_GATED_HOST_PATH = re.compile(
    r'^/host/([^/]+)/(?:vnc_lite\.html|websockify|vnc/|core/|vendor/|include/|app/|utils/|stream/)'
)


def _host_session_secret() -> str:
    # Falls back to the Supabase JWT secret so this works in any environment
    # that already has user auth configured, with no extra deploy step. A
    # dedicated HOST_SESSION_SECRET can be set later to rotate independently.
    return (
        os.getenv('HOST_SESSION_SECRET')
        or os.getenv('SUPABASE_JWT_SECRET')
        or os.getenv('FLASK_SECRET_KEY')
        or ''
    )


@server_host_session_bp.route('/session', methods=['POST'])
@require_user_auth
@handle_route_exceptions('host-session:session')
def host_session_mint():
    """Mint a short-lived, host-scoped session cookie for the calling (authenticated) user."""
    data = request.get_json(silent=True) or {}
    host_name = (data.get('host_name') or '').strip()
    if not host_name:
        return jsonify({'error': 'host_name is required'}), 400

    from backend_server.src.lib.utils.server_utils import get_host_manager

    if not get_host_manager().get_host(host_name):
        return jsonify({'error': f'Unknown host: {host_name}'}), 404

    secret = _host_session_secret()
    if not secret:
        return jsonify({'error': 'Host session signing is not configured on this server'}), 500

    now = int(time.time())
    token = jwt.encode(
        {'host': host_name, 'sub': getattr(request, 'user_id', None), 'iat': now, 'exp': now + HOST_SESSION_TTL_SECONDS},
        secret,
        algorithm='HS256',
    )

    resp = make_response(jsonify({'success': True, 'expires_in': HOST_SESSION_TTL_SECONDS}))
    resp.set_cookie(
        HOST_SESSION_COOKIE_NAME,
        token,
        path=f'/host/{host_name}/',
        max_age=HOST_SESSION_TTL_SECONDS,
        httponly=True,
        secure=True,
        samesite='Strict',
    )
    return resp


@server_host_session_bp.route('/authorize', methods=['GET'])
@handle_route_exceptions('host-session:authorize')
def host_session_authorize():
    """nginx `auth_request` target. 2xx = allow, 401/403 = deny. Never called by the frontend."""
    original_uri = request.headers.get('X-Original-URI', '')
    match = _GATED_HOST_PATH.match(original_uri)
    if not match:
        # Not a gated path — nothing for this gate to say about it.
        return '', 200
    host_name = match.group(1)

    # Server-to-server callers (MCP screenshot tool, heatmap processor) fetch these
    # same URLs directly with no browser session — let the shared service key through.
    if _is_valid_service_api_key():
        return '', 200

    token = request.cookies.get(HOST_SESSION_COOKIE_NAME)
    if not token:
        return jsonify({'error': 'missing host session'}), 401

    secret = _host_session_secret()
    try:
        claims = jwt.decode(token, secret, algorithms=['HS256'])
    except jwt.PyJWTError:
        return jsonify({'error': 'invalid or expired host session'}), 401

    if claims.get('host') != host_name:
        return jsonify({'error': 'host session does not match host'}), 403

    return '', 200
