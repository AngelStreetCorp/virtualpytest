-- TASK-99 — per-user device favorites. WRITTEN, NOT YET APPLIED: apply only after the owner signs off.
-- One row = one starred device for one user in one team. The key includes host_name because device
-- names/ids collide across servers. user_id is TEXT (no FK): the auto-sign test principal has no UUID.
-- RLS: service_role only (the server reads and writes it). Idempotent. Same content as schema/069_device_favorites.sql.

BEGIN;

CREATE TABLE IF NOT EXISTS public.device_favorites (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    team_id     UUID NOT NULL REFERENCES public.teams(id) ON DELETE CASCADE,
    user_id     TEXT NOT NULL,
    host_name   TEXT NOT NULL,
    device_id   TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT device_favorites_unique UNIQUE (team_id, user_id, host_name, device_id)
);

CREATE INDEX IF NOT EXISTS idx_device_favorites_user ON public.device_favorites (team_id, user_id);

COMMENT ON TABLE public.device_favorites IS
    'TASK-99: devices a user starred, per team. Key (team_id, user_id, host_name, device_id); host_name is part of the key because device ids collide across servers.';

ALTER TABLE public.device_favorites ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "service_role_all_device_favorites" ON public.device_favorites;
CREATE POLICY "service_role_all_device_favorites" ON public.device_favorites FOR ALL TO service_role USING (true) WITH CHECK (true);
REVOKE ALL ON public.device_favorites FROM anon, authenticated;

COMMIT;
