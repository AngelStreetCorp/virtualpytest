-- TASK-104 goal 11 (TASK-88 row 12): "Wrong screen?" corrects the matcher, and every correction is
-- audited here so it can be seen and undone. Choosing the true node adds the live fingerprint as an
-- extra sample on that node (navigation_nodes.data.fingerprint.extra); "Unknown screen" adds it as a
-- negative on the node that wrongly claimed the frame (data.fingerprint.negatives). Each entry carries
-- the verdict id, so undo removes exactly what this row added.
-- Also: screen_fingerprints.label, the name Localize's known_screen verdict shows (TASK-104 goal 10).
-- Idempotent.

BEGIN;

CREATE TABLE IF NOT EXISTS public.localize_verdicts (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    team_id             UUID NOT NULL,
    userinterface_name  TEXT NOT NULL,
    host_name           TEXT,
    device_id           TEXT,
    frame_url           TEXT,
    live_fingerprint    JSONB NOT NULL,
    action              TEXT NOT NULL CHECK (action IN ('add_sample', 'negative')),
    wrong_node_id       TEXT,
    wrong_node_label    TEXT,
    true_node_id        TEXT,
    true_node_label     TEXT,
    node_row_ids        UUID[] NOT NULL DEFAULT '{}',
    tree_ids            UUID[] NOT NULL DEFAULT '{}',
    created_by          TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    undone_at           TIMESTAMPTZ,
    undone_by           TEXT
);

CREATE INDEX IF NOT EXISTS idx_localize_verdicts_team_created
    ON public.localize_verdicts (team_id, created_at DESC);

COMMENT ON TABLE public.localize_verdicts IS
    'TASK-104 goal 11: Localize "Wrong screen?" corrections. add_sample = live fingerprint added to the true '
    'node; negative = added as not-this-screen on the wrong node. undone_at set when reverted.';

ALTER TABLE public.localize_verdicts ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "service_role_all_localize_verdicts" ON public.localize_verdicts;
CREATE POLICY "service_role_all_localize_verdicts" ON public.localize_verdicts
    FOR ALL TO service_role USING (true) WITH CHECK (true);
REVOKE ALL ON public.localize_verdicts FROM anon, authenticated;

ALTER TABLE public.screen_fingerprints ADD COLUMN IF NOT EXISTS label TEXT;

COMMIT;
