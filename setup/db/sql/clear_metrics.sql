-- Clear all aggregated navigation metrics and the underlying execution rows.
-- After this, NavigationEditor panels render "No data" until new runs land.

TRUNCATE TABLE public.edge_metrics;
TRUNCATE TABLE public.node_metrics;
TRUNCATE TABLE public.execution_results;
