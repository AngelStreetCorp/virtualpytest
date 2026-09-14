-- Linkage between the AI-learned UI knowledge base and the production
-- userinterfaces table.
--
-- Problem: ai_userinterfaces (agent-written KB) and userinterfaces (human-curated
-- navigation trees) share nothing — by design. But once an agent has resolved a
-- device's fingerprint to an ai_userinterfaces row, it often needs to hand off to
-- production tree tooling (navigate_to_node, get_userinterface_complete), and today
-- there is no way to know WHICH production userinterface corresponds to the
-- resolved KB entry. Agents guess by name, which is exactly the misrouting the
-- disambiguation section of docs/agent/navigation/AI_USERINTERFACE.md warns about.
--
-- This migration adds an optional soft link:
--   ai_userinterfaces.userinterface_id uuid NULL  -> userinterfaces.id
--
-- Deliberately NO foreign key constraint:
--   * The two tables have independent lifecycles — production UIs are freely
--     deleted/recreated by humans in the tree editor, and the KB must never
--     block that (nor be cascaded away by it).
--   * The KB is portable across installs where the production table may not
--     contain the referenced row at all.
--   Application code treats a dangling value as "link stale, ignore".
--
-- Also folded into setup/db/schema/033_ai_userinterface.sql so a fresh install
-- gets it (per docs/agent/infra/DATABASE.md convention).
--
-- Idempotent: safe to re-run. Apply per docs/agent/infra/DATABASE.md, then
-- reload the PostgREST schema cache.

BEGIN;

ALTER TABLE public.ai_userinterfaces
    ADD COLUMN IF NOT EXISTS userinterface_id uuid;

CREATE INDEX IF NOT EXISTS idx_ai_userinterfaces_prod_ui
    ON public.ai_userinterfaces(userinterface_id)
    WHERE userinterface_id IS NOT NULL;

COMMENT ON COLUMN public.ai_userinterfaces.userinterface_id IS
'Soft link to the production userinterfaces.id modelling the same UI. No FK by
 design (independent lifecycles); dangling values are ignored by application code.';

COMMIT;
