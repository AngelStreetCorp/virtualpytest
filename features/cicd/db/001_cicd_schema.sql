-- CI/CD results — SEPARATE Grafana datasource and role, SAME Postgres database as VirtualPyTest.
--
-- Decision 2026-09-03: the CI/CD tables live in schema `cicd` of the Supabase `postgres`
-- database (192.168.x.102:54322), owned by role `cicd`. Same server URL as the VirtualPyTest
-- data (no second connection string on the VPT server: it reads them through its existing
-- Supabase client with `.schema('cicd')`), but isolated:
--   * role `cicd` (login) owns the schema; its search_path is `cicd` so writers (the GitHub
--     workflows' `psql "$CICD_DATABASE_URL"`, DSN …/postgres) and the Grafana datasource
--     `cicd-postgres` (user cicd, database postgres) address the tables by bare name;
--   * PostgREST exposes the schema (`pgrst.db_schemas` on role authenticator) so the VPT server
--     and the REST API reach it with the `Accept-Profile: cicd` / `.schema('cicd')` switch.
-- White-box + grey-box CI results of every project (virtualpytest, sample-app, …) go here;
-- black-box device runs stay in `public.script_results`.
--
-- Apply as supabase_admin on the Postgres server:
--   psql -h 127.0.0.1 -p 54322 -U supabase_admin -d postgres \
--        -v cicd_password='…' -v pgrst_schemas='public, graphql_public, cicd' \
--        -f 001_cicd_schema.sql
-- (pgrst_schemas = the currently exposed list + cicd; the REST error for an unknown
--  Accept-Profile lists the current one). Idempotent.

\set ON_ERROR_STOP on

SELECT 'CREATE ROLE cicd LOGIN PASSWORD ' || quote_literal(:'cicd_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'cicd') \gexec
ALTER ROLE cicd PASSWORD :'cicd_password';
ALTER ROLE cicd SET search_path = cicd;
GRANT CONNECT ON DATABASE postgres TO cicd;

CREATE SCHEMA IF NOT EXISTS cicd AUTHORIZATION cicd;

SET ROLE cicd;
SET search_path = cicd;
-- One row per workflow run. `run` is the report directory name on the reports server
-- ("138" for virtualpytest, "sample-app-4" for sample-app); `project` + `run` identify the run.
CREATE TABLE IF NOT EXISTS ci_runs (
  project     text        NOT NULL,
  run         text        NOT NULL,
  run_number  integer,
  branch      text,
  sha         text,
  runner      text,                                   -- GitHub Actions runner name
  started_at  timestamptz NOT NULL DEFAULT now(),
  report_url  text,                                   -- CI/CD Reports page entry for the run
  PRIMARY KEY (project, run)
);

-- One row per job of a run. `layer` is the test layer the job exercises:
--   white = code-visible (lint, unit, component, contract)
--   grey  = deployed backend / product driven from outside (API, Playwright, script smoke)
-- Black-box runs (VirtualPyTest scripts on devices) live in the VirtualPyTest database.
CREATE TABLE IF NOT EXISTS ci_jobs (
  project     text        NOT NULL,
  run         text        NOT NULL,
  job         text        NOT NULL,
  category    text,                                   -- lint | unit | api | browser | script
  layer       text        NOT NULL DEFAULT 'grey' CHECK (layer IN ('white', 'grey')),
  status      text        NOT NULL,                   -- success | failure | cancelled | skipped
  report_url  text,
  finished_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (project, run, job),
  FOREIGN KEY (project, run) REFERENCES ci_runs (project, run) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS ci_jobs_finished_at_idx ON ci_jobs (finished_at DESC);
CREATE INDEX IF NOT EXISTS ci_runs_started_at_idx  ON ci_runs (started_at DESC);

-- Per-run rollup used by the dashboard's runs table and pass-rate tiles.
CREATE OR REPLACE VIEW ci_run_summary AS
SELECT r.project, r.run, r.run_number, r.branch, r.sha, r.runner, r.started_at, r.report_url,
       count(j.job)                                        AS jobs,
       count(j.job) FILTER (WHERE j.status = 'success')    AS jobs_passed,
       count(j.job) FILTER (WHERE j.status = 'failure')    AS jobs_failed,
       CASE
         WHEN count(j.job) = 0                                                 THEN 'unknown'
         WHEN count(j.job) FILTER (WHERE j.status = 'failure') > 0             THEN 'failed'
         WHEN count(j.job) = count(j.job) FILTER (WHERE j.status = 'success')  THEN 'passed'
         ELSE 'partial'
       END                                                 AS overall,
       max(j.finished_at)                                  AS finished_at
FROM ci_runs r
LEFT JOIN ci_jobs j USING (project, run)
GROUP BY r.project, r.run, r.run_number, r.branch, r.sha, r.runner, r.started_at, r.report_url;

RESET ROLE;
RESET search_path;

-- PostgREST / Supabase access: the VPT server (service_role) reads and writes, the API roles read.
GRANT USAGE ON SCHEMA cicd TO anon, authenticated, service_role;
GRANT SELECT ON ALL TABLES IN SCHEMA cicd TO anon, authenticated;
GRANT ALL    ON ALL TABLES IN SCHEMA cicd TO service_role;
ALTER DEFAULT PRIVILEGES FOR ROLE cicd IN SCHEMA cicd GRANT SELECT ON TABLES TO anon, authenticated;
ALTER DEFAULT PRIVILEGES FOR ROLE cicd IN SCHEMA cicd GRANT ALL    ON TABLES TO service_role;

-- Expose the schema to PostgREST (in-database config overrides PGRST_DB_SCHEMAS; PostgREST >= 9).
ALTER ROLE authenticator SET pgrst.db_schemas = :'pgrst_schemas';
NOTIFY pgrst, 'reload config';
NOTIFY pgrst, 'reload schema';
