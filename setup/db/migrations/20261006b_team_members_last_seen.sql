-- ============================================================================
-- 20261006b_team_members_last_seen.sql
-- TASK-65 — Projects (first-class concept). Phase 1 plan artifact.
--
-- Adds:
--   * team_members.last_seen_at TIMESTAMPTZ NULL
--   * idx_team_members_last_seen_at (team_id, last_seen_at DESC)
--
-- Used by the "Active users" tile on /projects/<id>:
--     Active = last_seen_at > now() - 5 minutes
-- Updated by PUT /server/team/last_seen (throttled to 60 s, idempotent UPSERT).
--
-- This file is a BLUEPRINT committed on the task65-projects branch. It is NOT
-- applied yet. The data_migrations guard row at the bottom is commented out
-- so accidental tooling runs do not flag this migration as applied.
--
-- Idempotent (ADD COLUMN IF NOT EXISTS, CREATE INDEX IF NOT EXISTS).
-- ============================================================================

BEGIN;

ALTER TABLE public.team_members
    ADD COLUMN IF NOT EXISTS last_seen_at TIMESTAMPTZ NULL;

CREATE INDEX IF NOT EXISTS idx_team_members_last_seen_at
    ON public.team_members (team_id, last_seen_at DESC);

COMMENT ON COLUMN public.team_members.last_seen_at IS
    'TASK-65 — Last heartbeat from this team member (PUT /server/team/last_seen, '
    'throttled to 60 s). Used by the Active Users tile on /projects/<id>. '
    'Phase 1 plan artifact.';

-- ============================================================================
-- data_migrations guard row — commented out so Phase 1 does NOT apply.
-- See docs/tasks/TASK-65-projects.md §G8 for the Phase 2 commit that
-- uncomments this row and applies the migration.
-- ============================================================================
-- INSERT INTO public.data_migrations (name) VALUES ('20261006b_team_members_last_seen')
-- ON CONFLICT (name) DO NOTHING;

COMMIT;