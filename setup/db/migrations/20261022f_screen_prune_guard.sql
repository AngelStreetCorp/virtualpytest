-- 20261022f_screen_prune_guard.sql
-- TASK-159 G4: the retention prune that never deletes a row whose label is a real name (only NULL or unknown_N rows are
-- noise). A NEW function (the 20261016c prune_screen_fingerprints_noise is left as it is and no longer called):
-- auto_classify_unknowns.py calls this one. Same parameters and grants. Rollback: _rollback.sql.
BEGIN;

CREATE FUNCTION public.prune_unnamed_screen_noise(
    p_team_id      uuid,
    p_min_hits     integer DEFAULT 3,
    p_max_age_days integer DEFAULT 14,
    p_floor        integer DEFAULT 500
)
RETURNS TABLE(deleted_count bigint)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE
    v_deleted bigint;
BEGIN
    WITH top_floor AS (
        SELECT s.id FROM public.screen_fingerprints s
        WHERE s.team_id = p_team_id AND s.verdict = 'unknown'
        ORDER BY s.seen_count DESC LIMIT p_floor
    ),
    deleted AS (
        DELETE FROM public.screen_fingerprints d
        WHERE d.team_id = p_team_id
          AND d.verdict = 'unknown'
          AND (d.label IS NULL OR d.label ~ '^unknown_[0-9]+$')
          AND d.seen_count < p_min_hits
          AND d.last_seen < now() - (p_max_age_days || ' days')::interval
          AND d.id NOT IN (SELECT t.id FROM top_floor t)
        RETURNING d.id
    )
    SELECT count(*) INTO v_deleted FROM deleted;
    RETURN QUERY SELECT v_deleted;
END;
$$;

REVOKE ALL ON FUNCTION public.prune_unnamed_screen_noise(uuid, integer, integer, integer) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.prune_unnamed_screen_noise(uuid, integer, integer, integer) TO service_role;

COMMIT;
