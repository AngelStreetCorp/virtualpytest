-- ============================================================================
-- Variant attribution on execution_results / edge_metrics / node_metrics
-- ============================================================================
-- After 20260505_restore_metrics_trigger.sql, every execution rolls up into a
-- single edge_metrics / node_metrics row keyed only by topology. That mixes
-- "ran on base" with "ran on a variant" together, so on the navigation editor
-- the same edge cannot show distinct averages depending on the canvas
-- viewing scope.
--
-- This migration:
--   1. Adds nullable `variant text` to public.execution_results, public.edge_metrics,
--      public.node_metrics. NULL = base run (matches resolver semantics).
--   2. Replaces the unique constraints on edge_metrics / node_metrics with
--      NULLS NOT DISTINCT keys that include `variant` so each (run_scope) gets
--      its own row.
--   3. Replaces public.update_metrics() so the trigger upserts into the
--      variant-aware row and so the UPDATE branch (KPI delta from
--      kpi_executor.py) only touches the matching variant.
--   4. Replaces public.get_tree_metrics_optimized() with a new arity:
--        get_tree_metrics_optimized(p_tree_id, p_team_id, p_variant text DEFAULT NULL)
--      that filters by variant. Default NULL → base-only.
--   5. Rebuilds edge_metrics / node_metrics from public.execution_results.
--      Historical rows have no variant column yet, so they all attribute to
--      NULL (base) — accurate enough since the variant feature only shipped
--      on 2026-05-05.
--
-- After applying, restart supabase_rest_supabase so the new RPC signature is
-- exposed to PostgREST:
--   ssh database "echo \$SUDO_PASSWORD | sudo -S docker restart supabase_rest_supabase"

BEGIN;

-- 0. Enforce lowercase on variant names --------------------------------------
-- Variant identity is case-insensitive at the user level — "Example" and
-- "example" are the same thing. We normalise by storing only lowercase and
-- rejecting anything else at the column level. No runtime casefolding
-- needed — every read returns canonical bytes.

UPDATE public.userinterface_variants
SET name = lower(name)
WHERE name <> lower(name);

ALTER TABLE public.userinterface_variants
    DROP CONSTRAINT IF EXISTS userinterface_variants_name_check;

ALTER TABLE public.userinterface_variants
    ADD CONSTRAINT userinterface_variants_name_check
    CHECK (name ~ '^[a-z0-9._-]{1,64}$');

-- 1. Columns -----------------------------------------------------------------

ALTER TABLE public.execution_results
    ADD COLUMN IF NOT EXISTS variant text;

ALTER TABLE public.execution_results
    DROP CONSTRAINT IF EXISTS execution_results_variant_lowercase_check;

ALTER TABLE public.execution_results
    ADD CONSTRAINT execution_results_variant_lowercase_check
    CHECK (variant IS NULL OR variant = lower(variant));

CREATE INDEX IF NOT EXISTS idx_execution_results_variant
    ON public.execution_results (team_id, tree_id, variant);

CREATE INDEX IF NOT EXISTS idx_execution_results_kpi_variant
    ON public.execution_results (team_id, tree_id, variant)
    WHERE kpi_measurement_ms IS NOT NULL;

ALTER TABLE public.edge_metrics
    ADD COLUMN IF NOT EXISTS variant text;

ALTER TABLE public.node_metrics
    ADD COLUMN IF NOT EXISTS variant text;

-- 2. Unique keys -------------------------------------------------------------
-- The old unique constraints did not include variant, so they would now
-- collapse base + variant rows into one. Drop them and recreate with
-- NULLS NOT DISTINCT so NULL-as-base behaves as a single concrete value.

ALTER TABLE public.edge_metrics
    DROP CONSTRAINT IF EXISTS edge_metrics_edge_id_tree_id_action_set_id_key;

ALTER TABLE public.edge_metrics
    ADD CONSTRAINT edge_metrics_edge_tree_action_variant_key
    UNIQUE NULLS NOT DISTINCT (edge_id, tree_id, action_set_id, variant);

ALTER TABLE public.node_metrics
    DROP CONSTRAINT IF EXISTS node_metrics_unique;

