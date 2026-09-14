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
        "/server/* served without a credential (dev/trusted-net only)."
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
    """Explicit, dev-only opt-in to serve `/server/*` with no credential.

    Default **off**: the platform is closed by default. Set `SERVER_OPEN_MODE=true`
    only on local dev or a trusted isolated network. Replaces the old implicit
    "no JWT secret ⇒ open" behaviour.
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
            # Role lives in app_metadata (server-controlled, synced from
            # profiles.role by the on_profile_role_sync trigger). Fall back to
            # user_metadata for tokens minted before the sync existed.
            request.user_role = app_meta.get('role') or meta.get('role', 'viewer')
            request.user_metadata = meta
            request.user_permissions = meta.get('permissions', [])
            request.user_denied_permissions = meta.get('denied_permissions', [])
            
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


def require_permission(permission: str) -> Callable:
    """
    Decorator to require a specific fine-grained permission (resource:action format).
    Must be used AFTER @require_user_auth.

    Permission resolution order:
      1. Admin role → always allowed
      2. Denied permissions on request → reject
      3. Role defaults + individual grants → check membership

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

            # Admin has all permissions (denials do not apply to admin)
            if user_role == 'admin':
                print(f"[@auth_middleware] ✅ Admin has permission: {permission}")
                return f(*args, **kwargs)

            # The shared X-API-Key principal (host->server callbacks, provisioning, CI,
            # backend->backend). It has no entry in the role matrix, so without this it
            # would fail every permission check and break host callbacks. Same rationale
            # as ADMIN_ROLES above: the key already drives /host/* directly.
            if user_role == 'service':
                return f(*args, **kwargs)

            denied = set(getattr(request, 'user_denied_permissions', []))
            if permission in denied:
                return jsonify({
                    'error': 'Forbidden',
                    'message': f'Permission explicitly denied: {permission}',
                    'user_role': user_role
                }), 403

            # Role defaults (resource:action format)
            role_defaults: dict = {
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
                    'plugins.jira:view', 'plugins.jira:manage',
                    'settings.status:view',
                },
                'viewer': {
                    'dashboard:view',
                    'testcases:view', 'campaigns:view',
                    'reports.tests:view', 'reports.campaigns:view',
                    'reports.models:view', 'reports.dependency:view',
                    'monitoring.incidents:view', 'monitoring.heatmap:view', 'monitoring.ai_queue:view',
                    'settings.status:view',
                },
            }

            individual_grants = set(getattr(request, 'user_permissions', []))
            allowed = role_defaults.get(user_role, set()) | individual_grants

            if permission not in allowed:
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
                # See require_user_auth: role comes from app_metadata.
                request.user_role = app_meta.get('role') or meta.get('role', 'viewer')
                request.user_metadata = meta
                request.user_permissions = meta.get('permissions', [])
                request.user_denied_permissions = meta.get('denied_permissions', [])

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
    Enforce JWT auth for the current Flask request when auth is enabled.

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
    # X-API-Key instead of a user JWT. Allow them through the frontend-JWT guard.
    if _is_valid_service_api_key():
        request.user_id = 'service_api_key'
        request.user_email = 'service@local'
        request.user_role = 'service'
        request.user_metadata = {'service_api_key': True}
        request.user_permissions = []
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
        _log_open_mode_warning_once()
        request.user_id = 'open_mode'
        request.user_email = 'open@local'
        request.user_role = _get_server_public_role()
        request.user_metadata = {'server_open_mode': True}
        request.user_permissions = []
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
    must get 403 (docs/technical/permissions/PERMISSION_PLAN.md). Runs after the global
    guard in app.py, which is what sets request.user_role, so it needs no @require_user_auth
    of its own.
    """
    return require_role(*ADMIN_ROLES)(f)


# Aliases for common usage patterns
require_auth = require_user_auth
require_admin = require_role('admin')
