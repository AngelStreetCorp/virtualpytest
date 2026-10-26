-- 066 — AI budgets finer buckets (BUG-0559, TASK-87 phase 5).
-- Idempotent. Same content as migration 20261016d_ai_budgets_finer_buckets.sql.
-- Apply BEFORE the deploy that switches the resolver to the multi-bucket path.

BEGIN;

ALTER TABLE public.ai_budgets
    ADD COLUMN IF NOT EXISTS bucket_type TEXT NOT NULL DEFAULT 'team'
        CHECK (bucket_type IN ('team', 'user', 'model', 'endpoint', 'usage', 'project')),
    ADD COLUMN IF NOT EXISTS bucket_id   TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS team_scope  UUID NULL REFERENCES public.teams(id) ON DELETE CASCADE,
    ADD COLUMN IF NOT EXISTS label       TEXT NULL;

UPDATE public.ai_budgets
   SET bucket_id = team_id::text,
       team_scope = team_id
 WHERE bucket_id = '' OR bucket_id IS NULL;

ALTER TABLE public.ai_budgets DROP CONSTRAINT IF EXISTS ai_budgets_pkey;
ALTER TABLE public.ai_budgets ADD PRIMARY KEY (bucket_type, bucket_id);

CREATE INDEX IF NOT EXISTS ai_budgets_team_scope_idx ON public.ai_budgets (team_scope);

ALTER TABLE public.ai_calls
    ADD COLUMN IF NOT EXISTS project_id TEXT NULL;

CREATE INDEX IF NOT EXISTS ai_calls_project_ts_idx ON public.ai_calls (project_id, ts);
CREATE INDEX IF NOT EXISTS ai_calls_team_user_ts_idx ON public.ai_calls (team_id, user_id, ts);

COMMIT;