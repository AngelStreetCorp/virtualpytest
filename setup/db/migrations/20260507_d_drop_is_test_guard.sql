-- Drop the is_test guard from update_metrics() so editor runs feed
-- edge_metrics / node_metrics. The frontend continues to send is_test=true
-- for interactive runs; Grafana can still slice on execution_results.is_test.
--
-- Idempotent: replaces the function body and rebuilds aggregates from
-- execution_results in one shot. Safe to re-run.

BEGIN;

CREATE OR REPLACE FUNCTION public.update_metrics()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = ''
AS $$
DECLARE
    kpi_landed boolean;
BEGIN
    -- Editor runs (is_test=true) AND CLI / pipeline runs (is_test=false) both
    -- aggregate into the same row. is_test stays on execution_results so
    -- Grafana panels can filter, but edge_metrics / node_metrics is keyed on
    -- (edge_id, tree_id, action_set_id, variant) so the editor sees totals
    -- across both scopes without doing its own filtering.

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

COMMENT ON FUNCTION public.update_metrics() IS
    'Aggregates execution_results into edge_metrics/node_metrics keyed by run scope (variant). NULL variant = base run. is_test=true rows aggregate alongside is_test=false; Grafana filters on execution_results.is_test directly.';

-- Backfill aggregates from existing rows (test + non-test together).
TRUNCATE public.edge_metrics, public.node_metrics;

INSERT INTO public.edge_metrics (
    edge_id, tree_id, team_id, action_set_id, variant,
    total_executions, successful_executions, success_rate,
    avg_action_time_ms,
    total_kpi_measurements, successful_kpi_measurements,
    avg_kpi_ms, min_kpi_ms, max_kpi_ms, kpi_success_rate
)
SELECT
    edge_id, tree_id, team_id, action_set_id, variant,
    COUNT(*) AS total_executions,
    COUNT(*) FILTER (WHERE success) AS successful_executions,
    COUNT(*) FILTER (WHERE success)::numeric / NULLIF(COUNT(*), 0) AS success_rate,
    COALESCE(AVG(execution_time_ms)::int, 0) AS avg_action_time_ms,
    COUNT(*) FILTER (WHERE kpi_measurement_ms IS NOT NULL) AS total_kpi_measurements,
    COUNT(*) FILTER (WHERE kpi_measurement_success IS TRUE) AS successful_kpi_measurements,
    COALESCE(AVG(kpi_measurement_ms)::int, 0) AS avg_kpi_ms,
    MIN(kpi_measurement_ms) AS min_kpi_ms,
    MAX(kpi_measurement_ms) AS max_kpi_ms,
    CASE WHEN COUNT(*) FILTER (WHERE kpi_measurement_ms IS NOT NULL) > 0 THEN
        COUNT(*) FILTER (WHERE kpi_measurement_success IS TRUE)::numeric
        / COUNT(*) FILTER (WHERE kpi_measurement_ms IS NOT NULL)
    ELSE 0 END AS kpi_success_rate
FROM public.execution_results
WHERE edge_id IS NOT NULL
GROUP BY edge_id, tree_id, team_id, action_set_id, variant;

INSERT INTO public.node_metrics (
    node_id, tree_id, team_id, variant,
    total_executions, successful_executions, success_rate,
    avg_verification_time_ms
)
SELECT
    node_id, tree_id, team_id, variant,
    COUNT(*) AS total_executions,
    COUNT(*) FILTER (WHERE success) AS successful_executions,
    COUNT(*) FILTER (WHERE success)::numeric / NULLIF(COUNT(*), 0) AS success_rate,
    COALESCE(AVG(execution_time_ms)::int, 0) AS avg_verification_time_ms
FROM public.execution_results
WHERE node_id IS NOT NULL
GROUP BY node_id, tree_id, team_id, variant;

COMMIT;
