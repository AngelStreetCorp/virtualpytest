-- 2026-09-08: the virtualpytest api-smoke job became api-routes (every GET route the
-- server registers, discovered at run time — see test_scripts/api/run_api_tests.md).
-- ci_projects.suites is seeded once (002) and then owned by the Run CI/CD page, so the
-- rename must be applied to the live row too. Old ci_jobs rows keep their historic name.
UPDATE ci_projects
SET suites = jsonb_set(
    suites, '{grey}',
    (SELECT jsonb_agg(CASE WHEN j = '"api-smoke"'::jsonb THEN '"api-routes"'::jsonb ELSE j END)
       FROM jsonb_array_elements(suites->'grey') j)
)
WHERE project = 'virtualpytest' AND suites->'grey' ? 'api-smoke';
