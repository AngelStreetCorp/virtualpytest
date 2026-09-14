#!/usr/bin/env python3
"""
Create / refresh test accounts for the permission test suite.

Creates 4 Supabase users directly in the DB (bypasses disabled signups)
and generates 1-year JWTs signed with SUPABASE_JWT_SECRET.

The secret MUST be the exact string the backend_server you test against has in its
.env (auth_middleware verifies HS256 with it as-is: raw, not base64-decoded). It is
NOT necessarily the Postgres `app.settings.jwt_secret` — 2026-09-07 lesson: three
different values existed (server .env, DB setting, rpitest Pi); only the server's works.
Users get a random password and banned_until = 3000-01-01, so nobody can log in as them
through Supabase; only the tokens minted here authenticate.

Users created:
  admin.test@vpt.local   — role: admin
  tester.test@vpt.local  — role: tester
  viewer.test@vpt.local  — role: viewer
  runner.test@vpt.local  — role: viewer (team perms granted separately)

Password: random per run, never printed (Supabase login is banned anyway).

Output: tests/backend_server/.env.test.jwt  (gitignored)

Usage:
  python3 scripts/setup_test_accounts.py
"""

import datetime, os, subprocess, sys, uuid
import jwt as pyjwt

# ── Config ─────────────────────────────────────────────────────────────────
# Secrets must be provided via environment variables (never hardcode).
# Set SUPABASE_DB_URI and SUPABASE_JWT_SECRET in your .env or shell.
DB_DSN = os.environ.get("SUPABASE_DB_URI", "")
JWT_SECRET = os.environ.get("SUPABASE_JWT_SECRET", "")
import secrets as _secrets
TEST_PASSWORD = _secrets.token_urlsafe(24)  # never used interactively: logins are banned below

if not DB_DSN or not JWT_SECRET:
    sys.exit(
        "ERROR: SUPABASE_DB_URI and SUPABASE_JWT_SECRET must be set.\n"
        "  export SUPABASE_DB_URI='postgres://...'  \n"
        "  export SUPABASE_JWT_SECRET='<exact value from the target server .env>'"
    )

# UUIDs are stable — regenerating the script will reuse the same IDs
TEST_USERS = [
    {
        "id":       "12af5417-2d1f-4359-a82b-4698ca8b8a2c",
        "email":    "admin.test@vpt.local",
        "role":     "admin",
        "var":      "ADMIN",
    },
    {
        "id":       "ac1723d9-0d5d-40d2-99f2-b8a9d573a757",
        "email":    "tester.test@vpt.local",
        "role":     "tester",
        "var":      "TESTER",
    },
    {
        "id":       "55e91e04-19fa-411e-8e0b-6a54d172750e",
        "email":    "viewer.test@vpt.local",
        "role":     "viewer",
        "var":      "VIEWER",
    },
    {
        "id":       "7a009103-3c85-4dbd-80c4-78d32f6a313f",
        "email":    "runner.test@vpt.local",
        "role":     "viewer",   # viewer role; execution perms come from team
        "var":      "RUNNER",
    },
    {
        # Mutation target. The suite has ~14 tests that flip a user's role, rewrite their
        # permissions or move them between teams; they used to pick "users[0]" or "the first
        # non-admin", i.e. whichever REAL account happened to sort first — which today is a
        # real person's row. This account exists purely to be written to. Nothing
        # authenticates as it, so it gets no JWT.
        "id":       "71276050-1ec8-402a-9673-d5282cf29c9a",
        "email":    "mutable.test@vpt.local",
        "role":     "viewer",
        "var":      None,       # no token emitted
    },
]

OUT_FILE = os.path.join(
    os.path.dirname(__file__), "..", "tests", "backend_server", ".env.test.jwt"
)

# ── Helpers ─────────────────────────────────────────────────────────────────

def psql(sql: str) -> str:
    env = {**os.environ}
    r = subprocess.run(["psql", DB_DSN, "-c", sql],
                       capture_output=True, text=True, env=env)
    if r.returncode != 0 and r.stderr.strip():
        print(f"    psql warning: {r.stderr.strip()[:120]}")
    return r.stdout.strip()


def psql_file(path: str) -> str:
    env = {**os.environ}
    r = subprocess.run(["psql", DB_DSN, "-f", path],
                       capture_output=True, text=True, env=env)
    if r.returncode != 0 and r.stderr.strip():
        print(f"    psql warning: {r.stderr.strip()[:200]}")
    return r.stdout.strip()


def bcrypt_hash(password: str) -> str:
    try:
        import bcrypt as _bcrypt
        return _bcrypt.hashpw(password.encode(), _bcrypt.gensalt(rounds=10)).decode()
    except ImportError:
        sys.exit("bcrypt package required: pip install bcrypt")


