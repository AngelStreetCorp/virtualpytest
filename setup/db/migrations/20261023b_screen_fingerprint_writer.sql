-- TASK-159 G7: the one place a FINGERPRINT is written onto a screen row.
--
-- A name goes through name_screen_row() (20261022e) and is written once: only a row whose label is
-- NULL or unknown_N can be (re)named, and a real name is never overwritten.  A fingerprint is the
-- same kind of fact about the same kind of row -- "this is the screen I saw" -- and it was missing
-- its own single writer: register_screen_row() wrote it on INSERT and nothing else could, so a row
-- registered before that existed kept fingerprint = NULL FOREVER, no matter how often the screen
-- was seen again.
--
-- Measured 2026-10-23: of the 31 screens the owner counts (seen more than 10 times, not live),
-- 21 had a real name and NO fingerprint.  That is the gap this function closes.
--
-- THE RULES, in the function itself so that no caller can break them:
--   * a fingerprint is written ONCE   -> only a row whose fingerprint IS NULL is touched
--   * a name is never touched          -> the label column is not in this statement at all
--   * a row is never deleted           -> this is an UPDATE
--   * a merged (soft-merged) row is skipped -> merged_into IS NULL
--   * the blob must carry a dhash      -> a blob without one is not a fingerprint
--
-- linked_node_id is set when the fingerprint came from a navigation tree node (the row is now known
-- to BE that node).  It is left alone when it is not (COALESCE), so a plain backfill never claims a
-- tree link it did not earn.
BEGIN;

CREATE FUNCTION public.link_screen_fingerprint(
    p_team_id uuid,
    p_id uuid,
    p_fingerprint jsonb,
    p_node_id text DEFAULT NULL
) RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE
    v_rows integer;
BEGIN
    UPDATE public.screen_fingerprints
       SET fingerprint = p_fingerprint,
           linked_node_id = COALESCE(p_node_id, linked_node_id),
           updated_at = now()
     WHERE id = p_id
       AND team_id = p_team_id
       AND merged_into IS NULL
       AND fingerprint IS NULL
       AND p_fingerprint IS NOT NULL
       AND p_fingerprint ? 'dhash';
    GET DIAGNOSTICS v_rows = ROW_COUNT;
    RETURN v_rows;
END;
$$;

REVOKE ALL ON FUNCTION public.link_screen_fingerprint(uuid, uuid, jsonb, text) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.link_screen_fingerprint(uuid, uuid, jsonb, text) TO service_role;

COMMENT ON FUNCTION public.link_screen_fingerprint(uuid, uuid, jsonb, text) IS
    'TASK-159 G7: write a fingerprint onto a screen row, once. Fills only a NULL fingerprint, never '
    'touches the label, never deletes. Returns the number of rows written (0 = refused).';

COMMIT;
