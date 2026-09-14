-- Corrective migration: 20260508_b_avg_only_successful.sql and
-- 20260508_c_kpi_avg_only_successful.sql accidentally re-introduced the
-- `IF NEW.is_test THEN RETURN NEW; END IF;` short-circuit that
-- 20260507_d_drop_is_test_guard.sql had removed.
--
-- The intended behavior (per 20260507_d) is: every row aggregates, including
-- editor runs (is_test=true). Grafana filters on `execution_results.is_test`
-- at the read layer so a single edge_metrics row is the source of truth.
--
-- This migration restores the no-guard function while keeping the
-- successful-runs-only fix for action / verification / KPI time averages.

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
                edge_id,
                tree_id,
                team_id,
                action_set_id,
                variant,
                total_executions,
                successful_executions,
                success_rate,
                avg_action_time_ms,
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
                -- avg_action_time_ms reflects successful runs only. First
                -- failure stores 0; first success stores its time.
                CASE WHEN NEW.success THEN COALESCE(NEW.execution_time_ms, 0) ELSE 0 END,
                CASE WHEN NEW.kpi_measurement_ms IS NOT NULL THEN 1 ELSE 0 END,
                CASE WHEN NEW.kpi_measurement_success THEN 1 ELSE 0 END,
                -- avg / min / max KPI: only successful scans count. Failed
                -- scans (timeout) inflate the time without representing real
                -- user-perceived latency.
                CASE WHEN NEW.kpi_measurement_success THEN COALESCE(NEW.kpi_measurement_ms, 0) ELSE 0 END,
                CASE WHEN NEW.kpi_measurement_success THEN NEW.kpi_measurement_ms END,
                CASE WHEN NEW.kpi_measurement_success THEN NEW.kpi_measurement_ms END,
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
                -- Fold time only when NEW.success — failed runs leave the
                -- mean unchanged. Denominator = OLD successful_executions.
                avg_action_time_ms = CASE
                    WHEN NEW.success THEN
                        ((public.edge_metrics.avg_action_time_ms
                            * public.edge_metrics.successful_executions)
                            + COALESCE(NEW.execution_time_ms, 0))
                            / (public.edge_metrics.successful_executions + 1)
                    ELSE public.edge_metrics.avg_action_time_ms
                END,
                total_kpi_measurements = public.edge_metrics.total_kpi_measurements
                    + CASE WHEN NEW.kpi_measurement_ms IS NOT NULL THEN 1 ELSE 0 END,
                successful_kpi_measurements = public.edge_metrics.successful_kpi_measurements
                    + CASE WHEN NEW.kpi_measurement_success THEN 1 ELSE 0 END,
                -- Successful KPI scans only. Denominator = OLD
                -- successful_kpi_measurements.
                avg_kpi_ms = CASE
                    WHEN NEW.kpi_measurement_success THEN
                        ((public.edge_metrics.avg_kpi_ms
                            * public.edge_metrics.successful_kpi_measurements)
                            + NEW.kpi_measurement_ms)
                            / (public.edge_metrics.successful_kpi_measurements + 1)
                    ELSE public.edge_metrics.avg_kpi_ms
                END,
                min_kpi_ms = CASE
                    WHEN NEW.kpi_measurement_success THEN
                        LEAST(COALESCE(public.edge_metrics.min_kpi_ms,
                            NEW.kpi_measurement_ms), NEW.kpi_measurement_ms)
                    ELSE public.edge_metrics.min_kpi_ms
                END,
                max_kpi_ms = CASE
                    WHEN NEW.kpi_measurement_success THEN
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
                avg_verification_time_ms
            )
            VALUES (
                NEW.node_id,
                NEW.tree_id,
                NEW.team_id,
                NEW.variant,
                1,
                CASE WHEN NEW.success THEN 1 ELSE 0 END,
                CASE WHEN NEW.success THEN 1.0 ELSE 0.0 END,
                CASE WHEN NEW.success THEN COALESCE(NEW.execution_time_ms, 0) ELSE 0 END
            )
            ON CONFLICT (node_id, tree_id, team_id, variant)
            DO UPDATE SET
                total_executions = public.node_metrics.total_executions + 1,
                successful_executions = public.node_metrics.successful_executions
                    + CASE WHEN NEW.success THEN 1 ELSE 0 END,
                success_rate = (public.node_metrics.successful_executions
                    + CASE WHEN NEW.success THEN 1 ELSE 0 END)::numeric
                    / (public.node_metrics.total_executions + 1),
                avg_verification_time_ms = CASE
                    WHEN NEW.success THEN
                        ((public.node_metrics.avg_verification_time_ms
                            * public.node_metrics.successful_executions)
                            + COALESCE(NEW.execution_time_ms, 0))
                            / (public.node_metrics.successful_executions + 1)
                    ELSE public.node_metrics.avg_verification_time_ms
                END;
        END IF;

    ELSIF TG_OP = 'UPDATE' THEN
        kpi_landed := NEW.kpi_measurement_ms IS NOT NULL
            AND OLD.kpi_measurement_ms IS DISTINCT FROM NEW.kpi_measurement_ms;

        IF kpi_landed AND NEW.edge_id IS NOT NULL THEN
            UPDATE public.edge_metrics SET
                total_kpi_measurements = total_kpi_measurements + 1,
                successful_kpi_measurements = successful_kpi_measurements
                    + CASE WHEN NEW.kpi_measurement_success THEN 1 ELSE 0 END,
                avg_kpi_ms = CASE
                    WHEN NEW.kpi_measurement_success THEN
                        ((avg_kpi_ms * successful_kpi_measurements)
                            + NEW.kpi_measurement_ms)
                            / (successful_kpi_measurements + 1)
                    ELSE avg_kpi_ms
                END,
                min_kpi_ms = CASE
                    WHEN NEW.kpi_measurement_success THEN
                        LEAST(COALESCE(min_kpi_ms, NEW.kpi_measurement_ms),
                            NEW.kpi_measurement_ms)
                    ELSE min_kpi_ms
                END,
                max_kpi_ms = CASE
                    WHEN NEW.kpi_measurement_success THEN
                        GREATEST(COALESCE(max_kpi_ms, NEW.kpi_measurement_ms),
                            NEW.kpi_measurement_ms)
                    ELSE max_kpi_ms
                END,
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
    'Aggregates execution_results into edge_metrics/node_metrics keyed by run scope (variant). NULL variant = base run. is_test=true rows aggregate alongside is_test=false; Grafana filters on execution_results.is_test directly. Time averages (action / verification / kpi) fold only on success; failures still bump counts and pull success_rate down.';
