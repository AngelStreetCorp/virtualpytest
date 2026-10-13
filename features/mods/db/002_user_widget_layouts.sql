-- features/mods/db/002_user_widget_layouts.sql
-- Per-user widget layout of each widget area (TASK-77, docs/agent/platform/MODS.md §Widgets).
--
-- WHY THIS EXISTS
--   Widgets a user places (Dashboard "+ Add widget": which widgets, in which order, with which
--   settings) were kept in the browser only, so they did not follow the user to another
--   computer. One row = one user's layout of one area in one team.
--
-- SHAPE
--   (team_id, user_id, area) is the key. `layout` is the JSON array the app writes:
--   [{"id": "w-…", "widgetId": "team-devices", "settings": {"show": "all"}}, …].
--   Widget ids are the code's WidgetDefinition.id, not foreign keys: widgets are code.
--   The server checks the shape and caps it (50 widgets) before writing.
--
-- WHAT THIS MIGRATION DOES NOT DO
--   No backfill: the app copies a browser layout up the first time it finds no row.
--   Not applied by any deploy script: run it on every database the release reaches.

BEGIN;

CREATE TABLE IF NOT EXISTS public.user_widget_layouts (
    team_id     uuid        NOT NULL REFERENCES public.teams(id) ON DELETE CASCADE,
    user_id     uuid        NOT NULL REFERENCES auth.users(id) ON DELETE CASCADE,
    area        text        NOT NULL CHECK (length(btrim(area)) > 0 AND length(area) <= 50),
    layout      jsonb       NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(layout) = 'array'),
    updated_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (team_id, user_id, area)
);

ALTER TABLE public.user_widget_layouts ENABLE ROW LEVEL SECURITY;

-- The server reads and writes with the service role, filtering by team_id and the caller's
-- user_id in the route; browsers never query this table directly.
DROP POLICY IF EXISTS service_role_all_user_widget_layouts ON public.user_widget_layouts;
CREATE POLICY service_role_all_user_widget_layouts
    ON public.user_widget_layouts
    FOR ALL TO service_role
    USING (true) WITH CHECK (true);

GRANT ALL ON public.user_widget_layouts TO service_role;

COMMIT;
