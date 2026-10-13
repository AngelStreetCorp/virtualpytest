-- 20261004b_report_snapshots_rollback.sql — inverse of 20261004b_report_snapshots.sql.
-- Drops the report_snapshots table and removes "reports.tests:share" from the
-- default permissions of tester, developer and manager.

BEGIN;

DROP TABLE IF EXISTS public.report_snapshots;

UPDATE public.role_permissions rp
SET permissions = (
    SELECT COALESCE(jsonb_agg(v.value ORDER BY v.value), '[]'::jsonb)
    FROM jsonb_array_elements(rp.permissions) AS v(value)
    WHERE v.value <> '"reports.tests:share"'::jsonb
)
WHERE rp.role IN ('tester', 'developer', 'manager')
  AND rp.permissions ? 'reports.tests:share';

COMMIT;
