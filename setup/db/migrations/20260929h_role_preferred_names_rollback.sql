-- 20260929h_role_preferred_names_rollback.sql
-- Inverse of 20260929h_role_preferred_names.sql: recreates the (empty) per-provider alias table
-- of 20260929c and drops the unique preferred-name index. Deploy the matching older code with it.

BEGIN;

DROP INDEX IF EXISTS public.roles_display_name_key;

CREATE TABLE IF NOT EXISTS public.role_aliases (
    provider_type TEXT NOT NULL,
    external_name TEXT NOT NULL,
    role          TEXT NOT NULL REFERENCES public.roles(role) ON DELETE CASCADE,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT role_aliases_provider_not_blank CHECK (length(btrim(provider_type)) > 0),
    CONSTRAINT role_aliases_name_not_blank     CHECK (length(btrim(external_name)) > 0)
);
CREATE UNIQUE INDEX IF NOT EXISTS role_aliases_provider_name_key
    ON public.role_aliases (lower(provider_type), lower(external_name));
ALTER TABLE public.role_aliases ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "service_role_all_role_aliases" ON public.role_aliases;
CREATE POLICY "service_role_all_role_aliases" ON public.role_aliases
    FOR ALL TO service_role USING (true) WITH CHECK (true);
REVOKE ALL ON public.role_aliases FROM anon, authenticated;

COMMIT;

NOTIFY pgrst, 'reload schema';
