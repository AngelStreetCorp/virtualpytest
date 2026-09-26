"""
User Authentication Middleware for Supabase JWT

This middleware validates END USER authentication (different from service API_KEY).
Supabase JWT tokens are validated to identify and authorize frontend users.

DO NOT confuse with:
- API_KEY (X-API-Key header) - for backend_server → backend_host service calls
- MCP_SECRET_KEY - for MCP protocol authentication
- FLASK_SECRET_KEY - for Flask session encryption

This is for USER authentication: Frontend → Backend Server
"""

import os
import jwt
import requests
from functools import wraps
from flask import request, jsonify
from typing import Optional, Callable
from urllib.parse import urljoin

# IMPORTANT: This must be the actual JWT SECRET from Supabase Dashboard:
#   Project Settings → API → JWT Secret
# NOT the anon key (which is a public API key)
SUPABASE_URL = os.getenv('SUPABASE_URL')
_open_mode_warning_logged = False
_required_secret_warning_logged = False
_auto_sign_warning_logged = False
_jwks_sets: dict[str, jwt.PyJWKSet] = {}


def _log_open_mode_warning_once() -> None:
    """Log a loud open-mode warning once per process."""
    global _open_mode_warning_logged
    if _open_mode_warning_logged:
        return
    print(
        "[@auth_middleware] 🚨 SERVER OPEN MODE: SERVER_OPEN_MODE=true — "
        "/server/* browser requests served with no login (dev/trusted-net only). "
        "Direct non-browser calls still need X-API-Key when API_KEY is set."
    )
    _open_mode_warning_logged = True


def _get_supabase_jwt_secret() -> Optional[str]:
    """Return validated JWT secret or None when auth should be treated as disabled."""
    secret = (os.getenv('SUPABASE_JWT_SECRET') or '').strip()
    if not secret:
        return None

    # Treat common template/default placeholders as "not configured" to avoid false auth enforcement.
    normalized = secret.lower()
    placeholder_values = {
        'your-supabase-jwt-secret',
        'your_jwt_secret_here',
        'placeholder',
        'placeholder-key',
        'replace-me',
        'changeme',
        'not-set',
        'none',
        'null',
    }
    if normalized in placeholder_values:
        return None
    if normalized.startswith('your-') and 'supabase' in normalized and 'secret' in normalized:
        return None

    return secret


def _is_valid_service_api_key() -> bool:
    """True when the request carries the shared service key in X-API-Key.

    This is the service-auth path (host -> server: register / ping / unregister /
    execution-lock, and server-to-server calls). It lets those requests through
    the frontend-JWT guard without a user token, matching the documented
    baseline: a request is allowed with a valid service X-API-Key, a valid user
    JWT, or the auto-sign token. Per-route @require_role checks are unaffected —
    they still need a user JWT, so a service key cannot reach admin routes.
    """
    configured = (os.getenv('API_KEY') or '').strip()
    if not configured:
        return False
    provided = (request.headers.get('X-API-Key') or '').strip()
    return bool(provided) and provided == configured


def _is_auto_sign_enabled() -> bool:
    return _is_truthy_env(os.getenv('AUTO_SIGN_ENABLED'))


def is_server_open_mode() -> bool:
    """Explicit, dev-only opt-in to serve `/server/*` **browser** traffic with no login.

    Default **off**: the platform is closed by default. Set `SERVER_OPEN_MODE=true`
    only on local dev or a trusted isolated network. Replaces the old implicit
    "no JWT secret ⇒ open" behaviour.

    It waives the *user login* axis only. When `API_KEY` is configured, a direct
    non-browser call still has to present it — see `_looks_like_browser()`.
    """
    return _is_truthy_env(os.getenv('SERVER_OPEN_MODE'))


def is_server_public_key_configured() -> bool:
    """True when a usable SERVER_PUBLIC_KEY is set (the no-JWT browser baseline).

    Weak by design: it is published in the frontend bundle (`VITE_SERVER_PUBLIC_KEY`),
    so it is a bot speed-bump, not real authentication — it exists so a deployment
    without Supabase/JWT still works while requiring *a* key. It MUST differ from the
    strong service `API_KEY`; if they are equal the weak path is refused (never leak
    `API_KEY` through the bundle).
    """
    key = (os.getenv('SERVER_PUBLIC_KEY') or '').strip()
    if not key:
        return False
    return key != (os.getenv('API_KEY') or '').strip()


def is_api_key_configured() -> bool:
    """True when the shared service key `API_KEY` is set on this server."""
    return bool((os.getenv('API_KEY') or '').strip())


def _looks_like_browser() -> bool:
    """True when the request carries browser-only fetch metadata.

    Browsers set `Sec-Fetch-*` on every fetch/XHR/navigation and page scripts can
    neither forge nor omit them (forbidden header names); curl, requests and
    scanners send neither those nor `Origin`.

    This is what lets `SERVER_OPEN_MODE` mean "no user **login** required" instead
    of "no credential required" — the two are separate axes. `API_KEY` is the
    credential of the server API and has nothing to do with frontend login, so a
    direct (non-browser) call must present it even in open mode, while the SPA of
    a no-login deployment keeps working with no credential at all.

    A speed bump, not a boundary: `curl -H 'Sec-Fetch-Site: same-origin'` passes.
    A deployment that needs a real boundary configures a login
    (`SUPABASE_JWT_SECRET`) and leaves open mode off — then every browser call
    carries a JWT and this heuristic is never consulted.
    """
    return bool(
        (request.headers.get('Sec-Fetch-Site') or '').strip()
        or (request.headers.get('Sec-Fetch-Mode') or '').strip()
        or (request.headers.get('Origin') or '').strip()
    )


# Browser navigations (a report page opened in a new tab, an <a href>, window.open) cannot
# set an Authorization header. The SPA mirrors its credential into a cookie scoped to
# Path=/server/ with SameSite=Strict (frontend/src/utils/installFetchAuth.ts); the server
# accepts that cookie for GET/HEAD only, so it can never authorise a state-changing request
# and SameSite=Strict keeps it off cross-site requests entirely.
NAV_COOKIE_JWT = 'vpt_jwt'
NAV_COOKIE_SERVER_KEY = 'vpt_server_key'


def _navigation_cookie(name: str) -> str:
    """Credential from a navigation cookie — GET/HEAD only, empty otherwise."""
    if request.method not in ('GET', 'HEAD'):
        return ''
    return (request.cookies.get(name) or '').strip()


