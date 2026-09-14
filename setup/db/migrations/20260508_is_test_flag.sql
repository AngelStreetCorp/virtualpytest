-- Mark interactive frontend runs (Run / Goto / Edge Run from the Navigation
-- Editor) so the metrics trigger excludes them from edge_metrics /
-- node_metrics aggregates. Rows still land in execution_results so they
-- show up in the Details table — they just don't pollute the panel chips.
--
-- Reasoning: when iterating in the editor, the user clicks Run repeatedly
-- to debug a verification or test a goto. Each click was bumping
-- avg_action_time_ms / total_executions / success_rate the same way a CI
-- run does. With this flag, only CLI / pipeline runs (default is_test=false)
-- contribute to the aggregates that drive the panel and the auto-mode
-- confidence threshold.

ALTER TABLE public.execution_results
    ADD COLUMN IF NOT EXISTS is_test boolean NOT NULL DEFAULT false;

COMMENT ON COLUMN public.execution_results.is_test IS
    'true = interactive run from the Navigation Editor (Run / Goto / Edge Run); excluded from edge_metrics / node_metrics aggregates by update_metrics(). Default false = CLI / pipeline run.';

-- Replace update_metrics() with an is_test guard. Both branches early-return
-- on test rows. The function body is otherwise identical to the version in
-- setup/db/schema/005_monitoring_analytics.sql.
CREATE OR REPLACE FUNCTION public.update_metrics()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = ''
AS $$
DECLARE
    kpi_landed boolean;
BEGIN
    -- Skip test rows entirely. Editor "Run" / "Goto" / "Edge Run" set
    -- is_test=true so iterating in the UI cannot move the aggregate.
    IF NEW.is_test THEN
        RETURN NEW;
    END IF;

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
