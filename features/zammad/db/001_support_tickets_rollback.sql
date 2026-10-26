-- features/zammad/db/001_support_tickets_rollback.sql — inverse of 001_support_tickets.sql: drops support_tickets (the index rows are lost; the
-- tickets themselves stay in the helpdesk). Not applied.

BEGIN;
DROP TABLE IF EXISTS public.support_tickets;
COMMIT;
