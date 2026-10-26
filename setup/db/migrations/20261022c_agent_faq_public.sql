-- 20261022c — Prepared FAQ: a public flag so the website "Ask AI" widget can read the same table as Atlas.
-- Additive only. Default FALSE: no existing entry becomes visible to anonymous visitors; only the
-- docs-only entries loaded by scripts/agent/faq_load_public.py are flipped to TRUE.
-- Same content as setup/db/schema/081_agent_faq_public.sql. Rollback: 20261022c_agent_faq_public_rollback.sql
BEGIN;

ALTER TABLE public.agent_faq ADD COLUMN IF NOT EXISTS public BOOLEAN NOT NULL DEFAULT FALSE;

CREATE INDEX IF NOT EXISTS agent_faq_public_live_idx
    ON public.agent_faq (count DESC) WHERE live AND public;

COMMENT ON COLUMN public.agent_faq.public IS
    'TRUE = safe to serve to anonymous website visitors (docs-only answer, no hosts, IPs, credentials or customer data). Read by POST /server/public/ask.';

COMMIT;
