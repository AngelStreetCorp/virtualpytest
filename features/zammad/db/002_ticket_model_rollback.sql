-- features/zammad/db/002_ticket_model_rollback.sql - inverse of 002_ticket_model.sql: back to the first cut
-- (category / entity_type / entity_id, status open | pending | closed). Existing rows keep their title and
-- helpdesk link; their category becomes 'platform' and the entity is lost. Not applied.

BEGIN;

ALTER TABLE public.support_tickets DROP CONSTRAINT IF EXISTS support_tickets_severity_by_type;
ALTER TABLE public.support_tickets DROP CONSTRAINT IF EXISTS support_tickets_status_check;
UPDATE public.support_tickets SET status = 'closed' WHERE status IN ('closed', 'duplicate', 'wont_fix');
UPDATE public.support_tickets SET status = 'pending' WHERE status = 'need_info';
UPDATE public.support_tickets SET status = 'open' WHERE status NOT IN ('closed', 'pending');

DROP INDEX IF EXISTS public.idx_support_tickets_team_type;
DROP INDEX IF EXISTS public.idx_support_tickets_team_family_category;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns
               WHERE table_schema = 'public' AND table_name = 'support_tickets' AND column_name = 'ticket_type') THEN
        ALTER TABLE public.support_tickets
            DROP COLUMN ticket_type, DROP COLUMN family, DROP COLUMN category, DROP COLUMN target_id,
            DROP COLUMN target_label, DROP COLUMN severity, DROP COLUMN frequency, DROP COLUMN priority,
            DROP COLUMN fixed_in_build;
    END IF;
END $$;

ALTER TABLE public.support_tickets
    ADD COLUMN IF NOT EXISTS category    TEXT NOT NULL DEFAULT 'platform'
        CHECK (category IN ('device', 'host', 'system', 'script', 'dashboard', 'platform')),
    ADD COLUMN IF NOT EXISTS entity_type TEXT,
    ADD COLUMN IF NOT EXISTS entity_id   TEXT;
ALTER TABLE public.support_tickets ALTER COLUMN category DROP DEFAULT;

ALTER TABLE public.support_tickets ADD CONSTRAINT support_tickets_status_check
    CHECK (status IN ('open', 'pending', 'closed'));
ALTER TABLE public.support_tickets ALTER COLUMN status SET DEFAULT 'open';

CREATE INDEX IF NOT EXISTS idx_support_tickets_team_entity ON public.support_tickets (team_id, entity_type, entity_id);

COMMENT ON TABLE public.support_tickets IS
    'TASK-96: index of support tickets per team. The conversation lives in the helpdesk (external_provider/external_id); status mirrors it (open | pending | closed).';

COMMIT;
