"""Two-factor admin auth for sensitive backend_host endpoints.

The host backend does not have role-based auth (it's stateless, no JWT),
so admin-only endpoints are gated with a second token pulled from
`VPT_HOST_ADMIN_TOKEN`. The global API key gate (see
`backend_host/src/app.py:setup_api_authentication`) still runs first;
this decorator adds a second check on top.

Behavior:
- The env var `VPT_HOST_ADMIN_TOKEN` is read on every request (cheap,
  but lets an operator rotate the token without a restart). If unset,
  every protected route returns 403 with `error: admin token not
  configured` so a misconfigured deployment fails closed, not open.
- The caller must send `Authorization: Admin <token>` (constant
  prefix, case-insensitive). The token is compared with
  `hmac.compare_digest` to avoid timing leaks.

This is intentionally narrow:
- It does NOT change behavior for non-admin endpoints (`/health`,
  `/host/system/services/status`, etc. stay API-key-only).
- A leaked API key alone is no longer enough to invoke
  `/host/desktop/bash/executeCommand` or `/host/system/runCommand`
  (the two endpoints flagged by the CodeQL audit as Critical due to
  shell injection surface).
- A leaked admin token alone is also not enough — API key check runs
  first.
"""
import functools
import hmac
import os

from flask import jsonify, request


# Header name + scheme prefix the caller must use.
ADMIN_AUTH_HEADER = "Authorization"
ADMIN_AUTH_SCHEME = "Admin"


def get_admin_token() -> str:
    """Read VPT_HOST_ADMIN_TOKEN on every call. Rotating the env var is
    enough to rotate the token — no restart needed.

    Returns the token as a string, or '' when unset. The empty-string
    sentinel intentionally fails every compare; callers must treat
    unset as 'deny by default'.
    """
    return (os.environ.get("VPT_HOST_ADMIN_TOKEN") or "").strip()


def require_admin_token(func):
    """Decorator: in addition to the global /host/* API key check, the
    caller must present `Authorization: Admin <VPT_HOST_ADMIN_TOKEN>`.

    Returns 403 if the token is unconfigured OR if the supplied token
    does not match. The 403 (not 401) is deliberate: we don't want to
    reveal to a probing attacker whether the admin token is
    configured vs whether they got it wrong.
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        configured = get_admin_token()
        if not configured:
            print(
                f"[@backend_host:auth] \u26d4 admin token not configured; "
                f"denying {request.path}",
                flush=True,
            )
            return jsonify({
                "success": False,
                "error": "admin token not configured on this host",
            }), 403

        auth = request.headers.get(ADMIN_AUTH_HEADER, "")
        # Expected: "Admin <token>" — exactly one space, no internal whitespace.
        # We deliberately do NOT strip the supplied value; sloppy headers
        # should fail closed. Scheme is case-insensitive ("admin" / "ADMIN"
        # both work) since the value is compared case-sensitively to a
        # high-entropy random token where case does not matter.
        parts = auth.split(" ", 1)
        if len(parts) != 2 or parts[0].lower() != ADMIN_AUTH_SCHEME.lower():
            return jsonify({
                "success": False,
                "error": f"missing or malformed {ADMIN_AUTH_HEADER}: {ADMIN_AUTH_SCHEME} <token>",
            }), 403

        supplied = parts[1]
        if not hmac.compare_digest(supplied.encode("utf-8"), configured.encode("utf-8")):
            print(
                f"[@backend_host:auth] \u26d4 admin token mismatch for "
                f"{request.path} from {request.remote_addr}",
                flush=True,
            )
            return jsonify({
                "success": False,
                "error": "admin token mismatch",
            }), 403

        return func(*args, **kwargs)

    return wrapper
