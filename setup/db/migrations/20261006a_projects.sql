-- ============================================================================
-- 20261006a_projects.sql
-- TASK-65 — Projects (first-class concept). Phase 1 plan artifact.
--
-- Adds:
--   * projects               — one row per project (id, team_id, name, ...)
--   * projects_tags          — join: project <-> tag(s) it owns
--   * projects_members       — project ACL (owner / viewer)
--   * protect_project_tag     — BEFORE DELETE trigger on tags: blocked if any
--                                projects_tags row references the tag
--   * role_catalog rows      — team:projects:create / view / edit / delete
--
-- Per owner answers (2026-10-06):
--   * Q1 = 1 — tags-backed projects; additive migration
--   * Q4 = 1 — owners + viewers; team admins ALWAYS bypass project ACL
--
-- This file is a BLUEPRINT committed on the task65-projects branch. It is NOT
-- applied yet. The migration is applied in a follow-up commit AFTER this task
-- ships green and gets code review. The data_migrations guard row at the bottom
-- blocks accidental double-apply.
--
-- Idempotent (every CREATE / DROP uses IF [NOT] EXISTS / IF EXISTS).
-- Reuses: public.is_admin() (018_supabase_auth_schema.sql:52-57),
--         public.update_updated_at_column() (existing helper).
-- ============================================================================

BEGIN;