def _is_valid_server_public_key() -> bool:
    """True when the request carries the configured SERVER_PUBLIC_KEY as X-Server-Key
    (or, for GET navigations, as the vpt_server_key cookie)."""
    if not is_server_public_key_configured():
        return False
    provided = (request.headers.get('X-Server-Key') or '').strip() or _navigation_cookie(NAV_COOKIE_SERVER_KEY)
    return bool(provided) and provided == (os.getenv('SERVER_PUBLIC_KEY') or '').strip()


def _get_server_public_role() -> str:
    """Role granted to a SERVER_PUBLIC_KEY request. Default 'admin' so a no-JWT
    deployment stays fully functional (it has no per-user identity to distinguish);
    lower it via SERVER_PUBLIC_ROLE where the deployment wants a reduced posture."""
    role = (os.getenv('SERVER_PUBLIC_ROLE') or 'admin').strip().lower()
    return role if role in {'admin', 'tester', 'viewer'} else 'admin'


def _get_auto_sign_token() -> Optional[str]:
    token = (os.getenv('AUTO_SIGN_TOKEN') or '').strip()
    return token or None


def _get_auto_sign_role() -> str:
    role = (os.getenv('AUTO_SIGN_ROLE') or 'tester').strip().lower()
    return role if role in {'admin', 'tester', 'viewer'} else 'tester'


def _get_auto_sign_token_from_request() -> Optional[str]:
    header_token = (request.headers.get('X-Auto-Sign') or '').strip()
    if header_token:
        return header_token
    query_token = (request.args.get('auto_signed') or '').strip()
    return query_token or None


def _log_auto_sign_enabled_once() -> None:
    global _auto_sign_warning_logged
    if _auto_sign_warning_logged:
        return
    print(
        "[@auth_middleware] ⚠️  AUTO-SIGN ENABLED: Requests with valid X-Auto-Sign token bypass user auth."
    )
    _auto_sign_warning_logged = True


def _apply_auto_sign_context() -> None:
    request.user_id = 'auto_signed'
    request.user_email = 'auto_signed@local'
    request.user_role = _get_auto_sign_role()
    request.user_metadata = {'auto_sign': True}
    request.user_permissions = []
    request.user_team_permissions = []
    request.user_denied_permissions = []


def _is_request_auto_signed() -> bool:
    if not _is_auto_sign_enabled():
        return False
    token = _get_auto_sign_token()
    if not token:
        return False
    provided = _get_auto_sign_token_from_request()
    if not provided:
        return False
    if provided != token:
        return False
    _log_auto_sign_enabled_once()
    _apply_auto_sign_context()
    return True


def _is_truthy_env(value: Optional[str]) -> bool:
    if value is None:
        return False
    return value.strip().lower() in {'1', 'true', 'yes', 'on', 'enabled', 'required'}


def is_frontend_jwt_required() -> bool:
    """
    Explicit switch for enforcing frontend JWT on /server/*.

    Keep default OFF so deployments stay in open mode unless intentionally enabled.
    """
    return _is_truthy_env(os.getenv('ENFORCE_FRONTEND_JWT'))


def has_supabase_jwt_secret_configured() -> bool:
    """True when a non-placeholder SUPABASE_JWT_SECRET is configured."""
    return _get_supabase_jwt_secret() is not None


def is_supabase_jwt_auth_enabled() -> bool:
    """True when frontend JWT auth is both required and configured."""
    return is_frontend_jwt_required() and has_supabase_jwt_secret_configured()


def _log_required_secret_missing_once() -> None:
    """Log required-auth misconfiguration once per process."""
    global _required_secret_warning_logged
    if _required_secret_warning_logged:
        return
    print(
        "[@auth_middleware] ❌ FRONTEND JWT ENFORCEMENT MISCONFIGURED: "
        "ENFORCE_FRONTEND_JWT=true but SUPABASE_JWT_SECRET is missing/placeholder."
    )
    _required_secret_warning_logged = True


def _get_jwks_url() -> Optional[str]:
    """Build the Supabase JWKS URL from SUPABASE_URL."""
    base = (SUPABASE_URL or '').strip()
    if not base:
        return None
    return urljoin(f"{base.rstrip('/')}/", 'auth/v1/.well-known/jwks.json')


def _get_jwks_set() -> Optional[jwt.PyJWKSet]:
    """Fetch and cache the Supabase JWKS with a non-blocked User-Agent."""
    jwks_url = _get_jwks_url()
    if not jwks_url:
        return None
    jwks_set = _jwks_sets.get(jwks_url)
    if jwks_set is not None:
        return jwks_set

    response = requests.get(
        jwks_url,
        headers={'User-Agent': 'VirtualPyTest/1.0'},
        timeout=10,
    )
    response.raise_for_status()
    jwks_set = jwt.PyJWKSet.from_dict(response.json())
    _jwks_sets[jwks_url] = jwks_set
    return jwks_set


def _decode_supabase_jwt(token: str, jwt_secret: str) -> dict:
    """
    Decode a Supabase access token.

    Supports classic HS256 projects using SUPABASE_JWT_SECRET and asymmetric
    projects (typically RS256) via the Supabase JWKS endpoint.
    """
    unverified_header = jwt.get_unverified_header(token)
    algorithm = unverified_header.get('alg')

    if not algorithm:
        raise jwt.InvalidTokenError('Token is missing alg header')

    if algorithm == 'HS256':
        return jwt.decode(
            token,
            jwt_secret,
            algorithms=['HS256'],
            audience='authenticated',
            options={
                'verify_signature': True,
                'verify_exp': True,
                'verify_aud': True
            }
        )

    jwks_set = _get_jwks_set()
    if jwks_set is None:
        raise jwt.InvalidTokenError(
            f'Unsupported token algorithm {algorithm} and SUPABASE_URL is not configured for JWKS validation'
        )

    key_id = unverified_header.get('kid')
    if not key_id:
        raise jwt.InvalidTokenError('Token is missing kid header')

    signing_key = next((key for key in jwks_set.keys if key.key_id == key_id), None)
    if signing_key is None:
        raise jwt.InvalidTokenError(f'No matching signing key found for kid={key_id}')

    return jwt.decode(
        token,
        signing_key.key,
        algorithms=[algorithm],
        audience='authenticated',
        options={
            'verify_signature': True,
            'verify_exp': True,
            'verify_aud': True
        }
    )


