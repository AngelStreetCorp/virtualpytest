-- 059_refresh_navigation_trees_mv.sql
-- On-demand refresh of mv_full_navigation_trees.
--
-- Hosts build their navigation graph from mv_full_navigation_trees. On the live databases
-- the per-statement refresh triggers (002) are disabled — a full refresh per statement
-- made batched writes die with statement timeouts — and pg_cron refreshes the view once a
-- minute instead. So a tree written through REST/MCP was invisible to the hosts for up to
-- ~90 s (cron interval + host cache), and every builder waited that long after each write.
--
-- refresh_navigation_trees_mv() lets the server refresh right after a write
-- (POST /server/navigationTrees/<tree_id>/refresh). It takes a transaction-scoped advisory
-- lock so concurrent callers queue instead of piling up refreshes, and the pg_cron job (if
-- one refreshes this view) is re-pointed at the same function so it queues behind the same
-- lock. Returns the time the refresh finished.
--
-- SECURITY DEFINER: REFRESH requires ownership of the view; the function runs as its
-- owner (the migration role). EXECUTE: service_role only.
-- Idempotent. Migration twin: setup/db/migrations/20261003a_refresh_navigation_trees_mv.sql.

BEGIN;

CREATE OR REPLACE FUNCTION public.refresh_navigation_trees_mv()
RETURNS timestamptz
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO public, pg_temp
AS $$
BEGIN
    -- One refresh at a time; a caller that waited still refreshes, because its own
    -- write may postdate the snapshot the previous refresh read.
    PERFORM pg_advisory_xact_lock(hashtext('public.refresh_navigation_trees_mv'));
    REFRESH MATERIALIZED VIEW CONCURRENTLY public.mv_full_navigation_trees;
    RETURN clock_timestamp();
END;
$$;

COMMENT ON FUNCTION public.refresh_navigation_trees_mv() IS
'Refresh mv_full_navigation_trees now (CONCURRENTLY, serialized by an advisory lock shared with the pg_cron job). Called by POST /server/navigationTrees/<tree_id>/refresh after a tree write.';

REVOKE ALL ON FUNCTION public.refresh_navigation_trees_mv() FROM PUBLIC;
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        REVOKE ALL ON FUNCTION public.refresh_navigation_trees_mv() FROM anon;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated') THEN
        REVOKE ALL ON FUNCTION public.refresh_navigation_trees_mv() FROM authenticated;
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        GRANT EXECUTE ON FUNCTION public.refresh_navigation_trees_mv() TO service_role;
    END IF;
END $$;

COMMIT;

-- Re-point the once-a-minute pg_cron refresh at the function so it shares the lock.
-- Outside the transaction: cron.alter_job commits its own. Only touches a job whose
-- command refreshes this view directly; reports what it changed.
DO $$
DECLARE
    j record;
BEGIN
    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_cron') THEN
        FOR j IN
            SELECT jobid, jobname, command FROM cron.job
            WHERE command ILIKE '%REFRESH MATERIALIZED VIEW%mv_full_navigation_trees%'
        LOOP
            PERFORM cron.alter_job(j.jobid, command := 'SELECT public.refresh_navigation_trees_mv()');
            RAISE NOTICE 'pg_cron job % (%) now runs refresh_navigation_trees_mv() (was: %)',
                j.jobid, j.jobname, j.command;
        END LOOP;
    END IF;
END $$;
