import logging
import os
import sys
from typing import Optional

# Ensure global typing compatibility for all third-party packages
from shared.src.lib.utils.typing_compatibility import ensure_typing_compatibility
ensure_typing_compatibility()

# Import the real supabase package by temporarily manipulating sys.path
def _import_real_supabase():
    """Import the real supabase package, avoiding our local supabase directory."""
    # Temporarily remove paths that might contain our local supabase directory
    original_path = sys.path.copy()
    try:
        # Remove any paths that might contain our local supabase directory
        filtered_path = [p for p in sys.path if not p.endswith('/virtualpytest') and 'shared/lib' not in p]
        sys.path[:] = filtered_path
        
        # Import using the API from supabase==2.18.1 (must match requirements.txt)
        from supabase import create_client, Client
        return create_client, Client
    finally:
        # Restore original path
        sys.path[:] = original_path

create_client, Client = _import_real_supabase()

import httpx
from supabase.lib.client_options import SyncClientOptions

# ---------------------------------------------------------------------------
# HTTP transport tuning for the DB client (BUG-0093)
#
# Hosts reach Supabase over the WAN, and on at least one site (vpt-pi1) the
# router drops a share of *outbound* TCP SYNs — established connections are
# fine, it is connection setup that fails. Measured there: a new connection per
# request gave 1/30 outright failures and 3/30 over 2s (max 15.3s), while one
# reused keep-alive connection gave 0/30 and a 0.25s max.
#
# Left at the library defaults that combination is what made vpt-pi1 vanish from
# the UI: postgrest's default timeout is 120s, so a single dropped SYN stalled
# the caller for two minutes, the host's ping thread missed its cadence, and the
# server evicted it from the registry.
#
# Three settings, all overridable from the environment:
#   - a short connect timeout, so a dropped SYN fails in seconds, not minutes
#   - connection retries, so the common case (one dropped SYN) self-heals
#   - a keep-alive expiry LONGER than any caller's polling interval, so periodic
#     callers reuse a warm connection instead of paying for a new one each cycle
#     (httpx's default is 5s, against a 60s host metrics cycle — always cold)
# ---------------------------------------------------------------------------
DB_CONNECT_TIMEOUT_SECONDS = float(os.environ.get("DB_CONNECT_TIMEOUT_SECONDS", "5"))
DB_READ_TIMEOUT_SECONDS = float(os.environ.get("DB_READ_TIMEOUT_SECONDS", "20"))
DB_CONNECT_RETRIES = int(os.environ.get("DB_CONNECT_RETRIES", "2"))
DB_KEEPALIVE_EXPIRY_SECONDS = float(os.environ.get("DB_KEEPALIVE_EXPIRY_SECONDS", "300"))


def _build_db_http_client() -> httpx.Client:
    """An httpx client that fails fast on a dropped SYN and keeps connections warm."""
    return httpx.Client(
        # retries applies to connection establishment only — it never replays a
        # request that already reached the server, so it is safe for writes.
        transport=httpx.HTTPTransport(retries=DB_CONNECT_RETRIES),
        timeout=httpx.Timeout(
            DB_READ_TIMEOUT_SECONDS,
            connect=DB_CONNECT_TIMEOUT_SECONDS,
        ),
        limits=httpx.Limits(
            max_connections=20,
            max_keepalive_connections=10,
            keepalive_expiry=DB_KEEPALIVE_EXPIRY_SECONDS,
        ),
        follow_redirects=True,
    )


def _db_client_options() -> SyncClientOptions:
    """Client options carrying the tuned HTTP transport above."""
    return SyncClientOptions(httpx_client=_build_db_http_client())

def _loud(message: str) -> None:
    """Report a credential/connectivity problem so it cannot be missed.

    Deliberately writes to stderr with flush=True *and* logs, because neither
    alone is reliable here (BUG-0109):

      - plain print() goes to a block-buffered stdout when systemd owns the
        pipe, so a warning can sit unseen for minutes while logger.info lines
        from the same process appear immediately. That is exactly how three
        hosts ran on the anon key for 9 days without anyone noticing.
      - logging config differs per service (capture_monitor configures its own
        named logger, others rely on the root logger), so a module-level logger
        is not guaranteed to be wired up.

    stderr is StandardError=journal in every vpt-*.service unit, so this always
    lands in journalctl immediately.
    """
    print(message, file=sys.stderr, flush=True)
    try:
        logging.getLogger(__name__).error(message)
    except Exception:
        pass  # logging must never be the reason a caller fails


# Global variables to hold the lazily-loaded clients
_supabase_client: Optional[Client] = None
_supabase_admin_client: Optional[Client] = None

