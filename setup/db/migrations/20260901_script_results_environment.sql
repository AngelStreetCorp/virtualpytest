-- Tag each script execution with the capacity it ran in: dev / test / prod.
--
-- Until now there was no way to tell, from a script_results row, whether a
-- run was a developer's ad-hoc run, a staging/test pass, or a real
-- production execution. testcase_definitions.environment covers DB-authored
-- test cases but nothing equivalent existed for .py scripts run via
-- test_scripts/*.py.
--
-- This is an execution-level concept (mirrors trigger.type provenance),
-- not a script-catalog concept: the same script can run in different
-- capacities depending on who/what triggers it. Untagged runs default to
-- 'prod' — the safe assumption is that an unspecified run is real, so
-- nothing silently drops out of prod KPIs/dashboards.

ALTER TABLE script_results
    ADD COLUMN IF NOT EXISTS environment varchar(10) NOT NULL DEFAULT 'prod';

ALTER TABLE script_results
    ADD CONSTRAINT script_results_environment_check
    CHECK (environment IN ('dev', 'test', 'prod'));

COMMENT ON COLUMN script_results.environment IS
    'Capacity this run was executed in (dev/test/prod). Defaults to prod when unspecified by the caller. Distinct from metadata->trigger, which records who/what triggered the run.';