ALTER TABLE public.node_metrics
    ADD CONSTRAINT node_metrics_node_tree_team_variant_key
    UNIQUE NULLS NOT DISTINCT (node_id, tree_id, team_id, variant);

-- 3. Trigger function --------------------------------------------------------

CREATE OR REPLACE FUNCTION public.update_metrics()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = ''
AS $$
DECLARE
    kpi_landed boolean;
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.edge_id IS NOT NULL THEN
            INSERT INTO public.edge_metrics (
                edge_id,
                tree_id,
                team_id,
                action_set_id,
                variant,
                total_executions,
                successful_executions,
                success_rate,
                avg_execution_time_ms,
                total_kpi_measurements,
                successful_kpi_measurements,
                avg_kpi_ms,
                min_kpi_ms,
                max_kpi_ms,
                kpi_success_rate
            )
            VALUES (
                NEW.edge_id,
                NEW.tree_id,
                NEW.team_id,
                NEW.action_set_id,
                NEW.variant,
                1,
                CASE WHEN NEW.success THEN 1 ELSE 0 END,
                CASE WHEN NEW.success THEN 1.0 ELSE 0.0 END,
                COALESCE(NEW.execution_time_ms, 0),
                CASE WHEN NEW.kpi_measurement_ms IS NOT NULL THEN 1 ELSE 0 END,
                CASE WHEN NEW.kpi_measurement_success THEN 1 ELSE 0 END,
                COALESCE(NEW.kpi_measurement_ms, 0),
                NEW.kpi_measurement_ms,
                NEW.kpi_measurement_ms,
                CASE WHEN NEW.kpi_measurement_success THEN 1.0 ELSE 0.0 END
            )
            ON CONFLICT (edge_id, tree_id, action_set_id, variant)
            DO UPDATE SET
                total_executions = public.edge_metrics.total_executions + 1,
                successful_executions = public.edge_metrics.successful_executions
                    + CASE WHEN NEW.success THEN 1 ELSE 0 END,
                success_rate = (public.edge_metrics.successful_executions
                    + CASE WHEN NEW.success THEN 1 ELSE 0 END)::numeric
                    / (public.edge_metrics.total_executions + 1),
                avg_execution_time_ms = (
                    (public.edge_metrics.avg_execution_time_ms
                        * public.edge_metrics.total_executions)
                    + COALESCE(NEW.execution_time_ms, 0)
                ) / (public.edge_metrics.total_executions + 1),
                total_kpi_measurements = public.edge_metrics.total_kpi_measurements
                    + CASE WHEN NEW.kpi_measurement_ms IS NOT NULL THEN 1 ELSE 0 END,
                successful_kpi_measurements = public.edge_metrics.successful_kpi_measurements
                    + CASE WHEN NEW.kpi_measurement_success THEN 1 ELSE 0 END,
                avg_kpi_ms = CASE
                    WHEN NEW.kpi_measurement_ms IS NOT NULL THEN
                        ((public.edge_metrics.avg_kpi_ms
                            * public.edge_metrics.total_kpi_measurements)
                            + NEW.kpi_measurement_ms)
                            / (public.edge_metrics.total_kpi_measurements + 1)
                    ELSE public.edge_metrics.avg_kpi_ms
                END,
                min_kpi_ms = CASE
                    WHEN NEW.kpi_measurement_ms IS NOT NULL THEN
                        LEAST(COALESCE(public.edge_metrics.min_kpi_ms,
                            NEW.kpi_measurement_ms), NEW.kpi_measurement_ms)
                    ELSE public.edge_metrics.min_kpi_ms
                END,
                max_kpi_ms = CASE
                    WHEN NEW.kpi_measurement_ms IS NOT NULL THEN
                        GREATEST(COALESCE(public.edge_metrics.max_kpi_ms,
                            NEW.kpi_measurement_ms), NEW.kpi_measurement_ms)
                    ELSE public.edge_metrics.max_kpi_ms
                END,
                kpi_success_rate = CASE
                    WHEN public.edge_metrics.total_kpi_measurements
                        + CASE WHEN NEW.kpi_measurement_ms IS NOT NULL THEN 1 ELSE 0 END > 0 THEN
                        (public.edge_metrics.successful_kpi_measurements
                            + CASE WHEN NEW.kpi_measurement_success THEN 1 ELSE 0 END)::numeric
                        / (public.edge_metrics.total_kpi_measurements
                            + CASE WHEN NEW.kpi_measurement_ms IS NOT NULL THEN 1 ELSE 0 END)
                    ELSE 0
                END;
        END IF;

        IF NEW.node_id IS NOT NULL THEN
            INSERT INTO public.node_metrics (
                node_id,
                tree_id,
                team_id,
                variant,
                total_executions,
                successful_executions,
                success_rate,
                avg_execution_time_ms
            )
            VALUES (
                NEW.node_id,
                NEW.tree_id,
                NEW.team_id,
                NEW.variant,
                1,
                CASE WHEN NEW.success THEN 1 ELSE 0 END,
                CASE WHEN NEW.success THEN 1.0 ELSE 0.0 END,
                COALESCE(NEW.execution_time_ms, 0)
            )
            ON CONFLICT (node_id, tree_id, team_id, variant)
            DO UPDATE SET
                total_executions = public.node_metrics.total_executions + 1,
                successful_executions = public.node_metrics.successful_executions
                    + CASE WHEN NEW.success THEN 1 ELSE 0 END,
                success_rate = (public.node_metrics.successful_executions
                    + CASE WHEN NEW.success THEN 1 ELSE 0 END)::numeric
                    / (public.node_metrics.total_executions + 1),
                avg_execution_time_ms = (
                    (public.node_metrics.avg_execution_time_ms
                        * public.node_metrics.total_executions)
                    + COALESCE(NEW.execution_time_ms, 0)
                ) / (public.node_metrics.total_executions + 1);
        END IF;

    ELSIF TG_OP = 'UPDATE' THEN
        kpi_landed := NEW.kpi_measurement_ms IS NOT NULL
            AND OLD.kpi_measurement_ms IS DISTINCT FROM NEW.kpi_measurement_ms;

        IF kpi_landed AND NEW.edge_id IS NOT NULL THEN
            UPDATE public.edge_metrics SET
                total_kpi_measurements = total_kpi_measurements + 1,
                successful_kpi_measurements = successful_kpi_measurements
                    + CASE WHEN NEW.kpi_measurement_success THEN 1 ELSE 0 END,
                avg_kpi_ms = ((avg_kpi_ms * total_kpi_measurements)
                    + NEW.kpi_measurement_ms) / (total_kpi_measurements + 1),
                min_kpi_ms = LEAST(COALESCE(min_kpi_ms, NEW.kpi_measurement_ms),
                    NEW.kpi_measurement_ms),
                max_kpi_ms = GREATEST(COALESCE(max_kpi_ms, NEW.kpi_measurement_ms),
                    NEW.kpi_measurement_ms),
                kpi_success_rate = (successful_kpi_measurements
                    + CASE WHEN NEW.kpi_measurement_success THEN 1 ELSE 0 END)::numeric
                    / (total_kpi_measurements + 1)
            WHERE edge_id = NEW.edge_id
              AND tree_id IS NOT DISTINCT FROM NEW.tree_id
              AND action_set_id IS NOT DISTINCT FROM NEW.action_set_id
              AND variant IS NOT DISTINCT FROM NEW.variant;
        END IF;
    END IF;

    RETURN NEW;
