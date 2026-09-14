-- 20260914_executable_identity.sql
-- Move the TCnnn prefix / display name out of the hand-edited
-- script_identity_map.json pair and into the DB, editable from the Test Cases
-- page. Canonical definition: setup/db/schema/047_executable_identity.sql.
-- Idempotent: safe to re-run.

BEGIN;

CREATE TABLE IF NOT EXISTS public.executable_identity (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    team_id      UUID NOT NULL REFERENCES public.teams(id) ON DELETE CASCADE,
    kind         VARCHAR(32) NOT NULL DEFAULT 'script',
    script_ref   TEXT NOT NULL,
    prefix       VARCHAR(32),
    display_name VARCHAR(255),
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_by   VARCHAR(255),

    CONSTRAINT executable_identity_kind_check
        CHECK (kind IN ('script', 'campaign')),
    CONSTRAINT executable_identity_ref_not_blank
        CHECK (length(btrim(script_ref)) > 0),
    CONSTRAINT unique_executable_identity_per_team
        UNIQUE (team_id, kind, script_ref)
);

CREATE INDEX IF NOT EXISTS idx_executable_identity_team_kind
    ON public.executable_identity(team_id, kind);
CREATE INDEX IF NOT EXISTS idx_executable_identity_prefix
    ON public.executable_identity(team_id, kind, prefix);

CREATE OR REPLACE FUNCTION public.update_executable_identity_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SET search_path = public, auth, extensions;

DROP TRIGGER IF EXISTS executable_identity_updated_at ON public.executable_identity;
CREATE TRIGGER executable_identity_updated_at
    BEFORE UPDATE ON public.executable_identity
    FOR EACH ROW EXECUTE FUNCTION public.update_executable_identity_updated_at();

COMMENT ON TABLE public.executable_identity IS
    'Team-scoped prefix/display_name for executables. kind=script covers disk scripts, virtual scripts and testcases (one namespace = script_results.script_name); kind=campaign reserved for campaign identity.';
COMMENT ON COLUMN public.executable_identity.script_ref IS
    'normalize_script_ref() output: "gw/superping", a virtual-script name, or a testcase_name. No "test_scripts/" prefix, no ".py".';

ALTER TABLE public.executable_identity ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "service_role_all_executable_identity" ON public.executable_identity;
CREATE POLICY "service_role_all_executable_identity" ON public.executable_identity
    FOR ALL TO service_role USING (true) WITH CHECK (true);
REVOKE ALL ON public.executable_identity FROM anon, authenticated;

COMMIT;
