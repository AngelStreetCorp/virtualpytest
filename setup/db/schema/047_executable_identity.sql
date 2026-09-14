-- 047 — Executable identity: the TCnnn prefix and display name shown for a
-- script / testcase / virtual script, stored per team instead of in a file.
--
-- Replaces the hand-edited pair test_scripts/script_identity_map.json (read by
-- the server for report naming) + frontend/public/data/script_identity_map.json
-- (the only copy the browser read). Two files with different owners is what
-- BUG-0066 was; this table is the single source of truth, editable from the
-- Test Cases page. The JSON files remain a read-only fallback for one release.
--
-- script_ref is normalize_script_ref() output — the SAME namespace as
-- script_results.script_name, which is what keeps report labelling working:
--   disk script     'gw/superping'
--   virtual script  'superping'      (convert names a VS by basename)
--   testcase        the testcase name
-- All three are kind='script'. kind='campaign' is reserved for
-- campaign_identity_map.json so it needs no second migration.
--
-- See docs/agent/execution/SCRIPTS_AND_CAMPAIGNS.md, test_scripts/script_identity.md.

DROP TABLE IF EXISTS public.executable_identity CASCADE;
DROP FUNCTION IF EXISTS public.update_executable_identity_updated_at() CASCADE;

CREATE TABLE public.executable_identity (
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

CREATE INDEX idx_executable_identity_team_kind
    ON public.executable_identity(team_id, kind);

-- Advisory only: a duplicate prefix is reported as a warning by the API, never
-- rejected, so importing an existing map can never fail half way through.
CREATE INDEX idx_executable_identity_prefix
    ON public.executable_identity(team_id, kind, prefix);

CREATE OR REPLACE FUNCTION public.update_executable_identity_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SET search_path = public, auth, extensions;

CREATE TRIGGER executable_identity_updated_at
    BEFORE UPDATE ON public.executable_identity
    FOR EACH ROW EXECUTE FUNCTION public.update_executable_identity_updated_at();

COMMENT ON TABLE public.executable_identity IS
    'Team-scoped prefix/display_name for executables. kind=script covers disk scripts, virtual scripts and testcases (one namespace = script_results.script_name); kind=campaign reserved for campaign identity.';
COMMENT ON COLUMN public.executable_identity.script_ref IS
    'normalize_script_ref() output: "gw/superping", a virtual-script name, or a testcase_name. No "test_scripts/" prefix, no ".py".';
COMMENT ON COLUMN public.executable_identity.prefix IS
    'Business identifier shown as a chip, e.g. TC021. Not unique by design.';

-- Post-TASK-10 convention: RLS on, service_role only, app keys revoked.
ALTER TABLE public.executable_identity ENABLE ROW LEVEL SECURITY;
CREATE POLICY "service_role_all_executable_identity" ON public.executable_identity
    FOR ALL TO service_role USING (true) WITH CHECK (true);
REVOKE ALL ON public.executable_identity FROM anon, authenticated;
