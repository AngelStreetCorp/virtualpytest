-- CI/CD feature — project registry, dispatch log, and run provenance (TASK-06 W3).
--
-- Adds to the `cicd` schema created by 001_cicd_schema.sql:
--   * ci_projects   — replaces the CI_PROJECT_REPOS env mapping; edited from the Run CI/CD page
--   * ci_dispatches — what the Run CI/CD page launched (audit + "recent dispatches" list)
--   * ci_runs.trigger / ci_runs.suite — how a run started and which suite it ran
--
-- Apply as supabase_admin on the Postgres server (idempotent):
--   psql -h 127.0.0.1 -p 54322 -U supabase_admin -d postgres -f 002_ci_projects.sql
--
-- `suites` / `cloud_suites` seeds come from the real job rows in ci_jobs (2026-09-03).
-- cloud_suites is deliberately white-only: Cloudflare 403s virtualpytest.angelstreet.io for
-- non-browser clients (verified 2026-09-03 from a laptop and from headless Chromium), so a
-- grey suite driven from a GitHub-hosted runner against the public URL is not trusted yet.
-- Widen it once a cloud grey run is proven to get through.

\set ON_ERROR_STOP on

SET ROLE cicd;
SET search_path = cicd;

-- One row per project that has CI. `report_prefix` is how its run directories are named on
-- the reports server: '' for virtualpytest (bare "138"), 'sample-app-' for sample-app ("sample-app-4").
CREATE TABLE IF NOT EXISTS ci_projects (
  project        text        PRIMARY KEY,
  repo           text        NOT NULL,                       -- owner/name on GitHub
  workflow_file  text        NOT NULL,                       -- e.g. regression.yml
  default_branch text        NOT NULL DEFAULT 'main',
  report_prefix  text        NOT NULL DEFAULT '',
  suites         jsonb       NOT NULL DEFAULT '{}'::jsonb,    -- {"white":[job,…],"grey":[job,…]}
  runner_labels  text[]      NOT NULL DEFAULT '{}',           -- self-hosted labels the workflow targets
  cloud_suites   text[]      NOT NULL DEFAULT '{}',           -- suites allowed on GitHub-hosted runners
  enabled        boolean     NOT NULL DEFAULT true,
  updated_at     timestamptz NOT NULL DEFAULT now()
);

-- One row per launch from the Run CI/CD page. github_run_id is filled once the dispatched
-- run shows up in the GitHub API (the dispatch endpoint polls briefly); status tracks it
-- until the workflow's own publish step writes the ci_runs/ci_jobs rows.
CREATE TABLE IF NOT EXISTS ci_dispatches (
  id            bigserial   PRIMARY KEY,
  project       text        NOT NULL,
  branch        text        NOT NULL,
  suite         text        NOT NULL,                        -- white | grey | all
  runner_target text        NOT NULL,                        -- self-hosted | github-hosted
  requested_by  text,                                        -- user email / id from the JWT
  requested_at  timestamptz NOT NULL DEFAULT now(),
  github_run_id bigint,
  status        text        NOT NULL DEFAULT 'requested'     -- requested | running | done | error
);

CREATE INDEX IF NOT EXISTS ci_dispatches_requested_at_idx ON ci_dispatches (requested_at DESC);

-- Run provenance: how it started and what it was asked to run. Older rows stay NULL.
ALTER TABLE ci_runs ADD COLUMN IF NOT EXISTS trigger text;   -- push | pull_request | dispatch | schedule
ALTER TABLE ci_runs ADD COLUMN IF NOT EXISTS suite   text;   -- white | grey | all

-- ci_run_summary gains the two new columns (CREATE OR REPLACE cannot add columns to an
-- existing view, so drop it first — it is a pure rollup, nothing depends on its identity).
DROP VIEW IF EXISTS ci_run_summary;
CREATE VIEW ci_run_summary AS
SELECT r.project, r.run, r.run_number, r.branch, r.sha, r.runner, r.started_at, r.report_url,
       r.trigger, r.suite,
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
GROUP BY r.project, r.run, r.run_number, r.branch, r.sha, r.runner, r.started_at, r.report_url,
         r.trigger, r.suite;

-- Seeds. ON CONFLICT keeps hand edits made from the Run CI/CD page: only the columns that
-- describe the repo/workflow are refreshed, suites/cloud_suites/enabled are left alone once set.
INSERT INTO ci_projects (project, repo, workflow_file, default_branch, report_prefix,
                         suites, runner_labels, cloud_suites)
VALUES
  ('virtualpytest', 'AngelStreetCorp/virtualpytest', 'regression.yml', 'main', '',
   '{"white": ["lint", "frontend-component-tests"],
     "grey":  ["backend-server-tests", "api-routes", "e2e-smoke", "e2e-pages", "e2e-viewport",
               "web-script-local-debug"]}'::jsonb,
   '{self-hosted,Linux,X64}', '{white}')
ON CONFLICT (project) DO UPDATE
  SET repo           = EXCLUDED.repo,
      workflow_file  = EXCLUDED.workflow_file,
      default_branch = EXCLUDED.default_branch,
      report_prefix  = EXCLUDED.report_prefix,
      updated_at     = now();

RESET ROLE;
RESET search_path;

-- Same access pattern as 001: server (service_role) read/write, API roles read. Re-granted
-- here because 001's ALTER DEFAULT PRIVILEGES only covers tables created after it ran.
GRANT SELECT ON ALL TABLES    IN SCHEMA cicd TO anon, authenticated;
GRANT ALL    ON ALL TABLES    IN SCHEMA cicd TO service_role;
-- ci_dispatches.id is a bigserial: service_role needs the sequence to INSERT.
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA cicd TO service_role;
ALTER DEFAULT PRIVILEGES FOR ROLE cicd IN SCHEMA cicd GRANT USAGE, SELECT ON SEQUENCES TO service_role;

NOTIFY pgrst, 'reload schema';
