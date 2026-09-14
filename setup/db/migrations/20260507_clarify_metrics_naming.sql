-- ============================================================================
-- Clarify metric column names + add edge_navigation_metrics convenience VIEW
-- ============================================================================
-- The old `avg_execution_time_ms` column existed on both edge_metrics and
-- node_metrics with different semantics:
--   - edge_metrics: full step wall-clock (action + final_wait + verification
--     when it ran) — a mixed signal that depended on verification_mode
--   - node_metrics: pure verify_node() duration
-- Same name, two meanings. This migration renames each so the column tells
-- you what it measures, and changes the writer side (navigation_executor.py)
-- to capture action + final_wait directly (no more "subtract verification").
--
--   edge_metrics.avg_execution_time_ms → avg_action_time_ms
--     "How long traversing this edge takes: actions + final_wait. Never
--      includes verification time. Consistent across verification modes."
--
--   node_metrics.avg_execution_time_ms → avg_verification_time_ms
--     "How long verify_node() takes on this node."
--
-- The full navigation step time = edge.avg_action_time_ms +
-- destination_node.avg_verification_time_ms. Computed at read time, not
-- stored — see edge_navigation_metrics VIEW below for ad-hoc SQL access.
--
-- Aggregates are TRUNCATEd because historical edge_metrics.avg_execution_time_ms
-- mixed verification time into the action time depending on mode; the new
-- avg_action_time_ms must not carry that pollution.

BEGIN;

TRUNCATE TABLE public.edge_metrics;
TRUNCATE TABLE public.node_metrics;

-- Idempotent rename: if the old column still exists, rename it. If the
-- schema was applied fresh (so the column was born as avg_action_time_ms /
-- avg_verification_time_ms already), skip silently. Either path leaves
-- the table in the canonical post-migration shape.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'edge_metrics'
          AND column_name = 'avg_execution_time_ms'
    ) THEN
        ALTER TABLE public.edge_metrics
            RENAME COLUMN avg_execution_time_ms TO avg_action_time_ms;
    END IF;

    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = 'node_metrics'
          AND column_name = 'avg_execution_time_ms'
    ) THEN
        ALTER TABLE public.node_metrics
            RENAME COLUMN avg_execution_time_ms TO avg_verification_time_ms;
    END IF;
END $$;

COMMENT ON COLUMN public.edge_metrics.avg_action_time_ms IS
    'Average wall-clock duration of traversing this edge: actions + final_wait_time. Never includes verification.';
COMMENT ON COLUMN public.node_metrics.avg_verification_time_ms IS
    'Average wall-clock duration of verify_node() calls on this node.';

-- ============================================================================
-- Trigger function — same logic, new column names
-- ============================================================================

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
                edge_id, tree_id, team_id, action_set_id, variant,
                total_executions, successful_executions, success_rate,
                avg_action_time_ms,
                total_kpi_measurements, successful_kpi_measurements,
                avg_kpi_ms, min_kpi_ms, max_kpi_ms, kpi_success_rate
            )
            VALUES (
                NEW.edge_id, NEW.tree_id, NEW.team_id, NEW.action_set_id, NEW.variant,
                1,
                CASE WHEN NEW.success THEN 1 ELSE 0 END,
                CASE WHEN NEW.success THEN 1.0 ELSE 0.0 END,
                COALESCE(NEW.execution_time_ms, 0),
                CASE WHEN NEW.kpi_measurement_ms IS NOT NULL THEN 1 ELSE 0 END,
                CASE WHEN NEW.kpi_measurement_success THEN 1 ELSE 0 END,
                COALESCE(NEW.kpi_measurement_ms, 0),
                NEW.kpi_measurement_ms, NEW.kpi_measurement_ms,
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
                avg_action_time_ms = (
                    (public.edge_metrics.avg_action_time_ms
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
                node_id, tree_id, team_id, variant,
                total_executions, successful_executions, success_rate,
                avg_verification_time_ms
            )
            VALUES (
                NEW.node_id, NEW.tree_id, NEW.team_id, NEW.variant,
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
                avg_verification_time_ms = (
                    (public.node_metrics.avg_verification_time_ms
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

-- ============================================================================
-- RPC — return new field names
-- ============================================================================

DROP FUNCTION IF EXISTS public.get_tree_metrics_optimized(uuid, uuid, text);

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
            'avg_verification_time', avg_verification_time_ms,
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
            'avg_action_time', avg_action_time_ms,
            'avg_kpi_ms', avg_kpi_ms,
            'kpi_volume', total_kpi_measurements,
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
        WHERE team_id = p_team_id AND tree_id = p_tree_id
          AND variant IS NOT DISTINCT FROM p_variant
        UNION ALL
        SELECT
            CASE
                WHEN total_executions = 0 THEN 0.0
                WHEN total_executions < 10 THEN success_rate::float * (total_executions / 10.0)
                ELSE success_rate::float
            END as confidence
        FROM public.edge_metrics
        WHERE team_id = p_team_id AND tree_id = p_tree_id
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

-- ============================================================================
-- VIEW — convenience for ad-hoc SQL / Grafana
-- ============================================================================
-- Joins edge_metrics with node_metrics on the destination node so the full
-- "navigation step time" (action + verification) is available without
-- callers writing the join. NULL-safe LEFT JOIN — edges whose destination
-- has never been verified still appear, with avg_verification_time_ms NULL
-- and avg_navigation_time_ms = avg_action_time_ms.

DROP VIEW IF EXISTS public.edge_navigation_metrics;

CREATE VIEW public.edge_navigation_metrics AS
SELECT
    em.id,
    em.edge_id,
    em.tree_id,
    em.team_id,
    em.action_set_id,
    em.variant,
    em.created_at,
    em.total_executions,
    em.successful_executions,
    em.success_rate,
    em.avg_action_time_ms,
    nm.avg_verification_time_ms AS dest_avg_verification_time_ms,
    em.avg_action_time_ms + COALESCE(nm.avg_verification_time_ms, 0)
        AS avg_navigation_time_ms,
    em.total_kpi_measurements,
    em.successful_kpi_measurements,
    em.avg_kpi_ms,
    em.min_kpi_ms,
    em.max_kpi_ms,
    em.kpi_success_rate,
    ne.target_node_id AS dest_node_id
FROM public.edge_metrics em
LEFT JOIN public.navigation_edges ne
    ON ne.edge_id = em.edge_id
    AND ne.team_id = em.team_id
LEFT JOIN public.node_metrics nm
    ON nm.node_id = ne.target_node_id
    AND nm.tree_id = em.tree_id
    AND nm.team_id = em.team_id
    AND nm.variant IS NOT DISTINCT FROM em.variant;

COMMENT ON VIEW public.edge_navigation_metrics IS
    'Read-side convenience: edge_metrics joined to the destination node''s node_metrics, with avg_navigation_time_ms = avg_action_time_ms + dest_avg_verification_time_ms. Use for ad-hoc SQL / Grafana / reporting. The frontend computes the same sum at read time from the get_tree_metrics_optimized RPC payload.';

COMMIT;

SELECT
    'clarify_metrics_naming: OK' AS status,
    (SELECT COUNT(*) FROM public.edge_metrics) AS edge_metrics_rows,
    (SELECT COUNT(*) FROM public.node_metrics) AS node_metrics_rows;
