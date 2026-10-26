-- 20261016d_ai_budgets_finer_buckets.sql
-- BUG-0559 / TASK-87 phase 5 — AI budget per team is no longer the only granularity.
--   ai_budgets becomes (bucket_type, bucket_id) ↔ row, where bucket_type ∈ {team, user, model, endpoint, usage, project}.
--   team_scope (FK to teams.id) carries the tenant-defending team FK regardless of bucket type (TASK-83 path).
--   The resolver walks the specificity ladder (usage > model > endpoint > user > project > team);
--   the most-specific bucket that applies wins the block decision; warn buckets still report.
-- ai_calls gains project_id so per-project spend can be computed from the 90-day per-call log.
-- Backfill: existing team rows migrate to (bucket_type='team', bucket_id=team_id, team_scope=team_id) — value preserved.
-- RLS unchanged (service_role only). Idempotent. Canonical twin: setup/db/schema/066_ai_budgets_finer_buckets.sql.
-- Inverse: 20261016d_ai_budgets_finer_buckets_rollback.sql.

BEGIN;

-- ---------------------------------------------------------------- ai_budgets shape
ALTER TABLE public.ai_budgets
    ADD COLUMN IF NOT EXISTS bucket_type TEXT NOT NULL DEFAULT 'team'
        CHECK (bucket_type IN ('team', 'user', 'model', 'endpoint', 'usage', 'project')),
    ADD COLUMN IF NOT EXISTS bucket_id   TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS team_scope  UUID NULL REFERENCES public.teams(id) ON DELETE CASCADE,
    ADD COLUMN IF NOT EXISTS label       TEXT NULL;

-- Backfill existing rows. bucket_id = team_id, team_scope = team_id.
UPDATE public.ai_budgets
   SET bucket_id = team_id::text,
       team_scope = team_id
 WHERE bucket_id = '' OR bucket_id IS NULL;

-- New composite PK.
ALTER TABLE public.ai_budgets DROP CONSTRAINT IF EXISTS ai_budgets_pkey;
ALTER TABLE public.ai_budgets ADD PRIMARY KEY (bucket_type, bucket_id);

CREATE INDEX IF NOT EXISTS ai_budgets_team_scope_idx ON public.ai_budgets (team_scope);

COMMENT ON TABLE  public.ai_budgets IS
    'BUG-0559 / TASK-87 phase 5: AI budget per bucket. bucket_type ∈ {team, user, model, endpoint, usage, project}. team_scope is the tenant-defending team FK (always set). The most-specific bucket that applies to a call wins the block decision; warn buckets report. Spend comes from ai_usage_stats for team buckets, from ai_calls (90-day per-call log) for finer buckets.';
COMMENT ON COLUMN public.ai_budgets.bucket_type IS 'team | user | model | endpoint | usage | project. Most-specific bucket wins per call.';
COMMENT ON COLUMN public.ai_budgets.bucket_id   IS 'Discriminator — team_id UUID for team buckets, auth.users UUID for user, model name for model, endpoint name for endpoint, usage_key for usage, project UUID for project.';
COMMENT ON COLUMN public.ai_budgets.team_scope  IS 'Tenant-defending team FK. Always set. A finer bucket still owes its tenant scope to the team the spend belongs to.';
COMMENT ON COLUMN public.ai_budgets.label      IS 'Optional display label (e.g. "Anthropic Claude Opus 4.6", "Atelier model A"). Free for installers.';

-- ---------------------------------------------------------------- ai_calls.project_id
-- Per-call log gains project_id so per-project spend is computable. Cheap on the 90-day table.
ALTER TABLE public.ai_calls
    ADD COLUMN IF NOT EXISTS project_id TEXT NULL;

CREATE INDEX IF NOT EXISTS ai_calls_project_ts_idx ON public.ai_calls (project_id, ts);
CREATE INDEX IF NOT EXISTS ai_calls_team_user_ts_idx ON public.ai_calls (team_id, user_id, ts);

COMMENT ON COLUMN public.ai_calls.project_id IS 'X-Project-Id header on the originating request, or localStorage virtualpytest:project_id when the call is browser-initiated. NULL when no project is active (most calls).';
COMMENT ON COLUMN public.ai_calls.user_id     IS 'Supabase auth.users UUID of the caller (NULL for monitoring / background / public Ask).';

COMMIT;