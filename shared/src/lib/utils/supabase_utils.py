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
                print(f"[@supabase_utils:get_supabase_client] ⚠️ DB client running on the ANON key — see TASK-10")

            if url and key:
                # Create client
                print(f"[@supabase_utils:get_supabase_client] 🔄 Creating Supabase client for: {url}")
                try:
                    _supabase_client = create_client(url, key)
                    print(f"[@supabase_utils:get_supabase_client] ✅ Supabase client initialized successfully")
                except Exception as client_error:
                    import traceback
                    print(f"[@supabase_utils:get_supabase_client] ❌ Failed to create client: {client_error}")
                    print(f"[@supabase_utils:get_supabase_client] 🔍 Error type: {type(client_error).__name__}")
                    print(f"[@supabase_utils:get_supabase_client] 🔍 Traceback:")
                    traceback.print_exc()
                    return None
            else:
                missing = []
                if not url:
                    missing.append("SUPABASE_URL")
                if not key:
                    missing.append("SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY")
                print(f"[@supabase_utils:get_supabase_client] ⚠️ Missing environment variables: {', '.join(missing)}")
                print(f"[@supabase_utils:get_supabase_client]    Client not available")
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
            print(f"[@supabase_utils:get_supabase_admin] ⚠️ Missing environment variables: {', '.join(missing)}")
            print(f"[@supabase_utils:get_supabase_admin]    Admin client not available")
            return None

        try:
            print(f"[@supabase_utils:get_supabase_admin] 🔄 Creating Supabase admin client for: {url}")
            _supabase_admin_client = create_client(url, key)
            print(f"[@supabase_utils:get_supabase_admin] ✅ Supabase admin client initialized successfully")
        except Exception as client_error:
            import traceback
            print(f"[@supabase_utils:get_supabase_admin] ❌ Failed to create admin client: {client_error}")
            print(f"[@supabase_utils:get_supabase_admin] 🔍 Error type: {type(client_error).__name__}")
            traceback.print_exc()
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