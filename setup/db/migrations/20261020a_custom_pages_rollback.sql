-- Rollback of 20261020a_custom_pages.sql: drops both tables (all saved pages are lost) and the two role permissions.
BEGIN;
DROP TABLE IF EXISTS public.custom_page_shares;
DROP TABLE IF EXISTS public.custom_pages;
UPDATE public.role_permissions r
SET permissions = COALESCE((
        SELECT jsonb_agg(p ORDER BY p)
        FROM jsonb_array_elements_text(r.permissions) AS p
        WHERE p NOT IN ('pages.custom:view', 'pages.custom:edit')
    ), '[]'::jsonb),
    updated_at = NOW()
WHERE r.role IN ('manager', 'developer', 'tester', 'viewer');
COMMIT;
