-- 070 — per-user executable favorites (TASK-100). Same content as migration 20261014d_executable_favorites.sql.
-- WRITTEN, NOT APPLIED.
-- One row = one starred executable for one user in one team. `kind` is part of the key because a script
-- name, a test case uuid and a campaign id live in separate namespaces. `item_id` per kind:
--   script          the listed id, e.g. 'goto.py' or 'gw/superping.py'
--   virtual_script  the script name (no .py); stable across the dev/test/prod rows
--   testcase        testcase_id (uuid)
--   campaign        campaign_id (uuid) for a stored campaign, the script reference for a file campaign
-- user_id is TEXT (no FK): the auto-sign test principal has no UUID. RLS: service_role only. Idempotent.

BEGIN;

CREATE TABLE IF NOT EXISTS public.executable_favorites (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    team_id     UUID NOT NULL REFERENCES public.teams(id) ON DELETE CASCADE,
    user_id     TEXT NOT NULL,
    kind        TEXT NOT NULL CHECK (kind IN ('script', 'testcase', 'virtual_script', 'campaign')),
    item_id     TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT executable_favorites_unique UNIQUE (team_id, user_id, kind, item_id)
);

CREATE INDEX IF NOT EXISTS idx_executable_favorites_user ON public.executable_favorites (team_id, user_id);

COMMENT ON TABLE public.executable_favorites IS
    'TASK-100: executables a user starred, per team. Key (team_id, user_id, kind, item_id); kind is script | testcase | virtual_script | campaign.';

ALTER TABLE public.executable_favorites ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "service_role_all_executable_favorites" ON public.executable_favorites;
CREATE POLICY "service_role_all_executable_favorites" ON public.executable_favorites FOR ALL TO service_role USING (true) WITH CHECK (true);
REVOKE ALL ON public.executable_favorites FROM anon, authenticated;

COMMIT;
