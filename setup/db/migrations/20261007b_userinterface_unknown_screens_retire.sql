-- 20261007b_userinterface_unknown_screens_retire.sql
-- Stops the unknown-screens table accumulating a fresh copy of every screen on every scan.
--
-- WHY
--   Scans upsert on (team_id, userinterface, cluster_dhash), which correctly prevents a repeat of
--   the SAME screen duplicating a row. It does nothing about rows a later scan no longer sees.
--   The scan window is relative to now, so each run samples a slightly different slice: running it
--   twice produced 356 rows and then 305 more, 661 in total, of which only the latest 305 describe
--   what the device is showing. An operator would see the same screen listed several times and
--   would have to recognise the duplicates by eye — which is exactly the reading task this feature
--   exists to remove.
--
-- WHAT IT ADDS
--   retired_at. A row is live while retired_at IS NULL. The upsert clears it for every screen the
--   scan actually saw, and the same request retires the rest for that interface. Retiring rather
--   than deleting keeps the history — including that a screen was once unknown — and leaves the
--   action untouched, so a mis-retirement is reversible by re-scanning.
--
--   Rows that have never been seen by a scan are not retired, so a partially-applied migration
--   cannot silently empty a table.

BEGIN;

ALTER TABLE public.userinterface_unknown_screens
    ADD COLUMN IF NOT EXISTS retired_at timestamptz;

CREATE INDEX IF NOT EXISTS idx_ui_unknown_live
    ON public.userinterface_unknown_screens (team_id, userinterface)
    WHERE retired_at IS NULL;

-- Live rows only by default. index_pending is the counts path and must agree.
COMMENT ON COLUMN public.userinterface_unknown_screens.retired_at IS
    'Set when a later scan stopped seeing this screen. NULL means the most recent scan saw it. '
    'Rows are retired, never deleted, so the history of what was unknown survives.';

COMMIT;