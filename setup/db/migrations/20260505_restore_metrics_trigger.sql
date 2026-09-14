-- ============================================================================
-- Restore the metrics aggregation trigger on execution_results
-- ============================================================================
-- The trigger trigger_update_metrics was originally created in
-- setup/db/migrations/add_kpi_measurement.sql, which was deleted in commit
-- 562c38084 (Nov 19, 2025) without folding the CREATE TRIGGER into
-- setup/db/schema/005_monitoring_analytics.sql. As a result fresh installs
-- (and any DB rebuilt after that date) had the function but no trigger, so
-- public.edge_metrics and public.node_metrics stayed empty forever and the
-- Navigation Editor edge/node panels showed "No data / 0s / #0 / 0".
--
-- This migration:
--   1. Replaces public.update_metrics() with a version that distinguishes
--      INSERT (new execution → bump counters) from UPDATE OF kpi_measurement_*
--      (KPI landed asynchronously from kpi_executor → fold KPI delta only,
--      do NOT recount the execution).
--   2. Recreates trigger_update_metrics on AFTER INSERT OR UPDATE OF the KPI
--      columns.
--   3. Backfills public.edge_metrics and public.node_metrics from the
--      existing public.execution_results rows.

CREATE OR REPLACE FUNCTION public.update_metrics()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = ''
AS $$
DECLARE
    kpi_landed boolean;
BEGIN
    IF TG_OP = 'INSERT' THEN
        -- Edge metrics: one row per (edge_id, tree_id, action_set_id).
        IF NEW.edge_id IS NOT NULL THEN
            INSERT INTO public.edge_metrics (
                edge_id,
                tree_id,
                team_id,
                action_set_id,
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
            ON CONFLICT (edge_id, tree_id, action_set_id)
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

        -- Node metrics: one row per (node_id, tree_id, team_id).
        IF NEW.node_id IS NOT NULL THEN
            INSERT INTO public.node_metrics (
                node_id,
                tree_id,
                team_id,
                total_executions,
                successful_executions,
                success_rate,
                avg_execution_time_ms
            )
            VALUES (
                NEW.node_id,
                NEW.tree_id,
                NEW.team_id,
                1,
                CASE WHEN NEW.success THEN 1 ELSE 0 END,
                CASE WHEN NEW.success THEN 1.0 ELSE 0.0 END,
                COALESCE(NEW.execution_time_ms, 0)
            )
            ON CONFLICT (node_id, tree_id, team_id)
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
        -- KPI columns are filled asynchronously by backend_host/scripts/kpi_executor.py
        -- via PATCH execution_results?id=... AFTER the navigation has already
        -- inserted the row. We MUST NOT re-count the execution; we only fold the
        -- KPI delta into edge_metrics. Trigger condition (the AFTER UPDATE OF
        -- list below) already restricts UPDATE firings to KPI columns, but we
        -- additionally guard on a NULL → non-NULL transition of
        -- kpi_measurement_ms so a no-op or repeated PATCH does not re-fold.
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
              AND action_set_id IS NOT DISTINCT FROM NEW.action_set_id;
        END IF;
    END IF;

    RETURN NEW;
END;
$$;

COMMENT ON FUNCTION public.update_metrics() IS
    'Aggregates execution_results into edge_metrics/node_metrics. INSERT bumps execution counters; UPDATE OF kpi_measurement_* folds the async KPI value (no recount).';

DROP TRIGGER IF EXISTS trigger_update_metrics ON public.execution_results;
CREATE TRIGGER trigger_update_metrics
    AFTER INSERT OR UPDATE OF kpi_measurement_ms, kpi_measurement_success
    ON public.execution_results
    FOR EACH ROW EXECUTE FUNCTION public.update_metrics();

-- ============================================================================
-- Backfill from historical execution_results
-- ============================================================================
-- Tables are currently empty for any DB that rebuilt after Nov 19, 2025.
-- Aggregate the existing rows once so historical confidence shows up.

INSERT INTO public.edge_metrics (
    edge_id,
    tree_id,
    team_id,
    action_set_id,
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
SELECT
    edge_id,
    tree_id,
    team_id,
    action_set_id,
    COUNT(*)::int,
    COUNT(*) FILTER (WHERE success)::int,
    (COUNT(*) FILTER (WHERE success))::numeric / COUNT(*),
    COALESCE(AVG(execution_time_ms), 0)::int,
    COUNT(*) FILTER (WHERE kpi_measurement_ms IS NOT NULL)::int,
    COUNT(*) FILTER (WHERE kpi_measurement_success)::int,
    COALESCE(AVG(kpi_measurement_ms) FILTER (WHERE kpi_measurement_ms IS NOT NULL), 0)::int,
    MIN(kpi_measurement_ms),
    MAX(kpi_measurement_ms),
    CASE
        WHEN COUNT(*) FILTER (WHERE kpi_measurement_ms IS NOT NULL) > 0 THEN
            (COUNT(*) FILTER (WHERE kpi_measurement_success))::numeric
            / COUNT(*) FILTER (WHERE kpi_measurement_ms IS NOT NULL)
        ELSE 0
    END
FROM public.execution_results
WHERE edge_id IS NOT NULL
  AND tree_id IS NOT NULL
  AND action_set_id IS NOT NULL
GROUP BY edge_id, tree_id, team_id, action_set_id
ON CONFLICT (edge_id, tree_id, action_set_id) DO NOTHING;

INSERT INTO public.node_metrics (
    node_id,
    tree_id,
    team_id,
    total_executions,
    successful_executions,
    success_rate,
    avg_execution_time_ms
)
SELECT
    node_id,
    tree_id,
    team_id,
    COUNT(*)::int,
    COUNT(*) FILTER (WHERE success)::int,
    (COUNT(*) FILTER (WHERE success))::numeric / COUNT(*),
    COALESCE(AVG(execution_time_ms), 0)::int
FROM public.execution_results
WHERE node_id IS NOT NULL
  AND tree_id IS NOT NULL
GROUP BY node_id, tree_id, team_id
ON CONFLICT (node_id, tree_id, team_id) DO NOTHING;

SELECT
    'restore_metrics_trigger: OK' AS status,
    (SELECT COUNT(*) FROM public.edge_metrics) AS edge_metrics_rows,
    (SELECT COUNT(*) FROM public.node_metrics) AS node_metrics_rows;
