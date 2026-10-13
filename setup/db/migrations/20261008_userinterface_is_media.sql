-- 20261008_userinterface_is_media.sql
-- Boolean `is_media` metadata on userinterfaces.
--
-- WHY THIS EXISTS
--   A userinterface (e.g. 'brand_a_app', 'streaming_tv_v3', 'switch_home') may
--   or may not be a media surface. A media surface is one where playback state
--   is meaningful — the freeze detector's own moving threshold can call it
--   'playing' on its own; a still picture plus a silent audio window is
--   'paused'. On anything that is NOT a media surface (a home grid, a settings
--   page, a 2048 game) the Tier-2 `playback` arm abstains to 'not_applicable'
--   rather than guessing against a UI whose entire concept is "no video
--   here". Until now the monitor had to pass `is_media=None` to make playback
--   abstain honestly, and so every UI read 'playback=unknown' instead of the
--   sharper answer the surface type allows.
--
-- SHAPE
--   `is_media` is a NULLABLE boolean. NULL = the safe default ("caller
--   abstains, today's behaviour stays in place"). TRUE / FALSE are explicit
--   editorial choices — TRUE marks the UI as a media surface, FALSE marks it
--   as definitively not media. The column is NOT NOT NULL, NOT a foreign key,
--   NOT a constraint: this is one row of metadata an editor flips on/off in
--   the editor, the same way `min_version` / `max_version` / `company` are.
--
-- EXAMPLES
--   TRUE  — a TV channel app, a streaming app, an HDMI-input STB home.
--   FALSE — a settings page, an app grid, a game UI.
--   NULL  — anyone who has not set it (the default for any pre-existing row).
--
-- WHAT THIS MIGRATION DOES NOT DO
--   Does not rename any existing field. Does not enforce a CHECK constraint
--   (NULL / TRUE / FALSE is the entire value domain and the API layer
--   already coerces input). Does not backfill values — NULL is the safe
--   default and any pre-existing inference must run as a separate job.

BEGIN;

ALTER TABLE public.userinterfaces
    ADD COLUMN IF NOT EXISTS is_media boolean;

COMMIT;
