-- 20261022e — Prepared FAQ: the count-bump RPC and the promoted-row CHECK (TASK-152 phase 9a/9b follow-up).
--
-- Two leftovers found on 2026-10-22 while reviewing the live FAQ table (342 rows, zero with
-- count > 1 — the hot cache's "top-N by count" ranking had therefore never been exercised).
--
-- 1. `increment_count()` called `atlas_faq_bump`, which was never created. Every FAQ hit fell
--    through to a postgrest fallback that only touched `updated_at`, so `count` never moved off
--    its initial value.
--
-- 2. `upsert_promoted()` upserted on `normalised_question`, so a persona-generated candidate that
--    collided with a curated seed overwrote `live=true, proposed=false` with
--    `live=false, proposed=true`, silently pulling a reviewed answer out of rotation. Row
--    1edc58d8 was caught in exactly that state. The code fix is in agent_faq_db.upsert_promoted
--    (read first, refuse when the row is already live); this CHECK makes the illegal shape
--    unrepresentable going forward.
--
-- Deliberately only two statements. The lane's additive check is a strict allowlist, so anything
-- it does not recognise refuses the whole file: BEGIN/COMMIT, COMMENT ON and REVOKE/GRANT are all
-- outside it, and none of them are needed here. Dropping the transaction wrapper means the two
-- statements autocommit independently — acceptable because each is independently re-runnable and
-- both are already applied to prod.
--
-- SECURITY INVOKER rather than DEFINER: the function is only ever reached from the service_role
-- client, which bypasses RLS on its own, so DEFINER bought nothing and forced a REVOKE/GRANT pair
-- to stop PUBLIC from calling it. Verified on prod that the invoker form returns the new count
-- (a throwaway atlas_faq_bump_invoker_test was created, checked and dropped).
--
-- Already applied to prod on 2026-10-22 and recorded in public.applied_migrations. Prod holds the
-- SECURITY DEFINER build from the first application; this file declares the invoker form, which is
-- strictly less privileged and behaves identically for service_role callers.
--
-- Idempotent. Same content as setup/db/schema/083_agent_faq_count_fn.sql.
-- Rollback: 20261022e_agent_faq_count_fn_rollback.sql

CREATE OR REPLACE FUNCTION public.atlas_faq_bump(p_faq_id UUID)
RETURNS INTEGER
LANGUAGE plpgsql
SET search_path = public
AS $fn$
DECLARE
    new_count BIGINT;
BEGIN
    UPDATE public.agent_faq
       SET count         = count + 1,
           last_asked_at = NOW(),
           updated_at    = NOW()
     WHERE id = p_faq_id AND live
    RETURNING count INTO new_count;

    IF new_count IS NULL THEN
        RETURN 0;                       -- unknown id, or the row is not live
    END IF;
    RETURN new_count::INTEGER;
END;
$fn$;

-- guarded so the file can be re-run (a second ADD CONSTRAINT would fail)
DO $guard$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'agent_faq_proposed_shape' AND conrelid = 'public.agent_faq'::regclass
    ) THEN
        ALTER TABLE public.agent_faq ADD CONSTRAINT agent_faq_proposed_shape CHECK (
            live = TRUE OR last_reviewed_at IS NULL
        );
    END IF;
END
$guard$;