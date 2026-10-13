"""Trigger provenance: who launched a run, as shown in the report's `Trigger:` line."""

from typing import Optional

from flask import request

# Identities the auth guard assigns when there is no per-user login
# (backend_server/src/lib/auth_middleware.py).
_NO_LOGIN_IDENTITIES = {'auto_signed', 'open_mode', 'public_key'}


def resolve_caller_user(body_user_id: Optional[str], user_name: Optional[str] = None) -> Optional[str]:
    """Label for trigger.caller_user when the caller did not send its own.

    - VirtualPyTest UI, logged-in user  -> `vpt_user:<full name | email | id>`
      The identity comes from the verified JWT, never from the body `user_id`.
    - VirtualPyTest UI without a login (open mode, public key, auto-sign in a browser)
                                        -> `vpt_user:<full name | open_mode | ...>`
    - Anything else (X-API-Key services such as a customer scheduler, CLI scripts)
                                        -> their own `user_id` / `X-User-ID`, unchanged.

    Scheduler runs never reach here: backend_host deployment_scheduler sets
    `vpt_deployment:<kind>:<name>` itself.
    """
    auth_id = getattr(request, 'user_id', None)

    if auth_id and auth_id != 'service_api_key' and auth_id not in _NO_LOGIN_IDENTITIES:
        meta = getattr(request, 'user_metadata', None) or {}
        name = (
            user_name
            or meta.get('full_name')
            or meta.get('name')
            or getattr(request, 'user_email', None)
            or auth_id
        )
        return f"vpt_user:{name}"

    if auth_id in _NO_LOGIN_IDENTITIES:
        from backend_server.src.lib.auth_middleware import _looks_like_browser
        if _looks_like_browser():
            return f"vpt_user:{user_name or auth_id}"

    return body_user_id or request.headers.get('X-User-ID')
