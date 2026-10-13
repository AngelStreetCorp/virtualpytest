-- 20260928d_verification_timeout_web_video_to_ms.sql
--
-- Every verification `params.timeout` is now MILLISECONDS, for every verification
-- type. Until this change `web` (Playwright: waitForElementToAppear /
-- waitForElementToDisappear / waitForTitleToAppear) and `video` (WaitForVideoTo*,
-- WaitForVideoChange, VerifyScreenState) read the same field as SECONDS while
-- image / text / adb / appium read it as ms, and the editor labelled all of them
-- "Timeout (ms)". The controllers now convert ms -> s at the params boundary for
-- web and video too (code change shipped with this migration), so the values
-- already stored for those two types have to be multiplied by 1000 or a 15 s
-- wait would run as 15 ms.
--
-- WHAT IT UPDATES  (only objects with verification_type IN ('web','video') and a
-- numeric params.timeout; timeout 0 stays 0)
--   navigation_nodes.verifications                       node verifications
--   navigation_edges.action_sets[].kpi_references        edge KPI references
--   userinterface_variants.node_overrides                variant node verifications
--   userinterface_variants.edge_overrides                variant action_sets / kpi_references
--   testcase_definitions.graph_json                      test case verification blocks
-- A table that does not exist on a database (e.g. userinterface_variants on an
-- install that never received that migration) is skipped and counted 0.
-- A recursive helper walks each jsonb value, so every nesting shape above is
-- covered by one rule. Rows that would not change are not touched (no trigger
-- noise, read-only nodes are never rewritten). testcase_definitions keeps the
-- pre-change graph in testcase_definitions_history via its own trigger.
--
-- NOT TOUCHED: image / text / adb / appium timeouts (already ms). Values that are
-- suspiciously small there (5, 15 ...) were probably written as seconds; they are
-- a data question, not a unit change — see the query in the change description.
--
-- ONE-SHOT, GUARDED: multiplying twice would turn 15 s into 15 000 000 ms, so the
-- run is recorded in public.data_migrations and skipped on a second execution.
-- It is not reversible by re-running; to undo, divide the same objects by 1000.
--
-- DEPLOY ORDER: apply together with the code release. Old code + migrated data
-- (or new code + unmigrated data) makes web/video waits 1000x too short/long.
-- Cached unified graphs (Redis / mv_full_navigation_trees) are refreshed at the
-- end; restart the servers or clear the graph cache if a host still serves old
-- verifications.

BEGIN;

