-- features/zammad/db/003_priority_severity_rollback.sql - inverse of 003: back to the 002 shape (priority
-- P1..P4 set by support, NULL until triage; severity with 'cosmetic'). Priorities map P0 -> P1, P1 -> P2,
-- P2 -> P3 (the original scale had no way to tell them apart). Not applied.

BEGIN;

ALTER TABLE public.support_tickets DROP CONSTRAINT IF EXISTS support_tickets_priority_p0_p2;
ALTER TABLE public.support_tickets DROP CONSTRAINT IF EXISTS support_tickets_severity_blocker_major_minor;
ALTER TABLE public.support_tickets ALTER COLUMN priority DROP NOT NULL;
ALTER TABLE public.support_tickets ALTER COLUMN priority DROP DEFAULT;

UPDATE public.support_tickets SET priority = CASE priority
    WHEN 'P0' THEN 'P1' WHEN 'P1' THEN 'P2' WHEN 'P2' THEN 'P3' ELSE priority END;

ALTER TABLE public.support_tickets ADD CONSTRAINT support_tickets_priority_check
    CHECK (priority IN ('P1', 'P2', 'P3', 'P4'));
ALTER TABLE public.support_tickets ADD CONSTRAINT support_tickets_severity_check
    CHECK (severity IN ('blocker', 'major', 'minor', 'cosmetic'));

COMMIT;
