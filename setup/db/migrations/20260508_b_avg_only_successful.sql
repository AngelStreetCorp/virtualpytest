-- Fix calculation error: failed executions used to drag down the time
-- averages on edge_metrics / node_metrics.
--
-- Previous formula averaged execution_time_ms over `total_executions` (every
-- row, success or fail). A timed-out edge that ended up at 30s of retries +
-- final_wait was making "Action: 30.00s" appear on the panel even when the
-- typical successful traversal was 0.3s.
--
-- New formula averages over `successful_executions` only — same numerator
-- only when NEW.success=true; the avg is held flat on failure. Counts and
-- success_rate keep folding on every row (so failures still pull down the
-- success rate exactly like before).
--
-- KPI averages stay unchanged for now — the user wants this scoped to action
-- + verification times only.
--
-- Both edge_metrics.avg_action_time_ms and node_metrics.avg_verification_time_ms
-- are fixed in the same trigger function.

CREATE OR REPLACE FUNCTION public.update_metrics()
RETURNS TRIGGER
LANGUAGE plpgsql
SET search_path = ''
AS $$
DECLARE
    kpi_landed boolean;
BEGIN
    -- Editor runs (is_test=true) skip aggregation entirely. Production runs
    -- (is_test=false) flow through. See migration 20260508_is_test_flag.sql.
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
                -- avg_action_time_ms: only consider time on success. First
                -- failure stores 0 (no successful sample yet); first success
                -- stores its time.
                CASE WHEN NEW.success THEN COALESCE(NEW.execution_time_ms, 0) ELSE 0 END,
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
                -- Fold the new time into the running mean of SUCCESSFUL runs
                -- only. Failure leaves avg unchanged. Denominator is
                -- successful_executions (the OLD count, since SET expressions
                -- evaluate against pre-update row state in Postgres).
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
                -- Same fix as edge_metrics: average only successful runs.
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
