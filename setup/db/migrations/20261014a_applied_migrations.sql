-- TASK-95 G5: tracker of the SQL migrations applied to THIS database, so the Platform update page can list the pending ones.
-- Platform-global (not team-scoped): the schema belongs to the install, like role_permissions. Service role only.
-- WRITTEN, NOT APPLIED. Idempotent. Apply it from Platform update -> step 3 ("Create tracker"), or by hand.
-- A fresh table is EMPTY: the existing migrations are recorded once with "Mark as already applied" on the page.
-- Twin: setup/db/schema/068_applied_migrations.sql. Inverse: 20261014a_applied_migrations_rollback.sql.

BEGIN;

CREATE TABLE IF NOT EXISTS public.applied_migrations (
    filename    TEXT PRIMARY KEY,
    applied_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    applied_by  TEXT,
    method      TEXT NOT NULL DEFAULT 'page' CHECK (method IN ('page', 'baseline', 'manual'))
);

COMMENT ON TABLE public.applied_migrations IS
    'TASK-95: setup/db/migrations files applied to this database. method = page (run by Platform update), baseline (marked as already applied, not run), manual.';

ALTER TABLE public.applied_migrations ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "service_role_all_applied_migrations" ON public.applied_migrations;
CREATE POLICY "service_role_all_applied_migrations" ON public.applied_migrations
    FOR ALL TO service_role USING (true) WITH CHECK (true);
REVOKE ALL ON public.applied_migrations FROM anon, authenticated;

COMMIT;
