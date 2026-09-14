-- Persist the run-level KPI display label onto execution_results.
--
-- Until now `kpi_display_label` (set by a script via device.navigation_context,
-- e.g. standby_measurement's standby-mode name "[TC268] Fast Start") only ever
-- reached the generated HTML KPI report header — it landed in no column, so the
-- "KPI Measurement" Grafana dashboard could not show it and fell back to the raw
-- action_set label ("live → standby").
--
-- It matters most where several logical measurements share ONE edge: every
-- standby mode is measured over the same wake edge, so action_set_id alone
-- cannot tell them apart. The dashboard groups on this column alongside
-- action_set_id so those runs separate into their own rows.

ALTER TABLE execution_results ADD COLUMN IF NOT EXISTS kpi_display_label text;

COMMENT ON COLUMN execution_results.kpi_display_label IS
    'KPI: run-level friendly name for this measurement (script-set via navigation_context, else the action_set kpi_name). Takes precedence over action_sets.kpi_name/label in the KPI dashboard.';

-- Backfill historical rows with the action_set's kpi_name — the same value the
-- executor will now stamp when a script sets no run-level label. Without this,
-- the dashboard (which groups on this column) would split one edge into two
-- identically-labelled rows either side of the deploy: NULL for old rows,
-- kpi_name for new ones.
--
-- Rows whose label came from a script (e.g. the standby modes) cannot be
-- recovered — that value was never persisted — so they stay NULL and keep
-- rendering under the raw edge label, correctly distinct from newly-named runs.
UPDATE execution_results er
SET kpi_display_label = sub.kpi_name
FROM (
    SELECT er2.id,
           (SELECT NULLIF(as_elem->>'kpi_name', '')
            FROM navigation_edges ne, jsonb_array_elements(ne.action_sets) AS as_elem
            WHERE ne.edge_id = regexp_replace(er2.edge_id, '_reverse$', '')
              AND ne.tree_id = er2.tree_id
              AND as_elem->>'id' = er2.action_set_id
            LIMIT 1) AS kpi_name
    FROM execution_results er2
    WHERE er2.kpi_measurement_ms IS NOT NULL
      AND er2.kpi_display_label IS NULL
) sub
WHERE er.id = sub.id
  AND sub.kpi_name IS NOT NULL;