END;
$$;

COMMENT ON FUNCTION public.update_metrics() IS
    'Aggregates execution_results into edge_metrics/node_metrics keyed by run scope (variant). NULL variant = base run.';

-- 4. Optimised metrics fetch — variant-aware --------------------------------

DROP FUNCTION IF EXISTS public.get_tree_metrics_optimized(uuid, uuid);

CREATE OR REPLACE FUNCTION public.get_tree_metrics_optimized(
    p_tree_id uuid,
    p_team_id uuid,
    p_variant text DEFAULT NULL
)
RETURNS json
LANGUAGE plpgsql
STABLE SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_node_metrics JSON;
    v_edge_metrics JSON;
    v_global_confidence NUMERIC;
    v_confidence_distribution JSON;
    v_all_confidences NUMERIC[];
BEGIN
    SELECT json_object_agg(
        node_id,
        json_build_object(
            'volume', total_executions,
            'success_rate', success_rate::float,
            'avg_execution_time', avg_execution_time_ms,
            'confidence', CASE
                WHEN total_executions = 0 THEN 0.0
                WHEN total_executions < 10 THEN success_rate::float * (total_executions / 10.0)
                ELSE success_rate::float
            END
        )
    )
    INTO v_node_metrics
    FROM public.node_metrics
    WHERE team_id = p_team_id
      AND tree_id = p_tree_id
      AND variant IS NOT DISTINCT FROM p_variant;

    SELECT json_object_agg(
        edge_id || COALESCE('#' || action_set_id, ''),
        json_build_object(
            'volume', total_executions,
            'success_rate', success_rate::float,
            'avg_execution_time', avg_execution_time_ms,
            'confidence', CASE
                WHEN total_executions = 0 THEN 0.0
                WHEN total_executions < 10 THEN success_rate::float * (total_executions / 10.0)
                ELSE success_rate::float
            END
        )
    )
    INTO v_edge_metrics
    FROM public.edge_metrics
    WHERE team_id = p_team_id
      AND tree_id = p_tree_id
      AND variant IS NOT DISTINCT FROM p_variant;

    SELECT array_agg(confidence)
    INTO v_all_confidences
    FROM (
        SELECT
            CASE
                WHEN total_executions = 0 THEN 0.0
                WHEN total_executions < 10 THEN success_rate::float * (total_executions / 10.0)
                ELSE success_rate::float
            END as confidence
        FROM public.node_metrics
        WHERE team_id = p_team_id
          AND tree_id = p_tree_id
          AND variant IS NOT DISTINCT FROM p_variant

        UNION ALL

        SELECT
            CASE
                WHEN total_executions = 0 THEN 0.0
                WHEN total_executions < 10 THEN success_rate::float * (total_executions / 10.0)
                ELSE success_rate::float
            END as confidence
        FROM public.edge_metrics
        WHERE team_id = p_team_id
          AND tree_id = p_tree_id
          AND variant IS NOT DISTINCT FROM p_variant
    ) all_conf;

    IF v_all_confidences IS NOT NULL AND array_length(v_all_confidences, 1) > 0 THEN
        SELECT AVG(c) INTO v_global_confidence FROM unnest(v_all_confidences) c;
    ELSE
        v_global_confidence := 0.0;
    END IF;

    SELECT json_build_object(
        'high', COUNT(*) FILTER (WHERE c >= 0.8),
        'medium', COUNT(*) FILTER (WHERE c >= 0.5 AND c < 0.8),
        'low', COUNT(*) FILTER (WHERE c >= 0.1 AND c < 0.5),
        'untested', COUNT(*) FILTER (WHERE c < 0.1)
    )
    INTO v_confidence_distribution
    FROM unnest(v_all_confidences) c;

    RETURN json_build_object(
        'success', true,
        'variant', p_variant,
        'nodes', COALESCE(v_node_metrics, '{}'::json),
        'edges', COALESCE(v_edge_metrics, '{}'::json),
        'global_confidence', COALESCE(v_global_confidence, 0.0),
        'confidence_distribution', COALESCE(v_confidence_distribution,
            json_build_object('high', 0, 'medium', 0, 'low', 0, 'untested', 0))
    );
END;
$$;

COMMENT ON FUNCTION public.get_tree_metrics_optimized(uuid, uuid, text) IS
    'Aggregated metrics for a tree filtered by run scope (variant). NULL p_variant = base-only.';

-- 5. No rebuild needed -------------------------------------------------------
-- Existing rows in edge_metrics / node_metrics already pick up variant=NULL
-- from the new column's default, which is exactly the right value for them
-- (every historical execution_results row predates variant attribution and is
-- therefore base). Future runs stamp variant via the trigger and split off
-- their own scope rows automatically.

COMMIT;

SELECT
    'kpi_variant_attribution: OK' AS status,
    (SELECT COUNT(*) FROM public.edge_metrics) AS edge_metrics_rows,
    (SELECT COUNT(*) FROM public.node_metrics) AS node_metrics_rows,
    (SELECT COUNT(*) FROM public.edge_metrics WHERE variant IS NULL) AS edge_metrics_base_rows,
    (SELECT COUNT(*) FROM public.edge_metrics WHERE variant IS NOT NULL) AS edge_metrics_variant_rows;
