-- 20261017a_match_runs_profile.sql
-- Add `profile` to match_runs so the queue worker can tag writes with the
-- matcher profile that produced them.
--
-- WHY
--   The match_runs table (20261016a) is fed from four sources: verify,
--   localize_button, monitor_localize, localize_check, nightwatch.  The
--   monitor path runs vpt-monitor-img (BUG-0565 follow-up), which is
--   profile-driven — the same host can run tv_app on a set-top box and
--   pc on a desktop, and the two flows are not comparable.  Without a
--   profile column the dashboard cannot separate them, and the
--   "10 rows/sec from one host" the queue is throttling becomes
--   10 rows/sec of mixed data the operator cannot interpret.
--
-- WHY TEXT, NOT ENUM
--   Profiles are added in the field (counting_cars, ad_meter, ...).  A
--   CHECK constraint would force a migration on every new profile; a
--   plain text column is profile-agnostic.  Validate on the writer side.
--
-- WHY A PARTIAL INDEX
--   The dashboard's "monitor activity by profile" view is the only
--   thing that filters by profile.  Most queries (recent runs,
--   transitions) ignore the column.  A partial index keyed on the
--   monitor_localize source keeps the dashboard fast without paying
--   for an index nobody else reads.

BEGIN;

ALTER TABLE public.match_runs
    ADD COLUMN IF NOT EXISTS profile text;

COMMENT ON COLUMN public.match_runs.profile IS
    'Matcher profile that produced this run (tv_app, pc, drone, ...).  '
    'NULL for non-monitor sources (verify, localize_button, localize_check).  '
    'Source-of-truth: shared/src/lib/utils/monitor_profile.py resolve_monitor_profile().';

CREATE INDEX IF NOT EXISTS idx_match_runs_team_profile_ts
    ON public.match_runs (team_id, profile, started_at DESC)
    WHERE profile IS NOT NULL;

COMMIT;