def make_jwt(user: dict) -> str:
    secret = JWT_SECRET  # raw string, exactly as auth_middleware.py uses it
    now = datetime.datetime.now(datetime.timezone.utc)
    exp = now + datetime.timedelta(days=365)
    payload = {
        "sub": user["id"],
        "email": user["email"],
        "aud": "authenticated",
        "role": "authenticated",
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
        "user_metadata": {
            "role": user["role"],
            "email": user["email"],
            "permissions": [],
            "denied_permissions": [],
        },
        # auth_middleware reads the role from app_metadata first (server-controlled claim)
        "app_metadata": {"provider": "email", "providers": ["email"], "role": user["role"]},
    }
    return pyjwt.encode(payload, secret, algorithm="HS256")


# ── Main ─────────────────────────────────────────────────────────────────────

def apply_migrations() -> None:
    """Apply DB migrations if not already applied."""
    out = psql(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema='public' AND table_name='profiles' "
        "AND column_name='denied_permissions';"
    )
    if "denied_permissions" not in out:
        print("⚙  Applying migration 028…")
        base = os.path.join(os.path.dirname(__file__), "..", "setup", "db", "schema")
        psql_file(os.path.join(base, "028_permissions_expansion.sql"))
        psql_file(os.path.join(base, "029_permissions_rpc.sql"))
        print("   ✅ Migrations applied")
    else:
        print("   ✅ Migrations already in place")


def ensure_user_in_db(user: dict, pw_hash: str) -> None:
    """Insert user into auth.users + auth.identities if not already there."""
    uid, email = user["id"], user["email"]

    # auth.users
    psql(f"""
INSERT INTO auth.users (
  id, instance_id, aud, role, email, encrypted_password,
  email_confirmed_at, created_at, updated_at,
  raw_app_meta_data, raw_user_meta_data, is_super_admin, banned_until
) VALUES (
  '{uid}', '00000000-0000-0000-0000-000000000000',
  'authenticated', 'authenticated',
  '{email}', '{pw_hash}',
  NOW(), NOW(), NOW(),
  '{{"provider":"email","providers":["email"],"role":"{user["role"]}"}}',
  '{{"role":"{user["role"]}","email":"{email}"}}',
  false, '3000-01-01'
) ON CONFLICT (id) DO NOTHING;
""")

    # auth.identities (required for Supabase GoTrue login)
    psql(f"""
INSERT INTO auth.identities (
  provider_id, user_id, identity_data, provider,
  last_sign_in_at, created_at, updated_at, id
) VALUES (
  '{email}', '{uid}',
  '{{"sub":"{uid}","email":"{email}","email_verified":true}}',
  'email', NOW(), NOW(), NOW(), gen_random_uuid()
) ON CONFLICT (provider, provider_id) DO NOTHING;
""")

    # profiles role
    psql(f"""
UPDATE public.profiles SET role = '{user["role"]}' WHERE email = '{email}';
""")


def main() -> None:
    print("=" * 60)
    print("VirtualPyTest — Test Account Setup")
    print("=" * 60)

    apply_migrations()

    pw_hash = bcrypt_hash(TEST_PASSWORD)
    print("\nRandom password hashed (login banned; tokens are the only credential)")

    env_lines = [
        "# Auto-generated by scripts/setup_test_accounts.py",
        "# JWTs signed with SUPABASE_JWT_SECRET — expire in 1 year",
        "# DO NOT COMMIT",
    ]

    print()
    for user in TEST_USERS:
        label = user["var"] or "(no token)"
        print(f"▶ {label} ({user['email']}, role={user['role']})")
        ensure_user_in_db(user, pw_hash)

        # var=None means the account is never authenticated as — it is only ever written
        # to (the mutation target). Minting a token for it would be a credential with no
        # purpose, so create the row and stop there.
        if not user["var"]:
            print("  ✅ row only, no JWT minted")
            continue

        token = make_jwt(user)
        env_lines.append(f"{user['var']}_TEST_JWT={token}")
        print(f"  ✅ JWT: {token[:24]}…")

    admin = next(l for l in env_lines if l.startswith("ADMIN_TEST_JWT="))
    env_lines.append("AUTH_TEST_JWT=" + admin.split("=", 1)[1])  # generic authenticated user = admin
    env_lines.append("")
    os.makedirs(os.path.dirname(OUT_FILE), exist_ok=True)
    with open(OUT_FILE, "w") as f:
        f.write("\n".join(env_lines))

    print(f"\n✅ JWTs written to tests/backend_server/.env.test.jwt")
    print("\nTo run permission tests:")
    print("  cd tests/backend_server")
    print("  export $(cat .env.test.jwt | grep -v '#' | xargs)")
    print("  pytest test_permissions.py -v")
    print("\nTest accounts summary:")
    for u in TEST_USERS:
        print(f"  {u['email']:<30} / {TEST_PASSWORD}  → role: {u['role']}")


if __name__ == "__main__":
    main()