-- ============================================================================
-- 1. projects
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.projects (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    team_id     UUID NOT NULL REFERENCES public.teams(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    description TEXT NULL,
    color       TEXT NULL,
    created_by  UUID NOT NULL REFERENCES public.profiles(id) ON DELETE RESTRICT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT projects_color_is_hex
        CHECK (color IS NULL OR color ~ '^#[0-9A-Fa-f]{6}$'),
    CONSTRAINT projects_name_not_blank
        CHECK (length(btrim(name)) > 0)
);

CREATE INDEX IF NOT EXISTS idx_projects_team_id
    ON public.projects (team_id);
CREATE INDEX IF NOT EXISTS idx_projects_created_by
    ON public.projects (created_by);
CREATE UNIQUE INDEX IF NOT EXISTS idx_projects_team_lower_name
    ON public.projects (team_id, LOWER(name));

DROP TRIGGER IF EXISTS projects_updated_at ON public.projects;
CREATE TRIGGER projects_updated_at
    BEFORE UPDATE ON public.projects
    FOR EACH ROW
    EXECUTE FUNCTION public.handle_updated_at();

COMMENT ON TABLE public.projects IS
    'TASK-65 — A project is a tagged scope of executables (scripts / testcases / '
    'campaigns). Scope is derived from projects_tags -> executable_tags. Team '
    'admins bypass project ACL via public.is_admin(). Phase 1 plan artifact.';
COMMENT ON COLUMN public.projects.color IS
    'Optional hex color for the project chip in the top bar (e.g. "#FFB300").';
COMMENT ON COLUMN public.projects.created_by IS
    'Profile that created the project; the first owner in projects_members.';

-- ============================================================================
-- 2. projects_tags
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.projects_tags (
    project_id UUID NOT NULL REFERENCES public.projects(id) ON DELETE CASCADE,
    tag_id     BIGINT NOT NULL REFERENCES public.tags(tag_id) ON DELETE RESTRICT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (project_id, tag_id)
);

CREATE INDEX IF NOT EXISTS idx_projects_tags_tag
    ON public.projects_tags (tag_id);

COMMENT ON TABLE public.projects_tags IS
    'TASK-65 — Which tag(s) a project owns. The tag is the SAME row in public.tags; '
    'scope comes from executable_tags on the same tag. Phase 1 plan artifact.';

-- ============================================================================
-- 3. projects_members
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.projects_members (
    project_id    UUID NOT NULL REFERENCES public.projects(id) ON DELETE CASCADE,
    team_member_id UUID NOT NULL REFERENCES public.team_members(id) ON DELETE CASCADE,
    role          TEXT NOT NULL CHECK (role IN ('owner', 'viewer')),
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (project_id, team_member_id)
);

CREATE INDEX IF NOT EXISTS idx_projects_members_member
    ON public.projects_members (team_member_id);

COMMENT ON TABLE public.projects_members IS
    'TASK-65 — Project ACL: owner (edit / delete) or viewer (read-only). Team '
    'admins hold edit and delete via public.is_admin() and need not be a row.';
COMMENT ON COLUMN public.projects_members.role IS
    'Project-local role. owner = edit/delete; viewer = read-only. Team admin '
    'role bypasses this via public.is_admin().';

-- ============================================================================
-- 4. Protect project tags from deletion
-- ============================================================================
-- If any projects_tags row references a tag, deletion of the tag must raise.
-- Rename is allowed (it is an UPDATE, not a DELETE).
CREATE OR REPLACE FUNCTION public.protect_project_tag()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF EXISTS (SELECT 1 FROM public.projects_tags pt WHERE pt.tag_id = OLD.tag_id) THEN
        RAISE EXCEPTION 'tag % is used by a project and cannot be deleted', OLD.tag_id
            USING ERRCODE = 'restrict_violation';
    END IF;
    RETURN OLD;
END;
$$;

DROP TRIGGER IF EXISTS protect_project_tag_delete ON public.tags;
CREATE TRIGGER protect_project_tag_delete
    BEFORE DELETE ON public.tags
    FOR EACH ROW
    EXECUTE FUNCTION public.protect_project_tag();

COMMENT ON FUNCTION public.protect_project_tag() IS
    'TASK-65 — Block deletion of a tag that any project references. '
    'Rename is allowed (UPDATE). Phase 1 plan artifact.';

-- ============================================================================
-- 5. RLS
-- ============================================================================
ALTER TABLE public.projects         ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.projects_tags    ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.projects_members ENABLE ROW LEVEL SECURITY;

-- --------------------------------------------------------------------- projects
DROP POLICY IF EXISTS "service_role_all_projects" ON public.projects;
CREATE POLICY "service_role_all_projects" ON public.projects
    FOR ALL TO service_role USING (true) WITH CHECK (true);

-- SELECT: any team member of the project's team can read
DROP POLICY IF EXISTS "team_member_read_projects" ON public.projects;
CREATE POLICY "team_member_read_projects" ON public.projects
    FOR SELECT TO authenticated
    USING (
        EXISTS (
            SELECT 1 FROM public.team_members tm
            WHERE tm.user_id = auth.uid()
              AND tm.team_id = public.projects.team_id
        )
    );

-- INSERT: team members with the team's create permission; created_by must equal self
DROP POLICY IF EXISTS "team_member_insert_projects" ON public.projects;
CREATE POLICY "team_member_insert_projects" ON public.projects
    FOR INSERT TO authenticated
    WITH CHECK (
        EXISTS (
            SELECT 1 FROM public.team_members tm
            JOIN public.role_permissions rp ON rp.role = tm.role
            WHERE tm.user_id = auth.uid()
              AND tm.team_id = public.projects.team_id
              AND rp.permissions ? 'team:projects:create'
        )
        AND created_by = auth.uid()
    );

-- UPDATE: team admins OR project owners
DROP POLICY IF EXISTS "team_admin_or_owner_update_projects" ON public.projects;
CREATE POLICY "team_admin_or_owner_update_projects" ON public.projects
    FOR UPDATE TO authenticated
    USING      (public.is_admin() OR EXISTS (
                    SELECT 1 FROM public.projects_members pm
                    WHERE pm.project_id = public.projects.id
                      AND pm.team_member_id = auth.uid()
                      AND pm.role = 'owner'
                ))
    WITH CHECK (public.is_admin() OR EXISTS (
                    SELECT 1 FROM public.projects_members pm
                    WHERE pm.project_id = public.projects.id
                      AND pm.team_member_id = auth.uid()
                      AND pm.role = 'owner'
                ));

-- DELETE: team admins OR project owners
DROP POLICY IF EXISTS "team_admin_or_owner_delete_projects" ON public.projects;
CREATE POLICY "team_admin_or_owner_delete_projects" ON public.projects
    FOR DELETE TO authenticated
    USING (public.is_admin() OR EXISTS (
                SELECT 1 FROM public.projects_members pm
                WHERE pm.project_id = public.projects.id
                  AND pm.team_member_id = auth.uid()
                  AND pm.role = 'owner'
            ));

REVOKE ALL ON public.projects FROM anon;

-- ----------------------------------------------------------- projects_tags
DROP POLICY IF EXISTS "service_role_all_projects_tags" ON public.projects_tags;
CREATE POLICY "service_role_all_projects_tags" ON public.projects_tags
    FOR ALL TO service_role USING (true) WITH CHECK (true);

-- SELECT: any team member of the project's team can read
DROP POLICY IF EXISTS "team_member_read_projects_tags" ON public.projects_tags;
CREATE POLICY "team_member_read_projects_tags" ON public.projects_tags
    FOR SELECT TO authenticated
    USING (
        EXISTS (
            SELECT 1 FROM public.projects p
            JOIN public.team_members tm
              ON tm.user_id = auth.uid() AND tm.team_id = p.team_id
            WHERE p.id = public.projects_tags.project_id
        )
    );

-- WRITE: team admins OR project owners of the referenced project
DROP POLICY IF EXISTS "team_admin_or_owner_write_projects_tags" ON public.projects_tags;
CREATE POLICY "team_admin_or_owner_write_projects_tags" ON public.projects_tags
    FOR ALL TO authenticated
    USING      (public.is_admin() OR EXISTS (
                    SELECT 1 FROM public.projects p
                    JOIN public.projects_members pm
                      ON pm.project_id = p.id
                         AND pm.team_member_id = auth.uid()
                         AND pm.role = 'owner'
                    WHERE p.id = public.projects_tags.project_id
                ))
    WITH CHECK (public.is_admin() OR EXISTS (
                    SELECT 1 FROM public.projects p
                    JOIN public.projects_members pm
                      ON pm.project_id = p.id
                         AND pm.team_member_id = auth.uid()
                         AND pm.role = 'owner'
                    WHERE p.id = public.projects_tags.project_id
                ));

REVOKE ALL ON public.projects_tags FROM anon;

-- ----------------------------------------------------------- projects_members
DROP POLICY IF EXISTS "service_role_all_projects_members" ON public.projects_members;
CREATE POLICY "service_role_all_projects_members" ON public.projects_members
    FOR ALL TO service_role USING (true) WITH CHECK (true);

-- SELECT: any team member of the project's team can read
DROP POLICY IF EXISTS "team_member_read_projects_members" ON public.projects_members;
CREATE POLICY "team_member_read_projects_members" ON public.projects_members
    FOR SELECT TO authenticated
    USING (
        EXISTS (
            SELECT 1 FROM public.projects p
            JOIN public.team_members tm
              ON tm.user_id = auth.uid() AND tm.team_id = p.team_id
            WHERE p.id = public.projects_members.project_id
        )
    );

-- WRITE: team admins OR project owners
DROP POLICY IF EXISTS "team_admin_or_owner_write_projects_members" ON public.projects_members;
CREATE POLICY "team_admin_or_owner_write_projects_members" ON public.projects_members
    FOR ALL TO authenticated
    USING      (public.is_admin() OR EXISTS (
                    SELECT 1 FROM public.projects p
                    JOIN public.projects_members pm
                      ON pm.project_id = p.id
                         AND pm.team_member_id = auth.uid()
                         AND pm.role = 'owner'
                    WHERE p.id = public.projects_members.project_id
                ))
    WITH CHECK (public.is_admin() OR EXISTS (
                    SELECT 1 FROM public.projects p
                    JOIN public.projects_members pm
                      ON pm.project_id = p.id
                         AND pm.team_member_id = auth.uid()
                         AND pm.role = 'owner'
                    WHERE p.id = public.projects_members.project_id
                ));

REVOKE ALL ON public.projects_members FROM anon;

-- ============================================================================
-- 6. Default grants — appended only when not present (idempotent).
-- Permissions are stored as a JSONB array on public.role_permissions; we union
-- the new project permissions into the existing list.
-- Admin already holds everything via profiles.role = 'admin' / is_admin().
-- ============================================================================

-- manager + developer + tester: create / view / edit / delete
UPDATE public.role_permissions rp
SET permissions = (
        SELECT COALESCE(jsonb_agg(DISTINCT v.value ORDER BY v.value), '[]'::jsonb)
        FROM jsonb_array_elements(rp.permissions || '["team:projects:create","team:projects:view","team:projects:edit","team:projects:delete"]'::jsonb) AS v(value)
    ),
    updated_at = NOW()
WHERE rp.role IN ('manager', 'developer', 'tester')
  AND NOT (rp.permissions ? 'team:projects:create');

-- viewer: view only
UPDATE public.role_permissions rp
SET permissions = (
        SELECT COALESCE(jsonb_agg(DISTINCT v.value ORDER BY v.value), '[]'::jsonb)
        FROM jsonb_array_elements(rp.permissions || '["team:projects:view"]'::jsonb) AS v(value)
    ),
    updated_at = NOW()
WHERE rp.role = 'viewer'
  AND NOT (rp.permissions ? 'team:projects:view');

-- ============================================================================
-- 7. data_migrations guard row — applied only when explicitly desired.
-- The Phase 1 plan says "do not apply". The guard row below is commented out
-- so the migration does NOT show as applied even if the file is run by a
-- tooling mistake. To apply the file, follow the Phase 2 commit instructions
-- in docs/tasks/TASK-65-projects.md §G8.
-- ============================================================================
-- INSERT INTO public.data_migrations (name) VALUES ('20261006a_projects')
-- ON CONFLICT (name) DO NOTHING;

COMMIT;