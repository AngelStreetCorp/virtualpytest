-- Rollback of 20261022c_agent_faq_public.sql. Drops the flag; entries stay, the website widget falls back to the model.
BEGIN;
DROP INDEX IF EXISTS public.agent_faq_public_live_idx;
ALTER TABLE public.agent_faq DROP COLUMN IF EXISTS public;
COMMIT;
