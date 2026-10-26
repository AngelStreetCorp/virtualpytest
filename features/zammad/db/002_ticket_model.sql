-- features/zammad/db/002_ticket_model.sql
-- TASK-96 "Ticket model and workflow" (owner approved 2026-10-14). Replaces the first cut (category /
-- entity_type / entity_id, status open | pending | closed) with the Type x Family x Category x Target model
-- and the workflow statuses. Applied on the lab DB (node1) 2026-10-14; customer DBs with their next deploy, after 001.
--   ticket_type  incident | bug | request | question
--   family       platform | scripting | monitoring | dashboards | ai
--   category     server, host, device, service | script, campaign, virtual_script, testcase | heatmap, timeline,
--                incident | grafana, report | agent   (the family decides which are valid)
--   target_id / target_label   the thing the ticket is about (optional)
--   severity     blocker | major | minor | cosmetic, NULL for request and question
--   frequency    always | frequent | random | once
--   priority     P1..P4, set by support at triage (NULL until then)
--   fixed_in_build  build that carries the fix, set by support (NULL until then)
-- The table was empty when this was written, so the old columns are dropped, not migrated; the script
-- refuses to run on a table that already holds rows. Idempotent: a second run changes nothing.
-- Inverse: 002_ticket_model_rollback.sql.

BEGIN;

DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns
               WHERE table_schema = 'public' AND table_name = 'support_tickets' AND column_name = 'entity_type') THEN
        IF EXISTS (SELECT 1 FROM public.support_tickets) THEN
            RAISE EXCEPTION 'support_tickets already holds rows with the old model; migrate them by hand first';
        END IF;
        -- drops the old category CHECK and idx_support_tickets_team_entity with them
        ALTER TABLE public.support_tickets DROP COLUMN category, DROP COLUMN entity_type, DROP COLUMN entity_id;
    END IF;
END $$;

ALTER TABLE public.support_tickets
    ADD COLUMN IF NOT EXISTS ticket_type    TEXT NOT NULL
        CHECK (ticket_type IN ('incident', 'bug', 'request', 'question')),
    ADD COLUMN IF NOT EXISTS family         TEXT NOT NULL
        CHECK (family IN ('platform', 'scripting', 'monitoring', 'dashboards', 'ai')),
    ADD COLUMN IF NOT EXISTS category       TEXT NOT NULL
        CHECK (category IN ('server', 'host', 'device', 'service', 'script', 'campaign', 'virtual_script',
                            'testcase', 'heatmap', 'timeline', 'incident', 'grafana', 'report', 'agent')),
    ADD COLUMN IF NOT EXISTS target_id      TEXT,
    ADD COLUMN IF NOT EXISTS target_label   TEXT,
    ADD COLUMN IF NOT EXISTS severity       TEXT
        CHECK (severity IN ('blocker', 'major', 'minor', 'cosmetic')),
    ADD COLUMN IF NOT EXISTS frequency      TEXT NOT NULL
        CHECK (frequency IN ('always', 'frequent', 'random', 'once')),
    ADD COLUMN IF NOT EXISTS priority       TEXT
        CHECK (priority IN ('P1', 'P2', 'P3', 'P4')),
    ADD COLUMN IF NOT EXISTS fixed_in_build TEXT;

-- severity belongs to incident and bug only
ALTER TABLE public.support_tickets DROP CONSTRAINT IF EXISTS support_tickets_severity_by_type;
ALTER TABLE public.support_tickets ADD CONSTRAINT support_tickets_severity_by_type
    CHECK ((ticket_type IN ('incident', 'bug') AND severity IS NOT NULL) OR
           (ticket_type IN ('request', 'question') AND severity IS NULL));

-- workflow statuses (rows of the old model, if any survived, map onto them first)
ALTER TABLE public.support_tickets DROP CONSTRAINT IF EXISTS support_tickets_status_check;
UPDATE public.support_tickets SET status = 'new' WHERE status = 'open';
UPDATE public.support_tickets SET status = 'need_info' WHERE status = 'pending';
ALTER TABLE public.support_tickets ADD CONSTRAINT support_tickets_status_check
    CHECK (status IN ('new', 'accepted', 'assigned', 'in_progress', 'need_info', 'fixed', 'delivered',
                      'reopened', 'closed', 'duplicate', 'wont_fix'));
ALTER TABLE public.support_tickets ALTER COLUMN status SET DEFAULT 'new';

CREATE INDEX IF NOT EXISTS idx_support_tickets_team_type ON public.support_tickets (team_id, ticket_type);
CREATE INDEX IF NOT EXISTS idx_support_tickets_team_family_category ON public.support_tickets (team_id, family, category);

COMMENT ON TABLE public.support_tickets IS
    'TASK-96: index of support tickets per team. The conversation lives in the helpdesk (external_provider/external_id); status mirrors its workflow (new, accepted, assigned, in_progress, need_info, fixed, delivered, reopened, closed, duplicate, wont_fix).';

COMMIT;
