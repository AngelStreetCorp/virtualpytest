-- 20261016a_match_runs.sql
-- One row per matcher run: every verify, every localize button press, every
-- monitor settle, every localize_check.  The matcher history the operator
-- never had — until now.
--
-- WHY THIS TABLE
--   The matcher is called from four places (verify_node, the Localize button,
--   the monitor's per-frame localize, and the post-verify localize_check) and
--   NONE of them wrote a row.  Operators could only see the verdict on the
--   one frame the API returned.  When a verification failed, there was no
--   way to ask "what was the runner-up?" or "was this the same screen as
--   yesterday's failure on the same device?".
--
--   match_runs answers that.  Every run lands here with its top-3 candidates
--   (when the winner cleared the confidence floor), the chain to the previous
--   event on the same device, and the dhash of the frame.
--
-- WHY top-3 AND A JSONB MIRROR
--   SQL-friendly analytics ("WHERE candidate_2_node_id = X AND runner_up_margin < 0.05")
--   needs columns.  The "show me the breakdown" view wants an array.  Both: the
--   six dedicated columns for the dashboard / Grafana / a11y queries, and the
--   candidates_top_3 JSONB for the "explain this single failure" view.
--
-- WHY the floor
--   Under 80% the matcher is guessing.  Storing a tail of weak candidates
--   pollutes the table and never gets read.  At >= 80% the runner-up is a
--   real second opinion worth comparing.
--
-- WHY a chain (previous_event_id, previous_node_id, session_id, step_in_session)
--   A device visits nodes in a sequence.  If we record that sequence, "what
--   comes after node X?" is a query, and that query is the prediction signal.
--   The chain is per (device_id, userinterface_name) — a TV's "home" is a
--   different sequence from the same model's "settings".
--
-- UNIQUE is intentionally absent.  Every run gets its own row.

BEGIN;

CREATE TABLE IF NOT EXISTS public.match_runs (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),

    -- Identity / context: who ran, on what, where.
    team_id             uuid NOT NULL REFERENCES public.teams(id) ON DELETE CASCADE,
    server_id           text,
    host_name           text NOT NULL,
    device_id           text,
    device_name         text,
    device_model        text,
    userinterface_name  text NOT NULL,
    tree_id             uuid,
    variant             text,

    -- What called the matcher.  Lets the dashboard separate "operator pressed
    -- Localize" from "monitor ran in the background" without two tables.
    source              text NOT NULL
                        CHECK (source IN ('verify', 'localize_button', 'monitor_localize',
                                          'localize_check', 'nightwatch')),
    source_ref          jsonb,

    -- Timing.
    started_at          timestamptz NOT NULL,
    completed_at        timestamptz,
    elapsed_ms          integer,

    -- Match result.  verdict = 'known_node' is the only one that should write
    -- to a tree's node_metrics; everything else is the matcher abstaining.
    verdict             text NOT NULL
                        CHECK (verdict IN ('known_node', 'unknown', 'no_signal',
                                            'low_confidence', 'overlay', 'live')),
    matched_node_id     uuid,
    matched_confidence  real,
    runner_up_margin    real,
    candidates_top_3    jsonb NOT NULL DEFAULT '[]'::jsonb,
    candidate_threshold real NOT NULL DEFAULT 0.80,
    candidate_floor_hit boolean NOT NULL,

    -- Frame fingerprint, for cross-host dedupe and "have I seen this exact
    -- image before?" queries.
    dhash               bigint,
    frame_url           text,

    -- Sequence chain.  previous_event_id is a self-FK so a chain is
    -- walkable in SQL with a recursive CTE; previous_node_id is denormalised
    -- so the GROUP BY in v_node_transitions is one index lookup, not a join.
    previous_event_id   uuid REFERENCES public.match_runs(id) ON DELETE SET NULL,
    previous_node_id    uuid,
    step_in_session     integer,
    session_id          uuid,

    created_at          timestamptz NOT NULL DEFAULT now()
);

-- The hot indexes.  "Last 20 events on this device" is the most common query
-- (sequence replay); "all hits on this node today" is the second.  Both are
-- composite so the planner can stop on the leading column.
CREATE INDEX IF NOT EXISTS idx_match_runs_team_device_ts
    ON public.match_runs (team_id, device_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_match_runs_team_ui_ts
    ON public.match_runs (team_id, userinterface_name, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_match_runs_team_node_ts
    ON public.match_runs (team_id, matched_node_id, started_at DESC)
    WHERE matched_node_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_match_runs_team_dhash
    ON public.match_runs (team_id, dhash)
    WHERE dhash IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_match_runs_team_prev
    ON public.match_runs (team_id, previous_node_id)
    WHERE previous_node_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_match_runs_team_source_ts
    ON public.match_runs (team_id, source, started_at DESC);

-- updated_at maintenance: this table is INSERT-only by design (every run
-- gets a new row, never updated), but the trigger keeps created_at
-- consistent with the rest of the schema.
DROP TRIGGER IF EXISTS trg_match_runs_updated_at ON public.match_runs;
-- (No trigger — INSERT-only, no updated_at column.  Documented here so a
-- future reader does not "fix" the missing trigger.)


-- ---------------------------------------------------------------------------
-- Derived views.  These are the prediction / dashboard inputs.
-- ---------------------------------------------------------------------------

-- v_node_transitions: P(to_node | from_node, userinterface).  The matrix an
-- agent reads to ask "where am I likely going next?".
CREATE OR REPLACE VIEW public.v_node_transitions AS
SELECT
    team_id,
    userinterface_name,
    previous_node_id AS from_node_id,
    matched_node_id  AS to_node_id,
    COUNT(*) AS occurrences,
    COUNT(*) FILTER (WHERE runner_up_margin < 0.05) AS uncertain_occurrences,
    MAX(started_at) AS last_seen_at
FROM public.match_runs
WHERE matched_node_id IS NOT NULL
  AND previous_node_id IS NOT NULL
  AND previous_node_id <> matched_node_id
GROUP BY team_id, userinterface_name, previous_node_id, matched_node_id;

-- v_uncertain_hits: the cases the matcher said "yes" but barely.  This is
-- the backlog for the operator — fingerprint more of these or add a sample.
CREATE OR REPLACE VIEW public.v_uncertain_hits AS
SELECT *
FROM public.match_runs
WHERE runner_up_margin < 0.05
  AND matched_node_id IS NOT NULL
  AND candidate_floor_hit = true;

-- v_recent_sequence: the last 20 events for each device, in order.  Lets a
-- viewer replay what just happened — useful when a verify fails and the
-- operator wants to know what the device was doing in the run-up.
CREATE OR REPLACE VIEW public.v_recent_sequence AS
SELECT *
FROM (
    SELECT *,
           ROW_NUMBER() OVER (PARTITION BY team_id, device_id ORDER BY started_at DESC) AS rn
    FROM public.match_runs
) t
WHERE rn <= 20;


-- ---------------------------------------------------------------------------
-- RLS — service_role only, mirroring the posture set by
-- 20260908b_close_app_tables_to_public_key.sql and 20261014e_localize_verdicts.
-- The host writes, the server reads, the operator never sees another team's
-- rows, and a role with no policy sees nothing.
-- ---------------------------------------------------------------------------
ALTER TABLE public.match_runs ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS service_role_all_match_runs ON public.match_runs;
CREATE POLICY service_role_all_match_runs
    ON public.match_runs
    FOR ALL TO service_role
    USING (true) WITH CHECK (true);

REVOKE ALL ON public.match_runs FROM anon, authenticated;
GRANT ALL ON public.match_runs TO service_role;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO service_role;

COMMIT;
