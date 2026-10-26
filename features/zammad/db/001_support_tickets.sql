-- features/zammad/db/001_support_tickets.sql (was setup/db/migrations/20261014a_support_tickets.sql)
-- TASK-96 G3 — index of support tickets per team. Applied on the lab DB 2026-10-14.
--   support_tickets  one row per ticket opened from the app. The thread itself lives in the helpdesk
--                    (external_provider / external_id, Zammad first); this is only the team-scoped index.
-- Every read filters by team_id. RLS: service_role only (anon / authenticated denied, like the other app tables).
-- Idempotent. Feature-owned: not deployed when `zammad` is in DISABLED_FEATURES. Inverse: 001_support_tickets_rollback.sql.

BEGIN;

CREATE TABLE IF NOT EXISTS public.support_tickets (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    team_id           UUID NOT NULL REFERENCES public.teams(id) ON DELETE CASCADE,
    category          TEXT NOT NULL CHECK (category IN ('device', 'host', 'system', 'script', 'dashboard', 'platform')),
    entity_type       TEXT,
    entity_id         TEXT,
    title             TEXT NOT NULL,
    status            TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'pending', 'closed')),
    external_provider TEXT NOT NULL DEFAULT 'zammad',
    external_id       TEXT NOT NULL,
    external_number   TEXT,
    created_by        TEXT NOT NULL,
    created_by_email  TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (external_provider, external_id)
);

CREATE INDEX IF NOT EXISTS idx_support_tickets_team_created ON public.support_tickets (team_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_support_tickets_team_entity ON public.support_tickets (team_id, entity_type, entity_id);

COMMENT ON TABLE public.support_tickets IS
    'TASK-96: index of support tickets per team. The conversation lives in the helpdesk (external_provider/external_id); status mirrors it (open | pending | closed).';

ALTER TABLE public.support_tickets ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "service_role_all_support_tickets" ON public.support_tickets;
CREATE POLICY "service_role_all_support_tickets" ON public.support_tickets FOR ALL TO service_role USING (true) WITH CHECK (true);
REVOKE ALL ON public.support_tickets FROM anon, authenticated;

COMMIT;
