-- Inverse of 20261014a_applied_migrations.sql (drops the history).
BEGIN;
DROP TABLE IF EXISTS public.applied_migrations;
COMMIT;