def require_user_auth(f: Callable) -> Callable:
    """
    Decorator to require Supabase user authentication.
    Validates JWT token from Authorization header.
    
    This is for USER authentication (frontend users).
    Does NOT interfere with API_KEY service authentication.
    
    Usage:
        @app.route('/api/protected')
        @require_user_auth
        def protected_route():
            user_id = request.user_id  # Available after auth
            user_role = request.user_role
            ...
    
    Sets request attributes:
        - request.user_id: Supabase user ID
        - request.user_email: User email
        - request.user_role: User role (from JWT or 'viewer' default)
        - request.user_metadata: Full user metadata
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if _is_request_auto_signed():
            return f(*args, **kwargs)

        # A principal already established by the global guard (app.py before_request on
        # /server/*) is authoritative. Open mode, X-Server-Key and the service key never
        # carry a user JWT, and when a secret is configured the guard's JWT branch has
        # already verified the token and set the same attributes this decorator would.
        # Re-running the JWT-only path below answered 500 ("User authentication not
        # configured") on a no-login site and 401 on an X-Server-Key site for every
        # @require_user_auth route, e.g. Run Command (BUG-0071).
        if getattr(request, 'user_role', None):
            return f(*args, **kwargs)

        jwt_secret = _get_supabase_jwt_secret()

        # Check if JWT secret is configured
        if not jwt_secret:
            print("[@auth_middleware] WARNING: SUPABASE JWT secret not configured")
            return jsonify({
                'error': 'Server configuration error',
                'message': 'User authentication not configured'
            }), 500
        
        # Get Authorization header — or, for GET navigations, the JWT mirrored in a cookie
        auth_header = request.headers.get('Authorization', '')
        if not auth_header:
            cookie_token = _navigation_cookie(NAV_COOKIE_JWT)
            if cookie_token:
                auth_header = f'Bearer {cookie_token}'
        
        if not auth_header:
            return jsonify({
                'error': 'Authentication required',
                'message': 'Authorization header is required'
            }), 401
        
        # Check Bearer token format
        if not auth_header.startswith('Bearer '):
            return jsonify({
                'error': 'Invalid Authorization format',
                'message': 'Expected: Authorization: Bearer <token>'
            }), 401
        
        # Extract token
        token = auth_header.replace('Bearer ', '').strip()
        
        try:
            # Decode and verify Supabase JWT. Support both classic HS256 tokens
            # and newer asymmetric tokens via the project's JWKS endpoint.
            payload = _decode_supabase_jwt(token, jwt_secret)
            
            # Extract user information from JWT payload
            request.user_id = payload.get('sub')  # Subject = user ID
            request.user_email = payload.get('email')
            meta = payload.get('user_metadata', {})
            app_meta = payload.get('app_metadata', {})
            # Role AND permissions live in app_metadata — server-controlled, written
            # only by the SECURITY DEFINER on_profile_role_sync trigger from the
            # profiles row. user_metadata is writable by the user themselves
            # (signUp({options:{data}}), PUT /auth/v1/user), so reading either from
            # there let any account grant itself permissions, and let a token with no
            # app_metadata.role assert its own. No fallback: a missing claim means
            # 'viewer' and an empty grant list, which is fail-closed. Tokens minted
            # before the sync existed get the real values on their next refresh.
            request.user_role = app_meta.get('role', 'viewer')
            request.user_metadata = meta
            request.user_app_metadata = app_meta
            request.user_permissions = app_meta.get('permissions', [])
            request.user_team_permissions = app_meta.get('team_permissions', [])
            request.user_denied_permissions = app_meta.get('denied_permissions', [])
            # TASK-23: tenant_ids + is_platform_admin land in app_metadata via the
            # sync_user_claims_to_auth() trigger. Read them here so route code and
            # decorators can gate without a second DB round trip. Fallbacks land in
            # _caller_tenant_ids() / _caller_is_platform_admin() below.
            request.user_tenant_ids = app_meta.get('tenant_ids', []) or []
            request.user_is_platform_admin = bool(app_meta.get('is_platform_admin', False))
            
            # Log successful authentication
            print(f"[@auth_middleware] ✅ User authenticated: {request.user_email} (role: {request.user_role})")
            
        except jwt.ExpiredSignatureError:
            return jsonify({
                'error': 'Token expired',
                'message': 'Please log in again'
            }), 401
        
        except jwt.InvalidAudienceError:
            return jsonify({
                'error': 'Invalid token audience',
                'message': 'Token not valid for this service'
            }), 401
        
        except jwt.InvalidTokenError as e:
            print(f"[@auth_middleware] ❌ Invalid token: {str(e)}")
            return jsonify({
                'error': 'Invalid token',
                'message': 'Authentication failed'
            }), 401
        
        except Exception as e:
            print(f"[@auth_middleware] ❌ Auth error: {str(e)}")
            return jsonify({
                'error': 'Authentication error',
                'message': str(e)
            }), 401
        
        # Token valid, proceed to route
        return f(*args, **kwargs)
    
    return decorated_function


# HTTP methods that cannot change server state. Everything else counts as a write,
# regardless of what the handler actually does — this codebase POSTs for plenty of
# reads, and the exceptions are listed below rather than inferred.
READ_ONLY_METHODS = frozenset({'GET', 'HEAD', 'OPTIONS'})

# Read-shaped POST endpoints a 'viewer' still needs, as exact paths or path prefixes.
#
# The viewer role is meant to be read-only, so the rule is default-deny and every entry
# here earns its line by being walked in the UI and confirmed non-mutating — never by
# looking at a route name, which would put /executeBatch and /upload next to /getStatus.
#
# Populated from a Playwright walk of every viewer-visible page (TASK-22 test 2): the
# whole UI produced exactly three distinct 403s, and only these two are reads. Both
# hand back a pre-signed URL for *reading* a private object and write nothing; they are
# POST only because the object path travels in a JSON body. Without them the Heatmap
# page cannot fetch its captures.
VIEWER_WRITE_EXEMPT_PREFIXES: tuple = (
    '/server/storage/signed-url',
    '/server/storage/signed-urls-batch',
    # Mints the short-lived HttpOnly cookie scoped to /host/<name>/ that the stream
    # player needs (BUG-0107). It signs a JWT and sets a cookie — it writes nothing.
    # Without it every device tile sits on "Loading stream..." forever for a viewer.
    '/server/host-session/session',
)


def _requested_team_id() -> str:
    """The team_id the caller is asking for, from the query string or a JSON body."""
    tid = (request.args.get('team_id') or '').strip()
    if tid:
        return tid
    if request.method in READ_ONLY_METHODS:
        return ''
    data = request.get_json(silent=True) or {}
    value = data.get('team_id')
    return str(value).strip() if value else ''


def _caller_team_ids() -> set:
    """
    Teams the authenticated caller belongs to: home team + every team_members row.

    From the `team_ids` claim in app_metadata (written only by the database trigger),
    with a database lookup as fallback so tokens minted before the claim existed keep
    working for their remaining lifetime instead of locking the user out for an hour.
    Cached on the request — this runs in a before_request on every /server/* call.
    """
    cached = getattr(request, '_vpt_team_ids', None)
    if cached is not None:
        return cached

    claim = (getattr(request, 'user_app_metadata', None) or {}).get('team_ids')
    if isinstance(claim, list):
        ids = {str(t) for t in claim if t}
    else:
        ids = _team_ids_from_db(getattr(request, 'user_id', None))

    request._vpt_team_ids = ids
    return ids


def _team_ids_from_db(user_id: Optional[str]) -> set:
    """Fallback lookup for a token with no team_ids claim. Empty set on any failure — deny."""
    if not user_id:
        return set()
    try:
        from shared.src.lib.utils.supabase_utils import get_supabase_admin
        sb = get_supabase_admin()
        if sb is None:
            return set()
        ids = set()
        profile = sb.table('profiles').select('team_id').eq('id', user_id).limit(1).execute()
        for row in (profile.data or []):
            if row.get('team_id'):
                ids.add(str(row['team_id']))
        members = sb.table('team_members').select('team_id').eq('user_id', user_id).execute()
        for row in (members.data or []):
            if row.get('team_id'):
                ids.add(str(row['team_id']))
        return ids
    except Exception as e:
        print(f"[@auth_middleware] team_ids lookup failed for {user_id}: {e}")
        return set()


def _caller_tenant_ids() -> set:
    """
    Tenants the authenticated caller belongs to.

    From the `tenant_ids` claim in app_metadata (written only by the database
    trigger from the `user_tenants` junction), with a database fallback so
    tokens minted before TASK-23 (or before a recent refresh) keep working for
    their remaining lifetime. Cached on the request — the JWT decode block
    already populates `request.user_tenant_ids`, this just hydrates the set
    form and handles the no-claim case.

    Returns an empty set on any failure, so the caller fails closed (every
    team-scoped route will deny).
    """
    cached = getattr(request, '_vpt_tenant_ids', None)
    if cached is not None:
        return cached

    claim = getattr(request, 'user_tenant_ids', None)
    if isinstance(claim, list) and claim:
        ids = {str(t) for t in claim if t}
    else:
        ids = _tenant_ids_from_db(getattr(request, 'user_id', None))

    request._vpt_tenant_ids = ids
    return ids


def _tenant_ids_from_db(user_id: Optional[str]) -> set:
    """Fallback lookup for a token with no tenant_ids claim. Empty set on any failure — deny."""
    if not user_id:
        return set()
    try:
        from shared.src.lib.utils.supabase_utils import get_supabase_admin
        sb = get_supabase_admin()
        if sb is None:
            return set()
        rows = (
            sb.table('user_tenants')
            .select('tenant_id')
            .eq('user_id', user_id)
            .execute()
        ).data or []
        return {str(r['tenant_id']) for r in rows if r.get('tenant_id')}
    except Exception as e:
        print(f"[@auth_middleware] tenant_ids lookup failed for {user_id}: {e}")
        return set()


def _caller_is_platform_admin() -> bool:
    """
    Whether the authenticated caller is a platform super admin.

    From the `is_platform_admin` claim in app_metadata, with a database
    fallback for tokens minted before the claim existed. Cached per request.
    A platform admin is exempt from the tenant boundary check — they see
    every tenant's teams, like the existing `role = 'admin'` exemption in
    enforce_team_scope().
    """
    cached = getattr(request, '_vpt_is_platform_admin', None)
    if cached is not None:
        return cached

    claim = getattr(request, 'user_is_platform_admin', None)
    if isinstance(claim, bool):
        is_pa = claim
    else:
        is_pa = _is_platform_admin_from_db(getattr(request, 'user_id', None))

    request._vpt_is_platform_admin = is_pa
    return is_pa


def _is_platform_admin_from_db(user_id: Optional[str]) -> bool:
    """Fallback lookup for the is_platform_admin flag. False on any failure — deny."""
    if not user_id:
        return False
    try:
        from shared.src.lib.utils.supabase_utils import get_supabase_admin
        sb = get_supabase_admin()
        if sb is None:
            return False
        row = (
            sb.table('profiles')
            .select('is_platform_admin')
            .eq('id', user_id)
            .limit(1)
            .execute()
        ).data or []
        if not row:
            return False
        return bool(row[0].get('is_platform_admin', False))
    except Exception as e:
        print(f"[@auth_middleware] is_platform_admin lookup failed for {user_id}: {e}")
        return False


def enforce_team_scope():
    """
    Refuse a request that names a team the caller does not belong to.

    `team_id` is the multi-tenancy boundary for ~45 tables, but 140 `/server/*` routes
    read it straight from `request.args` and nothing validated it. Proven on the live
    system 2026-09-17: a viewer belonging only to Default Team read another team's
    script_results by changing one query parameter, HTTP 200. That is a cross-tenant
    read for any logged-in account, and a write for anyone above viewer.

    Enforced here rather than in 140 routes, for the same reason as the viewer floor:
    a per-route check is a rule with 140 chances to be forgotten.

    Exempt:
      * `service` — the shared X-API-Key principal (host callbacks, CI, provisioning)
        legitimately acts across teams; it is not a browser user.
      * `admin` — platform administrators manage every team, matching how
        require_permission() already treats them.
      * requests naming no team — the route's own `team_id is required` check applies.

    Returns a 403 response tuple, or None to continue.
    """
    role = getattr(request, 'user_role', None)
    if role in (None, 'service', 'admin'):
        return None
    # TASK-23: a platform admin (super admin) is exempt from the tenant boundary
    # check — they see every tenant's teams, like a regular admin. The
    # is_platform_admin flag is JWT-sourced with a DB fallback for stale tokens.
    if _caller_is_platform_admin():
        return None

    requested = _requested_team_id()
    if not requested:
        return None

    if requested in _caller_team_ids():
        return None

    print(f"[@auth_middleware] \u26d4 team scope: {getattr(request, 'user_email', '?')} "
          f"asked for team {requested} on {request.method} {request.path}")
    return jsonify({
        'error': 'Forbidden',
        'message': 'You do not belong to the team this request names.',
    }), 403


def enforce_viewer_read_only():
    """
    Block state-changing requests from a 'viewer' principal.

    Runs in the global /server/* guard (app.py), after a principal has been
    established — so it covers every route, including the ~234 write routes that
    carry no @require_permission of their own. Per-route decorators stay in force;
    this is the floor under them, not a replacement.

    Returns a 403 response tuple for a denied write, or None to continue.
    """
    if request.method in READ_ONLY_METHODS:
        return None

    # Missing attribute = the request never reached the auth branches (an
    # unauthenticated-prefix route such as a host callback). Those are exempt by
    # construction and are not a viewer's requests.
    if getattr(request, 'user_role', None) != 'viewer':
        return None

    path = request.path or ''
    if any(path == prefix or path.startswith(f'{prefix}/')
           for prefix in VIEWER_WRITE_EXEMPT_PREFIXES):
        return None

    print(f"[@auth_middleware] ⛔ viewer blocked from {request.method} {path}")
    return jsonify({
        'error': 'Forbidden',
        'message': 'The viewer role is read-only; this request changes state.',
        'user_role': 'viewer'
    }), 403


def principal_from_jwt_claims(payload: dict) -> dict:
    """Turn a verified Supabase JWT payload into a principal dict.

    Role and grants come from `app_metadata` ONLY — it is written by the SECURITY DEFINER
    `on_profile_role_sync` trigger from the profiles row. `user_metadata` is writable by the
    user themselves, so reading authorization out of it lets any account grant itself
    anything. A missing claim means 'viewer' with no grants, which is fail-closed.
    """
    app_meta = payload.get('app_metadata', {}) or {}
    return {
        'user_id': payload.get('sub'),
        'user_email': payload.get('email'),
        'user_role': app_meta.get('role', 'viewer'),
        'user_metadata': payload.get('user_metadata', {}) or {},
        'user_app_metadata': app_meta,
        'user_permissions': app_meta.get('permissions', []),
        'user_team_permissions': app_meta.get('team_permissions', []),
        'user_denied_permissions': app_meta.get('denied_permissions', []),
    }


def _shared_principal(user_id: str, email: str, role: str, marker: str) -> dict:
    """A principal that is not one person: the service key, open mode, a public key."""
    return {
        'user_id': user_id,
        'user_email': email,
        'user_role': role,
        'user_metadata': {marker: True},
        'user_app_metadata': {},
        'user_permissions': [],
        'user_team_permissions': [],
        'user_denied_permissions': [],
        'shared': True,
    }


def _handshake_auto_signed(auth: dict) -> bool:
    """Auto-sign token presented in the socket handshake payload instead of a header/query."""
    if not _is_auto_sign_enabled():
        return False
    expected = _get_auto_sign_token()
    provided = (auth.get('auto_sign') or '').strip()
    if not expected or not provided or provided != expected:
        return False
    _log_auto_sign_enabled_once()
    _apply_auto_sign_context()
    return True


def _handshake_server_key(auth: dict) -> bool:
    """SERVER_PUBLIC_KEY presented in the socket handshake payload instead of X-Server-Key."""
    if not is_server_public_key_configured():
        return False
    provided = (auth.get('server_key') or '').strip()
    return bool(provided) and provided == (os.getenv('SERVER_PUBLIC_KEY') or '').strip()


def authorize_socket_connection(auth: Optional[dict]) -> Optional[dict]:
    """Authorize a Socket.IO handshake. Returns a principal dict, or None to refuse.

    Socket.IO connects over its own handshake at /socket.io/, which never passes through the
    global /server/* guard in app.py — so every namespace was reachable by anyone who could
    open a socket, whatever the HTTP posture. This is that guard's decision, for sockets, and
    it deliberately mirrors it axis for axis so a deployment cannot be closed over HTTP and
    open over WebSocket:

        X-API-Key (handshake header) -> auto-sign -> open mode -> user JWT -> public key -> refuse

    Credentials arrive in the handshake `auth` payload (`io(url, { auth: {...} })`) rather
    than in headers, because a browser WebSocket cannot set them. The payload mirrors what
    installFetchAuth.ts puts on every HTTP request — `token`, `server_key`, `auto_sign` —
    and headers are still honoured for non-browser clients (python-socketio, CI) that can
    send them.

    Returning None makes the connect handler return False, which socket.io reports to the
    client as a connection error — it does not silently half-connect.
    """
    auth = auth or {}

    # Same order as enforce_user_auth_if_enabled_for_request(). A *present* key is validated
    # strictly and never falls through to a weaker branch.
    if request.headers.get('X-API-Key') is not None:
        if not _is_valid_service_api_key():
            return None
        return _shared_principal('service_api_key', 'service@local', 'service', 'service_api_key')

    if _is_request_auto_signed() or _handshake_auto_signed(auth):
        return _shared_principal('auto_sign', 'auto@local', _get_auto_sign_role(), 'auto_signed')

    if is_server_open_mode():
        _log_open_mode_warning_once()
        return _shared_principal('open_mode', 'open@local', _get_server_public_role(), 'server_open_mode')

    jwt_secret = _get_supabase_jwt_secret()
    if jwt_secret:
        token = (auth.get('token') or '').strip()
        if not token:
            header = request.headers.get('Authorization', '')
            if header.startswith('Bearer '):
                token = header[len('Bearer '):].strip()
        if not token:
            print("[@auth_middleware:socket] ⛔ refused: no token in handshake")
            return None
        try:
            return principal_from_jwt_claims(_decode_supabase_jwt(token, jwt_secret))
        except jwt.InvalidTokenError as e:
            print(f"[@auth_middleware:socket] ⛔ refused: invalid token ({e})")
            return None

    # The no-Supabase posture. A browser socket cannot set X-Server-Key, so the SPA puts the
    # same published key in the handshake payload; the cookie path still covers navigations.
    if _is_valid_server_public_key() or _handshake_server_key(auth):
        return _shared_principal('public_key', 'public@local', _get_server_public_role(), 'server_public_key')

    print("[@auth_middleware:socket] ⛔ refused: no credential and no open-mode posture")
    return None


def require_role(*allowed_roles: str) -> Callable:
    """
    Decorator to require specific user roles.
    Must be used AFTER @require_user_auth.
    
    Usage:
        @app.route('/api/admin-only')
        @require_user_auth
        @require_role('admin')
        def admin_route():
            ...
        
        @app.route('/api/testers')
        @require_user_auth
        @require_role('admin', 'tester')
        def tester_route():
            ...
    
    Args:
        allowed_roles: One or more role names (e.g., 'admin', 'tester', 'viewer')
    """
    def decorator(f: Callable) -> Callable:
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # Check if user_role is set (requires @require_user_auth first)
            if not hasattr(request, 'user_role'):
                return jsonify({
                    'error': 'Configuration error',
                    'message': '@require_role must be used after @require_user_auth'
                }), 500
            
            user_role = request.user_role
            
            # Check if user has one of the allowed roles
            if user_role not in allowed_roles:
                return jsonify({
                    'error': 'Forbidden',
                    'message': f'This endpoint requires one of these roles: {", ".join(allowed_roles)}',
                    'user_role': user_role
                }), 403
            
            print(f"[@auth_middleware] ✅ Role check passed: {user_role} in {allowed_roles}")
            return f(*args, **kwargs)
        
        return decorated_function
    return decorator


ROLE_DEFAULT_PERMISSIONS: dict = {
    'tester': {
        'dashboard:view',
        'device_control:view', 'device_control:execute',
        'testcases:view', 'testcases:create', 'testcases:edit', 'testcases:hide',
        'campaigns:view', 'campaigns:create', 'campaigns:edit', 'campaigns:execute',
        'builder.test:view', 'builder.test:use',
        'builder.campaign:view', 'builder.campaign:use',
        'execution.run:view', 'execution.run:run_test', 'execution.run:run_campaign',
        'execution.monitor:view',
        'reports.tests:view', 'reports.campaigns:view',
        'reports.models:view', 'reports.dependency:view',
        'monitoring.incidents:view', 'monitoring.heatmap:view', 'monitoring.ai_queue:view',
        'interface:view',
        'ai_agent:view', 'ai_agent:use',
        'plugins.postman:view',
        'plugins.jira:view', 'plugins.jira:manage', 'plugins.testrail:view',
        'settings.status:view',
    },
    'viewer': {
        # Read-only everywhere a tester is also read-only, so a viewer can
        # audit the system and integrations but cannot mutate state. Write
        # verbs (`*:manage`, `device_control:execute/reboot/restart_streams`)
        # stay admin/tester-only — TASK-23 + the global read-only floor on
        # the /server/* guard means a viewer cannot change anything anyway,
        # but listing the read verbs here keeps the matrix honest (BUG-0154)
        # and stops the /server/integrations/* GET endpoints returning 403 to
        # a viewer who only wants to read the configured status.
        'dashboard:view',
        'testcases:view', 'campaigns:view',
        'reports.tests:view', 'reports.campaigns:view',
        'reports.models:view', 'reports.dependency:view',
        'monitoring.incidents:view', 'monitoring.heatmap:view', 'monitoring.ai_queue:view',
        'device_control:view',  # see host cards / status; :execute/:reboot/:restart_streams stay tester+admin-only
        'plugins.postman:view',
        'plugins.jira:view',
        'plugins.testrail:view',
        'plugins.slack:view',
        'plugins.grafana:view',
        'plugins.langfuse:view',
        'settings.status:view',
    },
}

# 'admin' is deliberately absent: it never consults this table (principal_holds_permission
# answers True before reaching it), and spelling out every permission here would be a fourth
# copy of the vocabulary to keep in step with frontend/src/types/auth.ts.


def principal_holds_permission(permission: str) -> bool:
    """Does the current request's principal hold `permission`?

    The one implementation of the resolution order, shared by @require_permission and by the
    routes that need the same answer mid-handler rather than as a gate:

      1. admin / service  -> always true, denials never consulted
      2. explicit denial  -> false
      3. role defaults | team grants | individual grants -> membership

    One implementation on purpose. This arithmetic had already been written out three times
    (here, the matrix API, the frontend PermissionContext) and the copies disagreed - see
    BUG-0154. Call this instead of re-deriving it.
    """
    user_role = getattr(request, 'user_role', None)
    if user_role in ADMIN_ROLES:
        return True

    if permission in set(getattr(request, 'user_denied_permissions', []) or []):
        return False

    allowed = (
        ROLE_DEFAULT_PERMISSIONS.get(user_role, set())
        | set(getattr(request, 'user_team_permissions', []) or [])
        | set(getattr(request, 'user_permissions', []) or [])
    )
    return permission in allowed


def require_permission(permission: str) -> Callable:
    """
    Decorator to require a specific fine-grained permission (resource:action format).
    Must be used AFTER @require_user_auth, or after the global /server/* guard that sets
    request.user_role.

    Resolution lives in principal_holds_permission(); this only turns a False into a 403.

    Args:
        permission: e.g. 'testcases:hide', 'execution.run:run_test'
    """
    def decorator(f: Callable) -> Callable:
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not hasattr(request, 'user_role'):
                return jsonify({
                    'error': 'Configuration error',
                    'message': '@require_permission must be used after @require_user_auth'
                }), 500

            user_role = request.user_role

            if not principal_holds_permission(permission):
                if permission in set(getattr(request, 'user_denied_permissions', []) or []):
                    return jsonify({
                        'error': 'Forbidden',
                        'message': f'Permission explicitly denied: {permission}',
                        'user_role': user_role
                    }), 403
                return jsonify({
                    'error': 'Forbidden',
                    'message': f'This endpoint requires permission: {permission}',
                    'user_role': user_role
                }), 403

            print(f"[@auth_middleware] ✅ Permission check passed: {permission}")
            return f(*args, **kwargs)

        return decorated_function
    return decorator


def require_any_permission(*permissions: str) -> Callable:
    """Allow the request if the caller holds ANY of these permissions.

    For endpoints that cover more than one action — `testcase/save` is create-or-edit, and
    the matrix grants `testcases:create` and `testcases:edit` independently, so gating on
    just one of them would block a user who legitimately holds the other.
    """
    def decorator(f: Callable) -> Callable:
        @wraps(f)
        def decorated_function(*args, **kwargs):
            last_response = None
            for permission in permissions:
                probe = require_permission(permission)(lambda *_a, **_k: None)
                last_response = probe(*args, **kwargs)
                if last_response is None:
                    return f(*args, **kwargs)
            return last_response

        return decorated_function
    return decorator


def optional_user_auth(f: Callable) -> Callable:
    """
    Decorator for optional authentication.
    Validates JWT if present, but doesn't require it.
    
    Usage:
        @app.route('/api/public-or-authenticated')
        @optional_user_auth
        def mixed_route():
            if hasattr(request, 'user_id'):
                # User is authenticated
                ...
            else:
                # Anonymous access
                ...
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        auth_header = request.headers.get('Authorization', '')
        jwt_secret = _get_supabase_jwt_secret()
        
        if jwt_secret and auth_header and auth_header.startswith('Bearer '):
            token = auth_header.replace('Bearer ', '').strip()
            
            try:
                payload = jwt.decode(
                    token,
                    jwt_secret,
                    algorithms=['HS256'],
                    audience='authenticated'
                )
                
                meta = payload.get('user_metadata', {})
                app_meta = payload.get('app_metadata', {})
                request.user_id = payload.get('sub')
                request.user_email = payload.get('email')
                # See require_user_auth: role AND permissions come from app_metadata,
                # which only the database trigger writes. Never user_metadata — the
                # user writes that themselves.
                request.user_role = app_meta.get('role', 'viewer')
                request.user_metadata = meta
                request.user_app_metadata = app_meta
                request.user_permissions = app_meta.get('permissions', [])
                request.user_team_permissions = app_meta.get('team_permissions', [])
                request.user_denied_permissions = app_meta.get('denied_permissions', [])

            except Exception as e:
                # Invalid token, but we don't reject - just continue without auth
                print(f"[@auth_middleware] ⚠️  Optional auth failed: {str(e)}")
                pass
        
        return f(*args, **kwargs)
    
    return decorated_function


def require_user_auth_if_enabled(f: Callable) -> Callable:
    """
    Require user auth only when SUPABASE_JWT_SECRET is configured.

    - Open mode (no secret): allow request and log a loud warning once.
    - Auth mode (secret configured): enforce bearer JWT using require_user_auth.
    """
    enforced_auth = require_user_auth(f)

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if is_frontend_jwt_required() and not has_supabase_jwt_secret_configured():
            _log_required_secret_missing_once()
            return jsonify({
                'error': 'Server configuration error',
                'message': 'Frontend JWT enforcement is enabled but SUPABASE_JWT_SECRET is not configured'
            }), 503

        if not is_supabase_jwt_auth_enabled():
            _log_open_mode_warning_once()
            return f(*args, **kwargs)

        return enforced_auth(*args, **kwargs)

    return decorated_function


def enforce_user_auth_if_enabled_for_request() -> Optional[tuple]:
    """
    Authorize the current `/server/*` request. Two independent axes:

    - **`API_KEY` / `X-API-Key`** — the credential of the server API, for machine
      callers (host->server, CI, provisioning, scripts). Checked first, validated
      strictly, and never waived by open mode or by the JWT posture.
    - **User login** — a Supabase JWT when a secret is configured; `SERVER_OPEN_MODE`
      waives *this* axis, and only for requests that look like a browser.

    Order: strict X-API-Key -> auto-sign -> open mode (browsers) -> user JWT ->
    SERVER_PUBLIC_KEY -> 401.

    Returns:
      - None when request may continue
      - Flask response tuple when request must be rejected
    """
    if is_frontend_jwt_required() and not has_supabase_jwt_secret_configured() and not is_server_open_mode():
        _log_required_secret_missing_once()
        return jsonify({
            'error': 'Server configuration error',
            'message': 'Frontend JWT enforcement is enabled but SUPABASE_JWT_SECRET is not configured'
        }), 503

    # Service-auth: host -> server and server-to-server calls present the shared
    # X-API-Key instead of a user JWT. `API_KEY` is the credential of the *server
    # API*; it is a different axis from frontend login, so this runs before open
    # mode and before the JWT branch and is never waived by either.
    #
    # A *present* X-API-Key is validated strictly: a wrong key is a hard 401, it
    # never falls through to a later branch. Before this, a service with a typo'd
    # key was silently admitted as admin on an open-mode deployment and rejected
    # on a JWT one — the same caller "working" on one site and 401-ing on another
    # with no way to tell why (docs/agent/platform/SERVER_AUTH.md §3).
    if request.headers.get('X-API-Key') is not None:
        if not _is_valid_service_api_key():
            return jsonify({
                'error': 'unauthorized',
                'message': 'Invalid X-API-Key'
            }), 401
        request.user_id = 'service_api_key'
        request.user_email = 'service@local'
        request.user_role = 'service'
        request.user_metadata = {'service_api_key': True}
        request.user_permissions = []
        request.user_team_permissions = []
        request.user_denied_permissions = []
        return None

    if _is_request_auto_signed():
        return None

    # Explicit open mode wins over everything below, INCLUDING a configured JWT secret
    # (BUG-0070): SERVER_OPEN_MODE=true is the operator's stated intent, and a site with
    # no browser login often still carries a SUPABASE_JWT_SECRET from its database
    # install — before this, that stale secret silently forced JWT enforcement and the
    # explicit open-mode line did nothing. Open mode = "everything allowed" by definition,
    # so granting the configured public role here does not widen the posture (BUG-0064).
    if is_server_open_mode():
        # Open mode waives the browser *login*, not the server API key. A direct
        # (non-browser) call still presents X-API-Key whenever one is configured,
        # so `curl /server/...` against a no-login deployment is refused while its
        # own SPA — which has no credential to send — keeps working.
        if is_api_key_configured() and not _looks_like_browser():
            return jsonify({
                'error': 'unauthorized',
                'message': 'X-API-Key header is required: SERVER_OPEN_MODE waives the '
                           'browser login, not the server API key'
            }), 401
        _log_open_mode_warning_once()
        request.user_id = 'open_mode'
        request.user_email = 'open@local'
        request.user_role = _get_server_public_role()
        request.user_metadata = {'server_open_mode': True}
        request.user_permissions = []
        request.user_team_permissions = []
        request.user_denied_permissions = []
        return None

    # User JWT — required whenever a real Supabase JWT secret is configured,
    # independent of ENFORCE_FRONTEND_JWT (secure by default). The frontend
    # attaches the session JWT to every /server/* request (installFetchAuth.ts).
    if has_supabase_jwt_secret_configured():
        @require_user_auth
        def _auth_probe():
            return None
        result = _auth_probe()
        return result if result is not None else None

    # No JWT secret configured — a deployment without Supabase/JWT. It still works,
    # but not wide open: the SPA presents the weak, published SERVER_PUBLIC_KEY as
    # X-Server-Key (a bot speed-bump). This is the "works with JWT disabled" path.
    if _is_valid_server_public_key():
        request.user_id = 'public_key'
        request.user_email = 'public@local'
        request.user_role = _get_server_public_role()
        request.user_metadata = {'server_public_key': True}
        request.user_permissions = []
        request.user_team_permissions = []
        request.user_denied_permissions = []
        return None

    # Still nothing valid → 401. Open mode was already handled above (it is an explicit
    # opt-in, never the default).
    return jsonify({
        'error': 'unauthorized',
        'message': 'Authentication required: present a valid X-API-Key, a user JWT, an auto-sign token, or X-Server-Key'
    }), 401


# Roles that satisfy an admin-level route gate.
#
# 'service' is the shared X-API-Key principal set by the global guard for host->server,
# provisioning, CI and backend->backend callers. It is strictly MORE trusted than
# any user role — the same key drives /host/* device control directly — so locking it out
# of admin routes would break those callers without buying any safety. See
# docs/agent/platform/SERVER_AUTH.md ("Service / automation -> X-API-Key", and API_KEY
# "valid on all routes incl. service-only").
#
# Auto-signed E2E requests need no special case: the guard gives them AUTO_SIGN_ROLE,
# which is 'admin' on every deployment that runs the browser suites.
ADMIN_ROLES = ('admin', 'service')


def require_admin_role(f: Callable) -> Callable:
    """Restrict a route to admin users and the service key.

    Use on user/team/workspace/permission administration, where a tester or viewer JWT
    must get 403 (docs/agent/platform/USER_PERMISSION.md). Runs after the global
    guard in app.py, which is what sets request.user_role, so it needs no @require_user_auth
    of its own.
    """
    return require_role(*ADMIN_ROLES)(f)


# Aliases for common usage patterns
require_auth = require_user_auth
require_admin = require_role('admin')


# ============================================================================
# TASK-23 — Tenant decorators
# ============================================================================


def require_platform_admin(f: Callable) -> Callable:
    """
    Restrict a route to the platform super admin only.

    Use for tenant CRUD (`/server/tenants/*`) and tenant grant / revoke
    (`/server/users/:id/tenants`). The role='admin' decorator is **not** enough:
    the maintainer's intent (Q3) is that regular admins are unaware tenants
    exist at all, so even `role='admin'` users get 403 here.

    Runs after the global guard in app.py, which sets request.user_role and
    hydrates the is_platform_admin claim (with DB fallback). No additional
    decorator chain needed.
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not hasattr(request, 'user_role'):
            return jsonify({
                'error': 'Configuration error',
                'message': '@require_platform_admin needs request.user_role; '
                'ensure the /server/* guard has run.'
            }), 500

        # service / X-API-Key callers legitimately act as super admin
        # (host callbacks, CI ingest, provisioning). Same convention as require_admin_role.
        if getattr(request, 'user_role', None) == 'service':
            return f(*args, **kwargs)

        if not _caller_is_platform_admin():
            return jsonify({
                'error': 'Forbidden',
                'message': 'This endpoint requires platform-admin (super admin) access.',
            }), 403

        return f(*args, **kwargs)
    return decorated_function


def require_team_in_tenant(f: Callable) -> Callable:
    """
    Per-route decorator: refuse if the `team_id` named by the request does not
    belong to a tenant the caller has membership in.

    Use on the ~140 team-scoped routes that read `team_id` straight from
    `request.args` / `request.json` / URL kwargs and otherwise trust the
    caller. Stacking this on top of `@require_user_auth` (or the global
    /server/* guard) makes the tenant filter per-route rather than per-handler:

        @server_teams_bp.route('/<team_id>', methods=['GET'])
        @require_user_auth
        @require_team_in_tenant
        def get_team(team_id): ...

    Mechanism:
      * Pull `team_id` from URL kwargs, query string, or JSON body (in that order).
      * Resolve `team.tenant_id` from the DB (one round trip per call — the
        callers are already paying an auth round trip in their route).
      * Platform admins / service callers are exempt (same convention as
        enforce_team_scope()).
      * Otherwise, the team's tenant_id must be in the caller's
        `_caller_tenant_ids()` set.

    Returns a 403 response tuple on mismatch, or None to continue (the
    decorator returns the wrapped function's result via the JSON 403 path).
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        requested = (
            kwargs.get('team_id')
            or request.args.get('team_id')
            or ((request.get_json(silent=True) or {}).get('team_id'))
        )
        if not requested:
            # No team named — the route's own `team_id is required` validation applies.
            return f(*args, **kwargs)

        if _caller_is_platform_admin():
            return f(*args, **kwargs)

        if getattr(request, 'user_role', None) == 'service':
            return f(*args, **kwargs)

        team_tenant_id = _team_tenant_id_from_db(requested)
        if team_tenant_id is None:
            # Team doesn't exist or lookup failed. Defer to the route's own
            # 404 logic — the decorator is about scope, not existence.
            return f(*args, **kwargs)

        if team_tenant_id in _caller_tenant_ids():
            return f(*args, **kwargs)

        print(f"[@auth_middleware] \u26d4 tenant scope: {getattr(request, 'user_email', '?')} "
              f"asked for team {requested} (tenant {team_tenant_id}) on {request.method} {request.path}")
        return jsonify({
            'error': 'Forbidden',
            'message': 'You do not belong to the tenant that owns this team.',
        }), 403
    return decorated_function


def _team_tenant_id_from_db(team_id: str) -> Optional[str]:
    """Resolve a team's tenant_id. None if the team is missing or lookup fails."""
    try:
        from shared.src.lib.utils.supabase_utils import get_supabase_admin
        sb = get_supabase_admin()
        if sb is None:
            return None
        rows = (
            sb.table('teams')
            .select('tenant_id')
            .eq('id', team_id)
            .limit(1)
            .execute()
        ).data or []
        if not rows:
            return None
        return str(rows[0].get('tenant_id') or '') or None
    except Exception as e:
        print(f"[@auth_middleware] team.tenant_id lookup failed for {team_id}: {e}")
        return None
