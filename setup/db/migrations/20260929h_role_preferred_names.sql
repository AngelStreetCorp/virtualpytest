-- 20260929h_role_preferred_names.sql
-- TASK-31 — one preferred name per role, no per-provider mapping.
--
-- Each role has a single preferred name (roles.display_name), shown everywhere in the app. An
-- external platform sends that same name when it creates or updates a user ("SuperAdmin"
-- -> admin); the user API also accepts the role id. The installation serves one tenant, so a
-- per-provider alias table (role_aliases, 20260929c) is not needed and is dropped.
--
-- Preferred names are unique, ignoring case and surrounding spaces, so a name maps to one role.
-- Canonical twin: setup/db/schema/053_role_catalog.sql. Idempotent.
-- Inverse: 20260929h_role_preferred_names_rollback.sql.

BEGIN;

DROP TABLE IF EXISTS public.role_aliases;

CREATE UNIQUE INDEX IF NOT EXISTS roles_display_name_key
    ON public.roles (lower(btrim(display_name)));

COMMENT ON TABLE public.roles IS
    'System roles and the preferred name this installation shows and accepts for each. Role ids '
    'are fixed; the rank between them lives in code (auth_middleware.ROLE_RANK).';

COMMIT;

NOTIFY pgrst, 'reload schema';
