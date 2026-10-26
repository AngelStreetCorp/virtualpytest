-- 20261016c_prune_screen_fingerprints_fn.sql
-- The retention DELETE that keeps screen_fingerprints bounded on the
-- "big counter" rule the operator asked for.
--
-- WHY A FUNCTION AND NOT A PLAIN DELETE
--   supabase-py's chainable filter builder cannot express a NOT-IN
--   subquery with ORDER BY + LIMIT.  The auto-classify scheduler calls
--   this function via RPC instead of trying to express the predicate
--   client-side.  The function is SECURITY DEFINER so it can DELETE
--   even though the caller's role has no DELETE policy; this is the
--   same pattern the rest of the admin scripts use.
--
-- WHY THESE PARAMETERS
--   p_min_hits      : a row must have been seen at least this often
--                     before it is even a candidate for deletion.  The
--                     "big counter" rule — a row with hits < this has
--                     not earned its keep.
--   p_max_age_days  : and the row must be at least this old.  A row
--                     that just landed is not noise yet.
--   p_floor         : NEVER delete below this many rows.  Even if the
--                     parameters are wrong, the operator always has
--                     something to look at.  The default is 500.
--
-- The function takes p_team_id and only deletes rows belonging to that
-- team — it cannot accidentally wipe another team's noise.  The caller
-- (the auto-classify scheduler) passes the team_id from --team-id.

BEGIN;

CREATE OR REPLACE FUNCTION public.prune_screen_fingerprints_noise(
    p_team_id      uuid,
    p_min_hits     integer DEFAULT 3,
    p_max_age_days integer DEFAULT 14,
    p_floor        integer DEFAULT 500
)
RETURNS TABLE(deleted_count bigint)
LANGUAGE plpgsql
SECURITY DEFINER
AS $$
DECLARE
    v_deleted bigint;
BEGIN
    WITH top_floor AS (
        SELECT id
        FROM public.screen_fingerprints
        WHERE team_id = p_team_id
          AND verdict = 'unknown'
        ORDER BY seen_count DESC
        LIMIT p_floor
    ),
    deleted AS (
        DELETE FROM public.screen_fingerprints
        WHERE team_id = p_team_id
          AND verdict = 'unknown'
          AND seen_count < p_min_hits
          AND last_seen < now() - (p_max_age_days || ' days')::interval
          AND id NOT IN (SELECT id FROM top_floor)
        RETURNING id
    )
    SELECT count(*) INTO v_deleted FROM deleted;

    RETURN QUERY SELECT v_deleted;
END;
$$;

-- Locked down: only the service_role can run it.  anon and authenticated
-- have no business pruning another team's fingerprints.
REVOKE ALL ON FUNCTION public.prune_screen_fingerprints_noise(uuid, integer, integer, integer) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.prune_screen_fingerprints_noise(uuid, integer, integer, integer) TO service_role;

COMMIT;
