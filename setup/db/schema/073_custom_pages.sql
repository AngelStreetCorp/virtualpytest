-- 073 — custom pages (TASK-139). Same content as migration 20261020a_custom_pages.sql.
-- Idempotent. Rollback: 20261020a_custom_pages_rollback.sql. Requires 20260929c_role_catalog.sql.

BEGIN;

-- custom_pages: a saved page = a versioned JSON definition of catalogue blocks. Never code.
-- status 'draft' (Atlas built it, only the owner sees it until Save) | 'saved'.
-- visibility 'private' (owner + custom_page_shares) | 'team' (every member of team_id can view).
CREATE TABLE IF NOT EXISTS public.custom_pages (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    team_id        UUID NOT NULL REFERENCES public.teams(id) ON DELETE CASCADE,
    owner_id       TEXT NOT NULL CHECK (length(owner_id) BETWEEN 1 AND 200),
    title          TEXT NOT NULL CHECK (length(btrim(title)) BETWEEN 1 AND 120),
    schema_version INTEGER NOT NULL CHECK (schema_version >= 1),
    definition     JSONB NOT NULL CHECK (jsonb_typeof(definition) = 'object'),
    status         TEXT NOT NULL DEFAULT 'saved' CHECK (status IN ('draft', 'saved')),
    visibility     TEXT NOT NULL DEFAULT 'private' CHECK (visibility IN ('private', 'team')),
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE public.custom_pages IS
    'TASK-139 custom pages: definition is revalidated against the block catalogue on save and on load.';

CREATE INDEX IF NOT EXISTS custom_pages_team_owner_idx
    ON public.custom_pages (team_id, owner_id, updated_at DESC);

-- custom_page_shares: one row = one named user a private page is shared with (view or edit).
CREATE TABLE IF NOT EXISTS public.custom_page_shares (
    page_id    UUID NOT NULL REFERENCES public.custom_pages(id) ON DELETE CASCADE,
    team_id    UUID NOT NULL REFERENCES public.teams(id) ON DELETE CASCADE,
    user_id    TEXT NOT NULL CHECK (length(user_id) BETWEEN 1 AND 200),
    can_edit   BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (page_id, user_id)
);

CREATE INDEX IF NOT EXISTS custom_page_shares_user_idx
    ON public.custom_page_shares (team_id, user_id);

ALTER TABLE public.custom_pages       ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.custom_page_shares ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "service_role_all_custom_pages" ON public.custom_pages;
CREATE POLICY "service_role_all_custom_pages" ON public.custom_pages FOR ALL TO service_role USING (true) WITH CHECK (true);
DROP POLICY IF EXISTS "service_role_all_custom_page_shares" ON public.custom_page_shares;
CREATE POLICY "service_role_all_custom_page_shares" ON public.custom_page_shares FOR ALL TO service_role USING (true) WITH CHECK (true);
REVOKE ALL ON public.custom_pages       FROM anon, authenticated;
REVOKE ALL ON public.custom_page_shares FROM anon, authenticated;

-- Role defaults. pages.custom:view -> every role (opening a page is open; each block still needs
-- its own permission). pages.custom:edit -> manager, developer, tester (admin holds everything,
-- viewer is blocked from writes by the global read-only floor anyway).
-- Adds only what a row lacks, never removes. Teams with an explicit ceiling (teams.permissions)
-- keep it until an admin adds the two permissions on the Teams page.
UPDATE public.role_permissions r
SET permissions = (
        SELECT jsonb_agg(DISTINCT p ORDER BY p)
        FROM (
            SELECT jsonb_array_elements_text(r.permissions) AS p
            UNION
            SELECT unnest(CASE r.role
                WHEN 'manager'   THEN ARRAY['pages.custom:view', 'pages.custom:edit']
                WHEN 'developer' THEN ARRAY['pages.custom:view', 'pages.custom:edit']
                WHEN 'tester'    THEN ARRAY['pages.custom:view', 'pages.custom:edit']
                WHEN 'viewer'    THEN ARRAY['pages.custom:view']
            END)
        ) AS merged
    ),
    updated_at = NOW()
WHERE r.role IN ('manager', 'developer', 'tester', 'viewer');

COMMIT;
