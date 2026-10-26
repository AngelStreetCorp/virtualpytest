-- 068 — applied_migrations tracker (TASK-95). Same content as migration 20261014a_applied_migrations.sql.
-- WRITTEN, NOT APPLIED. Idempotent. A fresh install starts empty: record the existing migrations with
-- Platform update -> step 3 -> "Mark as already applied".

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