def get_supabase_client() -> Optional[Client]:
    """Get the Supabase client instance with lazy loading."""
    global _supabase_client
    
    if _supabase_client is None:
        try:
            # Only try to create client when actually needed.
            # TASK-10: trusted server/host processes should run on the service_role
            # key (bypasses RLS). Prefer it; fall back to the anon key with a loud
            # warning so a node that has not been migrated yet is obvious in the logs.
            url: str = os.environ.get("SUPABASE_URL")
            service_key: str = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
            key: str = service_key or os.environ.get("SUPABASE_ANON_KEY")

            print(f"[@supabase_utils:get_supabase_client] 🔍 Checking environment variables...")
            print(f"[@supabase_utils:get_supabase_client]    URL present: {bool(url)}")
            print(f"[@supabase_utils:get_supabase_client]    Key present: {bool(key)}")
            if key and not service_key:
                # Post-lockdown the anon role has no grants on most tables, so this is a
                # hard failure dressed as a fallback: every write will come back 401 /
                # "permission denied for table ..." (42501). Usually it means the service
                # is holding a stale environment — it reads .env once at startup, so a
                # credential change needs a restart on this host (BUG-0109). Check with:
                #   stat -c %y /opt/virtualpytest/.env
                #   systemctl show -p ExecMainStartTimestamp --value <unit>
                _loud("[@supabase_utils:get_supabase_client] ❌ DB CLIENT IS ON THE ANON KEY — "
                      "SUPABASE_SERVICE_ROLE_KEY is not in this process's environment. Every DB "
                      "write will fail with 401 / permission denied (42501). If .env is newer "
                      "than this service's start time, restart the service to pick it up "
                      "(BUG-0109). See TASK-10.")

            if url and key:
                # Create client
                print(f"[@supabase_utils:get_supabase_client] 🔄 Creating Supabase client for: {url}")
                try:
                    _supabase_client = create_client(url, key, options=_db_client_options())
                    print(f"[@supabase_utils:get_supabase_client] ✅ Supabase client initialized successfully")
                except Exception as client_error:
                    import traceback
                    _loud(f"[@supabase_utils:get_supabase_client] ❌ FAILED TO CREATE DB CLIENT: "
                          f"{type(client_error).__name__}: {client_error} — every database operation "
                          f"in this process will be skipped silently (BUG-0109).")
                    traceback.print_exc(file=sys.stderr)
                    return None
            else:
                missing = []
                if not url:
                    missing.append("SUPABASE_URL")
                if not key:
                    missing.append("SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY")
                _loud(f"[@supabase_utils:get_supabase_client] ❌ NO DB CLIENT — missing environment "
                      f"variables: {', '.join(missing)}. Every database operation in this process "
                      f"will be skipped silently. Check the unit's EnvironmentFile and that .env is "
                      f"readable by the service user (BUG-0109).")
                return None
        except Exception as e:
            import traceback
            print(f"[@supabase_utils:get_supabase_client] ❌ Unexpected error: {e}")
            print(f"[@supabase_utils:get_supabase_client] 🔍 Error type: {type(e).__name__}")
            print(f"[@supabase_utils:get_supabase_client] 🔍 Traceback:")
            traceback.print_exc()
            return None

    return _supabase_client


def get_supabase_admin() -> Optional[Client]:
    """Get a Supabase client using the service_role key (bypasses RLS).

    Required for the Auth Admin API (auth.admin.create_user / delete_user).
    The anon client returned by get_supabase_client() cannot perform these.
    Lazily created; server-side only — never expose this client or its key.
    """
    global _supabase_admin_client

    if _supabase_admin_client is None:
        url: str = os.environ.get("SUPABASE_URL")
        key: str = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")

        print(f"[@supabase_utils:get_supabase_admin] 🔍 Checking environment variables...")
        print(f"[@supabase_utils:get_supabase_admin]    URL present: {bool(url)}")
        print(f"[@supabase_utils:get_supabase_admin]    Service role key present: {bool(key)}")

        if not (url and key):
            missing = []
            if not url:
                missing.append("SUPABASE_URL")
            if not key:
                missing.append("SUPABASE_SERVICE_ROLE_KEY")
            _loud(f"[@supabase_utils:get_supabase_admin] ❌ NO ADMIN DB CLIENT — missing environment "
                  f"variables: {', '.join(missing)}. Admin operations will be skipped silently. If "
                  f".env is newer than this service's start time, restart it (BUG-0109).")
            return None

        try:
            print(f"[@supabase_utils:get_supabase_admin] 🔄 Creating Supabase admin client for: {url}")
            _supabase_admin_client = create_client(url, key, options=_db_client_options())
            print(f"[@supabase_utils:get_supabase_admin] ✅ Supabase admin client initialized successfully")
        except Exception as client_error:
            import traceback
            _loud(f"[@supabase_utils:get_supabase_admin] ❌ FAILED TO CREATE ADMIN DB CLIENT: "
                  f"{type(client_error).__name__}: {client_error} — admin operations will be "
                  f"skipped silently (BUG-0109).")
            traceback.print_exc(file=sys.stderr)
            return None

    return _supabase_admin_client


def get_db_key_role() -> str:
    """Report which Postgres role the DB client (get_supabase_client) runs as.

    This mirrors the key-selection logic in get_supabase_client() — service_role
    key preferred, anon key as fallback — and returns one of:
      "service_role" | "anon" | "none" | "unknown"

    Handles both key formats: new-style publishable/secret keys
    (sb_publishable_… / sb_secret_…) and legacy JWTs (eyJ…, role in the claims).
    Used by the server/host health routes as the TASK-10 rollout verification
    signal — a node still reading "anon" has not been migrated yet.
    """
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_ANON_KEY")
    if not key:
        return "none"
    # New-style keys carry the role in their prefix.
    if key.startswith("sb_secret_"):
        return "service_role"
    if key.startswith("sb_publishable_"):
        return "anon"
    # Legacy Supabase keys are JWTs with a "role" claim.
    if key.startswith("eyJ"):
        try:
            import base64
            import json

            payload = key.split(".")[1]
            payload += "=" * (-len(payload) % 4)  # pad to a multiple of 4
            claims = json.loads(base64.urlsafe_b64decode(payload.encode()))
            return claims.get("role", "unknown")
        except Exception:
            return "unknown"
    return "unknown"