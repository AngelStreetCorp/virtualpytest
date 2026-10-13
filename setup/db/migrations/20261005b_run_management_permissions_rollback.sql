-- 20261005b_run_management_permissions_rollback.sql
-- Inverse of 20261005b_run_management_permissions.sql: takes the four run-management
-- permissions back out of every editable role's defaults. Individual user grants and
-- team ceilings that name them are left alone (an admin set those explicitly).

BEGIN;

UPDATE public.role_permissions r
SET permissions = COALESCE((
        SELECT jsonb_agg(p ORDER BY p)
        FROM jsonb_array_elements_text(r.permissions) AS p
        WHERE p NOT IN ('reports.runs:edit', 'reports.defects:edit',
                        'reports.manual:execute', 'reports.share:create')
    ), '[]'::jsonb),
    updated_at = NOW()
WHERE r.permissions ?| ARRAY['reports.runs:edit', 'reports.defects:edit',
                             'reports.manual:execute', 'reports.share:create'];

COMMIT;
