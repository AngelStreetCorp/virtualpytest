-- 20261007a_userinterface_unknown_screens.sql
-- Storage for screens a device shows that have no node in its navigation tree.
--
-- WHY THIS EXISTS
--   The localizer abstains whenever nothing in the tree fingerprints strongly enough. Measured over
--   4,507 processed cold frames, 2,029 abstentions reduced to just 15 distinct screens -- 11 of them
--   broadcast or game footage, which is content, not an unrecognised UI. The other 4 are the whole
--   feature surface: an operator task, not a modelling problem.
--
--   Until now that signal had nowhere to land. It was visible only in offline histograms, so it was
--   re-measured by hand every session. This table is where a scan writes its findings and the
--   unknown-screens page reads them.
--
-- WHAT IS NEVER AUTOMATICALLY ACTIONED
--   Nothing here mutates the navigation tree on its own. status stays 'pending' until a human
--   accepts a row. A provisional node that entered the tree unconfirmed would become a navigation
--   target for agents, and an agent would then be sent to whatever a half-named screen turned out
--   to be.
--
-- classification vs status
--   classification = 'unknown'  the operator may want to name this one
--                   'content'  broadcast / game footage, filtered out of the list but kept visible
--                              so the filter can be audited rather than silently trusted
--   status applies to 'unknown' rows only and records the human decision.
--
-- UNIQUE is on (team_id, userinterface, cluster_dhash) because a re-scan of the same screen must
-- update the existing row rather than accumulate duplicates every night.

BEGIN;

CREATE TABLE IF NOT EXISTS public.userinterface_unknown_screens (
    id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    team_id          uuid NOT NULL REFERENCES public.teams(id) ON DELETE CASCADE,

    -- The interface that showed the screen. A plain name, matching the
    -- userinterface_name convention used across the existing routes.
    userinterface    text NOT NULL,

    -- Device the frames came from. Carried so "a different device with no tree at all" stays
    -- distinguishable from "this device showed a screen we have not named yet" -- those need
    -- different actions (create a UI vs. add a node).
    device_model     text,

    -- Production dhash64 hex of the cluster centre. Same fingerprint the matcher uses, so a row
    -- here is directly comparable with what localize() would compute on a live frame.
    cluster_dhash    text NOT NULL,

    classification   text NOT NULL DEFAULT 'unknown'
                     CHECK (classification IN ('unknown', 'content')),
    status           text NOT NULL DEFAULT 'pending'
                     CHECK (status IN ('pending', 'accepted', 'dismissed', 'merged')),

    -- Name proposal, editable in the UI before accepting. Populated by the existing vision.dom
    -- path; the operator's edit always wins.
    proposed_name    text,
    screen_type      text,

    frame_count      integer NOT NULL DEFAULT 1 CHECK (frame_count >= 0),
    -- Human-readable reason this surfaced ("overlays a known screen", "not dimmed -- today's
    -- detector misses it"). Kept as text because it is a report, not a filter input.
    signal           text,
    -- For a content row, what the footage actually is ("live TV programme", "broadcast promo
    -- slate"). Content rows are shown to the operator so the filter can be audited; without a
    -- description they are an unauditable list of thumbnails.
    description      text,

    -- Representative still and a few examples, so the row is inspectable without re-reading the
    -- host archive. object_key style paths into the training bucket.
    image_url        text,
    example_frames   text[],

    -- The fingerprint, computed once by the scan on the host that holds the frame
    -- (ImageHelpers.compute_fingerprint). Storing it is what makes Accept a server-side operation:
    -- creating the node needs a fingerprint, and re-deriving it later would mean re-fetching an
    -- image the archive may already have rotated.
    fingerprint      jsonb,
    -- vision.dom output when the scan asked for a name. proposed_name is seeded from it.
    dom              jsonb,

    -- Set when accepted: the node that was created, or the node this was merged into.
    accepted_node_id text,

    first_seen_at    timestamptz NOT NULL DEFAULT now(),
    last_scan_at     timestamptz NOT NULL DEFAULT now(),
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now(),

    CONSTRAINT userinterface_unknown_screens_unique_cluster
        UNIQUE (team_id, userinterface, cluster_dhash)
);

CREATE INDEX IF NOT EXISTS idx_ui_unknown_team_ui
    ON public.userinterface_unknown_screens (team_id, userinterface);

-- The page's default view: pending unknowns, newest first.
CREATE INDEX IF NOT EXISTS idx_ui_unknown_pending
    ON public.userinterface_unknown_screens (team_id, classification, status, frame_count DESC);

-- updated_at maintenance, matching the convention used by the other tables in this schema.
CREATE OR REPLACE FUNCTION public.touch_userinterface_unknown_screens_updated_at()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_userinterface_unknown_screens_updated_at
    ON public.userinterface_unknown_screens;
CREATE TRIGGER trg_userinterface_unknown_screens_updated_at
    BEFORE UPDATE ON public.userinterface_unknown_screens
    FOR EACH ROW EXECUTE FUNCTION public.touch_userinterface_unknown_screens_updated_at();

-- ---------------------------------------------------------------------------
-- Row Level Security — service_role only, matching the posture set by
-- 20260908b_close_app_tables_to_public_key.sql. Hosts and the server run with the service role;
-- a role with no policy sees no rows.
-- ---------------------------------------------------------------------------
ALTER TABLE public.userinterface_unknown_screens ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS service_role_all_userinterface_unknown_screens
    ON public.userinterface_unknown_screens;
CREATE POLICY service_role_all_userinterface_unknown_screens
    ON public.userinterface_unknown_screens
    FOR ALL TO service_role
    USING (true) WITH CHECK (true);

REVOKE ALL ON public.userinterface_unknown_screens FROM anon, authenticated;
GRANT ALL ON public.userinterface_unknown_screens TO service_role;

-- The scan runs on a host and writes over HTTP through the service role; anon and authenticated
-- have no business reading or writing another team's unknown screens.
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO service_role;

COMMIT;