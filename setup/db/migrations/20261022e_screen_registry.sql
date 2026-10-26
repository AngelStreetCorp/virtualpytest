-- 20261022e_screen_registry.sql
-- TASK-159: one registry of screens per device. ADDITIVE only (rollback: 20261022e_screen_registry_rollback.sql).
--   * screen_fingerprints.merged_into: soft merge (G7), a merged row points at the row that was kept
--   * screen_unknown_counters + register_screen_row(): atomic per-scope "unknown_N" naming and insert (G3)
--   * name_screen_row(): a name is written once; only NULL / unknown_N rows can be (re)named (G4)
--   * prune_rare_screens(): nightwatch prune that never deletes a row whose label is a real name (G4)
--   (the guarded noise prune, prune_unnamed_screen_noise(), is 20261022f_screen_prune_guard.sql)
BEGIN;

ALTER TABLE public.screen_fingerprints ADD COLUMN IF NOT EXISTS merged_into UUID;
CREATE INDEX IF NOT EXISTS idx_screen_fingerprints_merged_into
    ON public.screen_fingerprints (merged_into) WHERE merged_into IS NOT NULL;

CREATE TABLE IF NOT EXISTS public.screen_unknown_counters (
    team_id UUID NOT NULL,
    scope   TEXT NOT NULL,
    last_n  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (team_id, scope)
);
ALTER TABLE public.screen_unknown_counters ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "service_role_all_screen_unknown_counters" ON public.screen_unknown_counters;
CREATE POLICY "service_role_all_screen_unknown_counters" ON public.screen_unknown_counters
    FOR ALL TO service_role USING (true) WITH CHECK (true);
REVOKE ALL ON public.screen_unknown_counters FROM anon, authenticated;

-- The number and the row come from one statement block: the counter row lock serialises two creators of one scope.
CREATE OR REPLACE FUNCTION public.register_screen_row(
    p_team_id uuid, p_scope text, p_dhash text, p_region_center text,
    p_fingerprint jsonb DEFAULT NULL, p_userinterface text DEFAULT NULL,
    p_sample text DEFAULT NULL
) RETURNS TABLE(id uuid, label text, seen_count integer)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE
    v_n integer;
BEGIN
    INSERT INTO public.screen_unknown_counters AS c (team_id, scope, last_n)
    VALUES (p_team_id, p_scope, 1)
    ON CONFLICT (team_id, scope) DO UPDATE SET last_n = c.last_n + 1
    RETURNING c.last_n INTO v_n;

    RETURN QUERY
    INSERT INTO public.screen_fingerprints AS s
        (team_id, scope, incident_type, dhash, region_center, fingerprint, userinterface, label,
         verdict, source, seen_count, sample_image_path)
    VALUES (p_team_id, p_scope, 'screen', p_dhash, COALESCE(p_region_center, ''), p_fingerprint, p_userinterface,
            'unknown_' || v_n, 'unknown', 'none', 1, p_sample)
    RETURNING s.id, s.label, s.seen_count;
END;
$$;

CREATE OR REPLACE FUNCTION public.name_screen_row(p_team_id uuid, p_id uuid, p_label text)
RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE
    v_rows integer;
BEGIN
    UPDATE public.screen_fingerprints
       SET label = p_label, verdict_by = 'auto_classify', updated_at = now()
     WHERE id = p_id AND team_id = p_team_id
       AND merged_into IS NULL
       AND (label IS NULL OR label ~ '^unknown_[0-9]+$');
    GET DIAGNOSTICS v_rows = ROW_COUNT;
    RETURN v_rows;
END;
$$;

CREATE OR REPLACE FUNCTION public.prune_rare_screens(
    p_team_id uuid, p_incident_type text, p_min_seen integer, p_cutoff timestamptz
) RETURNS integer
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public, pg_temp AS $$
DECLARE
    v_rows integer;
BEGIN
    DELETE FROM public.screen_fingerprints
     WHERE team_id = p_team_id AND incident_type = p_incident_type
       AND verdict = 'unknown' AND source <> 'human'
       AND (label IS NULL OR label ~ '^unknown_[0-9]+$')
       AND seen_count < p_min_seen AND last_seen < p_cutoff;
    GET DIAGNOSTICS v_rows = ROW_COUNT;
    RETURN v_rows;
END;
$$;

REVOKE ALL ON FUNCTION public.register_screen_row(uuid, text, text, text, jsonb, text, text) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.name_screen_row(uuid, uuid, text) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.prune_rare_screens(uuid, text, integer, timestamptz) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.register_screen_row(uuid, text, text, text, jsonb, text, text) TO service_role;
GRANT EXECUTE ON FUNCTION public.name_screen_row(uuid, uuid, text) TO service_role;
GRANT EXECUTE ON FUNCTION public.prune_rare_screens(uuid, text, integer, timestamptz) TO service_role;

COMMIT;