CREATE TABLE IF NOT EXISTS public.data_migrations (
    name text PRIMARY KEY,
    applied_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE public.data_migrations ENABLE ROW LEVEL SECURITY;  -- service role only

-- Recursively multiplies params.timeout by 1000 on every verification-shaped
-- object of type web or video. Returns the input unchanged everywhere else.
CREATE OR REPLACE FUNCTION pg_temp.vt_web_video_to_ms(j jsonb) RETURNS jsonb
LANGUAGE plpgsql AS $$
DECLARE
    result jsonb;
BEGIN
    IF j IS NULL THEN
        RETURN NULL;
    END IF;

    IF jsonb_typeof(j) = 'array' THEN
        SELECT COALESCE(jsonb_agg(pg_temp.vt_web_video_to_ms(e.value) ORDER BY e.ord), '[]'::jsonb)
          INTO result
          FROM jsonb_array_elements(j) WITH ORDINALITY AS e(value, ord);
        RETURN result;
    END IF;

    IF jsonb_typeof(j) <> 'object' THEN
        RETURN j;
    END IF;

    SELECT COALESCE(jsonb_object_agg(k.key, pg_temp.vt_web_video_to_ms(k.value)), '{}'::jsonb)
      INTO result
      FROM jsonb_each(j) AS k(key, value);

    IF result->>'verification_type' IN ('web', 'video')
       AND jsonb_typeof(result->'params') = 'object'
       AND jsonb_typeof(result->'params'->'timeout') = 'number' THEN
        result := jsonb_set(
            result,
            '{params,timeout}',
            to_jsonb(round((result->'params'->>'timeout')::numeric * 1000)::bigint)
        );
    END IF;

    RETURN result;
END;
$$;

DO $$
DECLARE
    n_nodes integer;
    n_edges integer;
    n_variants integer;
    n_testcases integer;
BEGIN
    IF EXISTS (SELECT 1 FROM public.data_migrations
               WHERE name = '20260928d_verification_timeout_web_video_to_ms') THEN
        RAISE NOTICE '20260928d already applied - skipping (would double-multiply)';
        RETURN;
    END IF;

    n_nodes := 0;
    IF to_regclass('public.navigation_nodes') IS NOT NULL THEN
        UPDATE public.navigation_nodes
           SET verifications = pg_temp.vt_web_video_to_ms(verifications)
         WHERE verifications IS DISTINCT FROM pg_temp.vt_web_video_to_ms(verifications);
        GET DIAGNOSTICS n_nodes = ROW_COUNT;
    END IF;

    n_edges := 0;
    IF to_regclass('public.navigation_edges') IS NOT NULL THEN
        UPDATE public.navigation_edges
           SET action_sets = pg_temp.vt_web_video_to_ms(action_sets)
         WHERE action_sets IS DISTINCT FROM pg_temp.vt_web_video_to_ms(action_sets);
        GET DIAGNOSTICS n_edges = ROW_COUNT;
    END IF;

    n_variants := 0;
    IF to_regclass('public.userinterface_variants') IS NOT NULL THEN
        UPDATE public.userinterface_variants
           SET node_overrides = pg_temp.vt_web_video_to_ms(node_overrides),
               edge_overrides = pg_temp.vt_web_video_to_ms(edge_overrides)
         WHERE node_overrides IS DISTINCT FROM pg_temp.vt_web_video_to_ms(node_overrides)
            OR edge_overrides IS DISTINCT FROM pg_temp.vt_web_video_to_ms(edge_overrides);
        GET DIAGNOSTICS n_variants = ROW_COUNT;
    END IF;

    n_testcases := 0;
    IF to_regclass('public.testcase_definitions') IS NOT NULL THEN
        UPDATE public.testcase_definitions
           SET graph_json = pg_temp.vt_web_video_to_ms(graph_json)
         WHERE graph_json IS DISTINCT FROM pg_temp.vt_web_video_to_ms(graph_json);
        GET DIAGNOSTICS n_testcases = ROW_COUNT;
    END IF;

    INSERT INTO public.data_migrations (name) VALUES ('20260928d_verification_timeout_web_video_to_ms');

    RAISE NOTICE '20260928d: nodes=% edges=% variants=% testcases=%',
        n_nodes, n_edges, n_variants, n_testcases;
END;
$$;

REFRESH MATERIALIZED VIEW public.mv_full_navigation_trees;

COMMIT;

SELECT '20260928d_verification_timeout_web_video_to_ms.sql applied' AS status;

-- ==============================================================================
-- AUDIT (read-only, NOT part of the migration): image/text/adb/appium timeouts that
-- are almost certainly seconds written into a millisecond field. Non-zero values
-- below 100 ms cannot be intended. Review and fix by hand (5 -> 5000, 15 -> 15000).
-- ==============================================================================
-- SELECT t.name AS tree, n.node_id, v->>'verification_type' AS type, v->>'command' AS command,
--        v->'params'->>'timeout' AS timeout
--   FROM navigation_nodes n
--   JOIN navigation_trees t ON t.id = n.tree_id
--   CROSS JOIN LATERAL jsonb_array_elements(COALESCE(n.verifications, '[]'::jsonb)) AS v
--  WHERE v->>'verification_type' IN ('image', 'text', 'adb', 'appium')
--    AND jsonb_typeof(v->'params'->'timeout') = 'number'
--    AND (v->'params'->>'timeout')::numeric > 0
--    AND (v->'params'->>'timeout')::numeric < 100
--  ORDER BY t.name, n.node_id;
-- Repeat with userinterface_variants.node_overrides
--   (jsonb_each(node_overrides) -> value->'verifications') and navigation_edges.action_sets
--   (action_sets[].kpi_references) for the same predicate.
