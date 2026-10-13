-- features/mods/db/001_user_mod_preferences.sql
-- Per-user on/off choice for each mod (TASK-77, docs/agent/platform/MODS.md).
--
-- WHY THIS EXISTS
--   Settings > Mods lets each user switch each mod on or off, like browser extensions.
--   The choice used to live in the browser only (localStorage), so it did not follow a user
--   to another computer. One row = one explicit choice; a mod with no row follows its own
--   `defaultEnabled` in the code, so adding a mod needs no data change.
--
-- SHAPE
--   (team_id, user_id, mod_id) is the key: a user in two teams can choose differently per
--   team. `mod_id` is the code's ModDefinition.id ('run-progress', 'blast-radius', ...),
--   plain text, not a foreign key: mods are code, not rows.
--
-- WHAT THIS MIGRATION DOES NOT DO
--   No backfill (browser choices are copied up by the app the first time it loads the
--   server choices, see useEnabledMods). Not applied by any deploy script: run it on every
--   database the release reaches (docs/technical/FEATURES.md, Rules).

BEGIN;

CREATE TABLE IF NOT EXISTS public.user_mod_preferences (
    team_id     uuid        NOT NULL REFERENCES public.teams(id) ON DELETE CASCADE,
    user_id     uuid        NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    mod_id      text        NOT NULL CHECK (length(btrim(mod_id)) > 0 AND length(mod_id) <= 100),
    enabled     boolean     NOT NULL,
    updated_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (team_id, user_id, mod_id)
);

ALTER TABLE public.user_mod_preferences ENABLE ROW LEVEL SECURITY;

-- The server reads and writes with the service role, filtering by team_id and the caller's
-- user_id in the route; browsers never query this table directly.
DROP POLICY IF EXISTS service_role_all_user_mod_preferences ON public.user_mod_preferences;
CREATE POLICY service_role_all_user_mod_preferences
    ON public.user_mod_preferences
    FOR ALL TO service_role
    USING (true) WITH CHECK (true);

GRANT ALL ON public.user_mod_preferences TO service_role;

COMMIT;
