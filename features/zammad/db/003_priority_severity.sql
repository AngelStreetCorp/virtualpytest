-- features/zammad/db/003_priority_severity.sql
-- TASK-96: the reporter sets the priority (P0 High, P1 Medium, P2 Low), required on every type, default P1;
-- severity loses 'cosmetic' (blocker | major | minor). Applies on top of 002.
-- Rows are mapped before the constraints tighten: priority NULL -> P1, P1 -> P0, P2 -> P1, P3/P4 -> P2
-- (a single UPDATE, so the old P1 is not remapped twice); severity cosmetic -> minor.
-- Idempotent: a second run finds only P0..P2 and changes nothing. Inverse: 003_priority_severity_rollback.sql.

BEGIN;

ALTER TABLE public.support_tickets DROP CONSTRAINT IF EXISTS support_tickets_priority_check;
ALTER TABLE public.support_tickets DROP CONSTRAINT IF EXISTS support_tickets_severity_check;

-- only rows still on the old scale (they hold P3/P4 or were never triaged) are remapped; once any P0 exists
-- the table is already on the new scale, so a re-run must not shift P1 -> P0 again.
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM public.support_tickets WHERE priority = 'P0')
       AND NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'support_tickets_priority_p0_p2') THEN
        UPDATE public.support_tickets SET priority = CASE priority
            WHEN 'P1' THEN 'P0' WHEN 'P2' THEN 'P1' WHEN 'P3' THEN 'P2' WHEN 'P4' THEN 'P2' ELSE priority END
        WHERE priority IN ('P1', 'P2', 'P3', 'P4');
    END IF;
END $$;
UPDATE public.support_tickets SET priority = 'P1' WHERE priority IS NULL;
UPDATE public.support_tickets SET severity = 'minor' WHERE severity = 'cosmetic';

ALTER TABLE public.support_tickets ALTER COLUMN priority SET DEFAULT 'P1';
ALTER TABLE public.support_tickets ALTER COLUMN priority SET NOT NULL;

ALTER TABLE public.support_tickets DROP CONSTRAINT IF EXISTS support_tickets_priority_p0_p2;
ALTER TABLE public.support_tickets ADD CONSTRAINT support_tickets_priority_p0_p2
    CHECK (priority IN ('P0', 'P1', 'P2'));
ALTER TABLE public.support_tickets DROP CONSTRAINT IF EXISTS support_tickets_severity_blocker_major_minor;
ALTER TABLE public.support_tickets ADD CONSTRAINT support_tickets_severity_blocker_major_minor
    CHECK (severity IN ('blocker', 'major', 'minor'));

COMMIT;
