-- 20260927a_ai_training_samples.sql
-- TASK-27 step 2. Index table for the vision-model training dataset, plus the
-- per-team opt-in. Images live in the training bucket (vpt-training); this table
-- owns dedup, split and labels. Nothing writes here unless TRAINING_DATA_ENABLED
-- is set AND the team has training_data_opt_in = true.
--
--   * teams.training_data_opt_in   — per-team consent, default off
--   * ai_training_samples          — one row per stored frame (TASK-27 §4)
--   * ai_training_samples_frozen_guard — refuses ground_truth / split changes
--     on rows frozen into an eval release (eval_version IS NOT NULL)
--
-- RLS: same posture as the most recent team-scoped table
-- (20260914_executable_identity): service_role only, anon/authenticated revoked.
--
-- Idempotent: safe to re-run. Inverse: 20260927a_ai_training_samples_rollback.sql.

BEGIN;

ALTER TABLE public.teams
    ADD COLUMN IF NOT EXISTS training_data_opt_in BOOLEAN NOT NULL DEFAULT false;

COMMENT ON COLUMN public.teams.training_data_opt_in IS
    'TASK-27: team consents to its frames entering the AI training dataset. Default off.';

CREATE TABLE IF NOT EXISTS public.ai_training_samples (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    team_id         UUID NOT NULL REFERENCES public.teams(id) ON DELETE CASCADE,
    family          TEXT NOT NULL,
    object_key      TEXT NOT NULL,
    dhash           TEXT NOT NULL,
    device_model    TEXT NOT NULL,
    userinterface   TEXT,
    node_id         TEXT,
    focus_label     TEXT,
    prompt          TEXT,
    model_answer    JSONB,
    ground_truth    JSONB,
    label_source    TEXT NOT NULL DEFAULT 'none',
    is_failure      BOOLEAN NOT NULL DEFAULT false,
    label_conflict  BOOLEAN NOT NULL DEFAULT false,
    split           TEXT NOT NULL,
    boxes           JSONB,
    source_ref      JSONB,
    eval_version    TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT ai_training_samples_family_check
        CHECK (family IN ('screen-id', 'focus', 'menu', 'banner', 'av-fault', 'content-type', 'other')),
    CONSTRAINT ai_training_samples_split_check
        CHECK (split IN ('train', 'eval', 'holdout')),
    CONSTRAINT ai_training_samples_label_source_check
        CHECK (label_source IN ('run', 'human', 'teacher', 'none')),
    CONSTRAINT ai_training_samples_dhash_hex
        CHECK (dhash ~ '^[0-9a-f]{64}$')
);

CREATE INDEX IF NOT EXISTS idx_ai_training_samples_group
    ON public.ai_training_samples(team_id, family, device_model, node_id, focus_label);
CREATE INDEX IF NOT EXISTS idx_ai_training_samples_split
    ON public.ai_training_samples(team_id, split);
CREATE INDEX IF NOT EXISTS idx_ai_training_samples_failure
    ON public.ai_training_samples(team_id, is_failure) WHERE is_failure;
CREATE INDEX IF NOT EXISTS idx_ai_training_samples_eval_version
    ON public.ai_training_samples(team_id, eval_version);

CREATE OR REPLACE FUNCTION public.ai_training_samples_frozen_guard()
RETURNS TRIGGER AS $$
BEGIN
    IF OLD.eval_version IS NOT NULL AND (
        NEW.ground_truth IS DISTINCT FROM OLD.ground_truth
        OR NEW.split IS DISTINCT FROM OLD.split
    ) THEN
        RAISE EXCEPTION 'ai_training_samples %: ground_truth and split are frozen (eval_version=%)',
            OLD.id, OLD.eval_version;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SET search_path = public, auth, extensions;

DROP TRIGGER IF EXISTS ai_training_samples_frozen_guard ON public.ai_training_samples;
CREATE TRIGGER ai_training_samples_frozen_guard
    BEFORE UPDATE ON public.ai_training_samples
    FOR EACH ROW EXECUTE FUNCTION public.ai_training_samples_frozen_guard();

COMMENT ON TABLE public.ai_training_samples IS
    'TASK-27 training-sample index. Image at object_key in the training bucket; split fixed at insert from stable keys + dhash[:4].';
COMMENT ON COLUMN public.ai_training_samples.source_ref IS
    'Pointer back to the origin: {"alert_id"}, {"script_result_id","step"}, {"zap_id"} or {"tree_id","node_id","edge_id"}.';

ALTER TABLE public.ai_training_samples ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "service_role_all_ai_training_samples" ON public.ai_training_samples;
CREATE POLICY "service_role_all_ai_training_samples" ON public.ai_training_samples
    FOR ALL TO service_role USING (true) WITH CHECK (true);
REVOKE ALL ON public.ai_training_samples FROM anon, authenticated;

COMMIT;
