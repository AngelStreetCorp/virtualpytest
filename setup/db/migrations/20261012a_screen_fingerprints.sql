-- TASK-84: screen memory. One row per distinct screen a device with no userinterface showed
-- when a freeze alert opened. The host stamps alerts.metadata.screen_id; the triage worker
-- (vpt-discard-incidents) records its verdict on the row and, once a screen is trusted as
-- "expected", discards later alerts on it without a model call. Idempotent.

BEGIN;

CREATE TABLE IF NOT EXISTS public.screen_fingerprints (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    team_id             UUID NOT NULL,
    scope               TEXT NOT NULL,
    incident_type       TEXT NOT NULL,
    dhash               TEXT NOT NULL,
    region_center       TEXT NOT NULL,
    verdict             TEXT NOT NULL DEFAULT 'unknown' CHECK (verdict IN ('unknown','expected','bad')),
    source              TEXT NOT NULL DEFAULT 'none' CHECK (source IN ('none','ai','human')),
    verdict_by          TEXT,
    ai_votes_expected   INTEGER NOT NULL DEFAULT 0,
    ai_votes_bad        INTEGER NOT NULL DEFAULT 0,
    seen_count          INTEGER NOT NULL DEFAULT 1,
    first_seen          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_seen           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    sample_image_path   TEXT,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_screen_fingerprints_lookup
    ON public.screen_fingerprints (team_id, scope, incident_type);

COMMENT ON TABLE public.screen_fingerprints IS
    'TASK-84 screen memory. scope = host_name/device_id. Written by the host (new screens, seen_count) '
    'and by vpt-server (verdicts). A human verdict is never overwritten by an AI one.';

ALTER TABLE public.screen_fingerprints ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "service_role_all_screen_fingerprints" ON public.screen_fingerprints;
CREATE POLICY "service_role_all_screen_fingerprints" ON public.screen_fingerprints
    FOR ALL TO service_role USING (true) WITH CHECK (true);
REVOKE ALL ON public.screen_fingerprints FROM anon, authenticated;

COMMIT;
