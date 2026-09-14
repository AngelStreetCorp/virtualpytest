-- Create / ensure anon and authenticated roles exist (idempotent).
-- webhooks.sql also creates these but we recreate them here as a safety net
-- so jwt.sql failing can never leave the DB in a broken state.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
    CREATE ROLE anon NOLOGIN;
  END IF;
END
$$;
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
    CREATE ROLE authenticated NOLOGIN;
  END IF;
END
$$;
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
    CREATE ROLE service_role NOLOGIN;
  END IF;
END
$$;

-- No grants here: the supabase/postgres image already gives anon / authenticated /
-- service_role the standard default privileges, and setup/db/apply_schema.sh closes
-- the app tables to anon afterwards (TASK-10 posture). Re-granting on every start
-- would silently undo that lockdown.

-- Set JWT secret and expiry at database level (PostgREST reads this via PGRST_JWT_SECRET)
\set jwt_secret `echo "$JWT_SECRET"`
\set jwt_exp `echo "$JWT_EXPIRY:-3600"`

ALTER DATABASE postgres SET "app.settings.jwt_secret" TO :'jwt_secret';
ALTER DATABASE postgres SET "app.settings.jwt_exp" TO :'jwt_exp';
