-- 20261018a_match_runs_dedupe_index.sql
-- Dedupe (team_id, profile, started_at) on match_runs so a vpt-host restart
-- mid-batch cannot double-write the same monitor row.
--
-- WHY
--   The queue worker (vpt-match-runs-writer, BUG-0565) is the single
--   writer, but the host-side `_enqueue_match_run` (monitor_localize.py)
--   is the producer.  A host restart between BRPOP and the next LPUSH
--   can leave a payload in flight twice — the worker processes it
--   once, the host's retry loop re-pushes the same payload, the worker
--   processes it again.  Same row twice in match_runs.
--
-- WHY A UNIQUE INDEX
--   The dedupe needs to be in the database because the writer and the
--   producer are separate processes — there is no shared in-memory
--   state to consult.  The match_runs table already carries a UUID
--   primary key, but the producer does not know the UUID when it
--   pushes; the unique constraint on (team_id, profile, started_at)
--   catches the duplicate by content rather than by id.
--
-- WHY A PARTIAL INDEX ON profile IS NOT NULL
--   The verify / localize_button / localize_check sources do not use
--   the profile column — their dedupe key is (team_id, host_name,
--   source, started_at) which is broader and would force every
--   verify write to consult the index.  A partial index keeps the
--   monitor_localize path safe (the only path that has the
--   double-write risk today) without slowing the others.
--
-- ROLLBACK
--   DROP INDEX IF EXISTS public.idx_match_runs_team_profile_ts_unique;

BEGIN;

CREATE UNIQUE INDEX IF NOT EXISTS idx_match_runs_team_profile_ts_unique
    ON public.match_runs (team_id, profile, started_at)
    WHERE profile IS NOT NULL;

COMMENT ON INDEX public.idx_match_runs_team_profile_ts_unique IS
    'Dedupe monitor_localize writes that the vpt-host may push twice on '
    'restart.  A duplicate triggers a 23505 (unique_violation) on insert; '
    'the worker logs and skips.  The verify / localize_button sources '
    'are out of scope (profile is NULL for them, so the index ignores them).';

COMMIT;
