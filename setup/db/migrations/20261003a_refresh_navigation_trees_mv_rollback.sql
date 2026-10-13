-- 20261003a_refresh_navigation_trees_mv_rollback.sql — inverse of 20261003a_refresh_navigation_trees_mv.sql.
-- Points any pg_cron job that calls the function back at a plain concurrent refresh first,
-- so the once-a-minute refresh keeps running after the function is dropped.

DO $$
DECLARE
    j record;
BEGIN
    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_cron') THEN
        FOR j IN
            SELECT jobid FROM cron.job WHERE command ILIKE '%refresh_navigation_trees_mv%'
        LOOP
            PERFORM cron.alter_job(j.jobid,
                command := 'REFRESH MATERIALIZED VIEW CONCURRENTLY public.mv_full_navigation_trees');
        END LOOP;
    END IF;
END $$;

BEGIN;

DROP FUNCTION IF EXISTS public.refresh_navigation_trees_mv();

COMMIT;
