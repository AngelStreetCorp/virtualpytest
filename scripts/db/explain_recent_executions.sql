-- EXPLAIN the queries behind GET /server/deployment/executions/recent.
--
-- Usage (read-only, safe on production; EXPLAIN ANALYZE runs the SELECTs):
--   psql "$DB_URL" -v team=<TEAM_ID> -f scripts/db/explain_recent_executions.sql
--   (self-hosted supabase: docker exec -i supabase_db_supabase sh -c 'PGPASSWORD="$POSTGRES_PASSWORD" psql
--    -h 127.0.0.1 -U supabase_admin -d postgres -v team=<TEAM_ID>' < scripts/db/explain_recent_executions.sql)
--
-- The SQL mirrors what PostgREST builds for `deployments!inner(...)` embeds:
-- a LEFT JOIN LATERAL on the parent plus a NOT NULL check on it (on a column,
-- not the whole row: ROW(...) IS NOT NULL is false if any column is NULL).
-- Compare the "Execution Time" of each block; the route runs them concurrently,
-- so its `queries=` timing is roughly the slowest one plus contention.

\set ON_ERROR_STOP on
\pset pager off
BEGIN READ ONLY;

\echo '=== table sizes / shape ==='
SELECT
  (SELECT count(*) FROM deployment_executions)                               AS exec_rows,
  (SELECT count(*) FROM deployments)                                         AS deployment_rows,
  (SELECT count(*) FROM deployments WHERE team_id = :'team')                 AS team_deployments,
  (SELECT count(*) FROM deployments WHERE team_id = :'team' AND campaign_id IS NOT NULL) AS team_campaign_deployments;

SELECT de.status, (d.campaign_id IS NOT NULL) AS is_campaign, count(*)
FROM deployment_executions de JOIN deployments d ON d.id = de.deployment_id
WHERE d.team_id = :'team'
GROUP BY 1, 2 ORDER BY 1, 2;

SELECT indexname, indexdef FROM pg_indexes
WHERE tablename IN ('deployment_executions', 'deployments') ORDER BY tablename, indexname;

\echo '=== Q1 running ==='
EXPLAIN (ANALYZE, BUFFERS, SETTINGS)
SELECT de.id, de.deployment_id, de.script_result_id, de.scheduled_at, de.started_at,
       de.completed_at, de.status, de.success, de.error_message,
       row_to_json(dep.*) AS deployments, row_to_json(sr.*) AS script_results
FROM deployment_executions de
LEFT JOIN LATERAL (
  SELECT d.team_id, d.name, d.script_name, d.host_name, d.device_id, d.cron_expression,
         d.campaign_id, d.parameters, d.rerun_payload
  FROM deployments d WHERE d.id = de.deployment_id AND d.team_id = :'team'
) dep ON TRUE
LEFT JOIN LATERAL (
  SELECT s.html_report_r2_url, s.logs_r2_url FROM script_results s WHERE s.id = de.script_result_id
) sr ON TRUE
WHERE de.status = 'running' AND de.started_at >= now() - interval '4 hours'
  AND dep.team_id IS NOT NULL
ORDER BY de.started_at DESC;

\echo '=== Q2 queued ==='
EXPLAIN (ANALYZE, BUFFERS)
SELECT de.id, de.status, de.scheduled_at, row_to_json(dep.*) AS deployments
FROM deployment_executions de
LEFT JOIN LATERAL (
  SELECT d.team_id, d.name, d.script_name, d.host_name, d.device_id, d.campaign_id
  FROM deployments d WHERE d.id = de.deployment_id AND d.team_id = :'team'
) dep ON TRUE
WHERE de.status = 'queued' AND dep.team_id IS NOT NULL
ORDER BY de.scheduled_at DESC LIMIT 50;

\echo '=== Q3 completed scripts (campaign_id IS NULL) ==='
EXPLAIN (ANALYZE, BUFFERS)
SELECT de.id, de.status, de.started_at, row_to_json(dep.*) AS deployments,
       row_to_json(sr.*) AS script_results
FROM deployment_executions de
LEFT JOIN LATERAL (
  SELECT d.team_id, d.name, d.script_name, d.host_name, d.device_id, d.cron_expression,
         d.campaign_id, d.parameters, d.rerun_payload
  FROM deployments d
  WHERE d.id = de.deployment_id AND d.team_id = :'team' AND d.campaign_id IS NULL
) dep ON TRUE
LEFT JOIN LATERAL (
  SELECT s.html_report_r2_url, s.logs_r2_url FROM script_results s WHERE s.id = de.script_result_id
) sr ON TRUE
WHERE de.status IN ('completed', 'failed') AND dep.team_id IS NOT NULL
ORDER BY de.started_at DESC LIMIT 20;

\echo '=== Q4 completed campaigns (campaign_id IS NOT NULL) ==='
EXPLAIN (ANALYZE, BUFFERS)
SELECT de.id, de.status, de.started_at, row_to_json(dep.*) AS deployments,
       row_to_json(sr.*) AS script_results
FROM deployment_executions de
LEFT JOIN LATERAL (
  SELECT d.team_id, d.name, d.script_name, d.host_name, d.device_id, d.cron_expression,
         d.campaign_id, d.parameters, d.rerun_payload
  FROM deployments d
  WHERE d.id = de.deployment_id AND d.team_id = :'team' AND d.campaign_id IS NOT NULL
) dep ON TRUE
LEFT JOIN LATERAL (
  SELECT s.html_report_r2_url, s.logs_r2_url FROM script_results s WHERE s.id = de.script_result_id
) sr ON TRUE
WHERE de.status IN ('completed', 'failed') AND dep.team_id IS NOT NULL
ORDER BY de.started_at DESC LIMIT 20;

\echo '=== Q5 abort_stale (SELECT half) ==='
EXPLAIN (ANALYZE, BUFFERS)
SELECT de.id, row_to_json(dep.*) AS deployments
FROM deployment_executions de
LEFT JOIN LATERAL (
  SELECT d.team_id, d.rerun_payload FROM deployments d
  WHERE d.id = de.deployment_id AND d.team_id = :'team'
) dep ON TRUE
WHERE de.status = 'queued' AND de.scheduled_at < now() - interval '4 hours'
  AND dep.team_id IS NOT NULL;

ROLLBACK;
