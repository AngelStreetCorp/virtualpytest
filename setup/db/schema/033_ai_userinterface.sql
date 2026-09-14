-- 033_ai_userinterface.sql
-- =============================================================================
-- AI USER INTERFACE KNOWLEDGE BASE
-- =============================================================================
--
-- Standalone, AI-focused knowledge base for what an agent has *learned* about
-- a device's user interface. Distinct from the production `userinterfaces`
-- table (which owns navigation_trees executed by production scripts).
--
-- Why a separate table:
--   - Different lifecycle: production UIs are human-curated. These rows are
--     written by AI agents during exploration (crawler) and then validated
--     by a replay pass (verifier) before being trusted for runtime use.
--   - Different verification bar: every screen/quirk/hardware/fingerprint row
--     carries verified_against NOT NULL. Layer 2 transitions additionally
--     carry verification_status + passes/runs/last_verified set by the
--     Verifier after N replays.
--   - Different write authority: AI hallucinations can't corrupt a production
--     navigation tree because the two systems share nothing.
--   - Different recovery: append-only sub-tables (screens, transitions, quirks,
--     known_hardware, fingerprints) + per-version snapshots on the parent
--     enable one-call rollback when an edit was wrong.
--
-- The 5-layer pack model (anchor → screens → transitions → verifications → tasks),
-- the runtime execution contract, the crawler/verifier/packager workflow, and
-- the naming conventions all live in:
--   docs/agent/navigation/AI_USERINTERFACE_MARKDOWN_PACKS.md
--   docs/agent/AI_USERINTERFACE_example_EXAMPLE.md
-- The agent's read/write workflow, naming conventions per category, fingerprint
-- rules, and rollback semantics live in: docs/agent/navigation/AI_USERINTERFACE.md
--
-- =============================================================================

-- Drop in reverse-dependency order
DROP TABLE IF EXISTS ai_userinterfaces_history CASCADE;
DROP TABLE IF EXISTS ai_userinterface_fingerprints CASCADE;
DROP TABLE IF EXISTS ai_userinterface_known_hardware CASCADE;
DROP TABLE IF EXISTS ai_userinterface_quirks CASCADE;
DROP TABLE IF EXISTS ai_userinterface_tasks CASCADE;
DROP TABLE IF EXISTS ai_userinterface_verifications CASCADE;
DROP TABLE IF EXISTS ai_userinterface_transitions CASCADE;
DROP TABLE IF EXISTS ai_userinterface_screens CASCADE;
DROP TABLE IF EXISTS ai_userinterfaces CASCADE;


-- =============================================================================
-- Parent record: one row per learned UI
-- =============================================================================
CREATE TABLE ai_userinterfaces (
    id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
    ui_id text NOT NULL,                       -- Slug agents use, e.g. 'example-5.02', 'netflix-8'
    category text NOT NULL,                    -- 'stb' | 'android-tv' | 'android-mobile' | 'web'
    operator text,                             -- Required for 'stb'; null otherwise
    app text,                                  -- Required for 'android-tv'/'android-mobile'; null otherwise
    app_package text,                          -- Optional Android package name (com.netflix.ninja)
    domain text,                               -- Required for 'web'; null otherwise
    version text NOT NULL,                     -- User-facing version, e.g. '5.02', '8.x'
    middleware_version text,                   -- Engine-internal, e.g. v2 '04.02' (informational)
    identifying_cues text,                     -- Markdown: how to recognise this UI on screen
    navigation_primitives text,                -- Markdown: how universal keys behave (HOME/BACK/OK/arrows)
    hardware_deltas text,                      -- Markdown: per-hardware rendering differences
    unknown_todo text,                         -- Markdown: what we don't yet know
    -- Layer 0 of the 5-layer pack model: the mandatory "goto home" anchor sequence
    -- that must work from any starting state (including idle screensaver). Stored
    -- in the same JSONB shape as execute_device_action.actions[]. The runtime LLM
    -- is told to fire this blind (no screenshot) as the first step of any task.
    -- For example-5.02: BACK/4000, TVGUIDE/4000, TVGUIDE/4000, HOME/4000 — the
    -- leading BACK dismisses the ~2-3 min idle screensaver.
    goto_home_actions jsonb,
    -- Compiled pack view of Layers 0-4: the prose the runtime LLM reads end-to-end.
    -- Generated (today: hand-authored in backfill migrations; tomorrow: by a
    -- Packager script from the structured rows). See docs/agent/navigation/AI_USERINTERFACE_MARKDOWN_PACKS.md.
    ui_pack_markdown text,
    -- Per-variant compiled packs keyed by variant_id (e.g. locale/hardware variants of the
    -- same UI): {"<variant_id>": "<markdown>"}. Empty object when the UI has no variants.
    ui_pack_markdown_variants jsonb NOT NULL DEFAULT '{}'::jsonb,
    -- Soft link to the PRODUCTION userinterfaces row (same team) when one
    -- models the same UI. Deliberately NO foreign key: the two tables have
    -- independent lifecycles (production UIs are created/deleted by humans in
    -- the tree editor; this KB is written by agents) and may even live in
    -- different installs. A dangling value must never block either side —
    -- application code treats it as "link stale, ignore".
    userinterface_id uuid,
    last_verified date,                        -- Date of most recent end-to-end re-verification
    current_version integer NOT NULL DEFAULT 1,-- Bumped on every parent-row UPDATE
    team_id uuid NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now(),
    UNIQUE (team_id, ui_id),
    CHECK (category IN ('stb', 'android-tv', 'android-mobile', 'web')),
    CHECK (
        (category = 'stb'              AND operator IS NOT NULL) OR
        (category IN ('android-tv','android-mobile') AND app IS NOT NULL) OR
        (category = 'web'              AND domain   IS NOT NULL)
    ),
    CONSTRAINT ai_userinterfaces_goto_home_actions_shape CHECK (
        goto_home_actions IS NULL OR (
            jsonb_typeof(goto_home_actions) = 'array' AND jsonb_array_length(goto_home_actions) > 0
        )
    )
);


-- =============================================================================
-- Per-screen knowledge (append-only with soft-supersede)
-- =============================================================================
-- Layer 1: one row per known screen, enriched with layout data so the
-- Packager can emit the compiled pack without re-inferring structure.
CREATE TABLE ai_userinterface_screens (
    id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
    ai_userinterface_id uuid NOT NULL REFERENCES ai_userinterfaces(id) ON DELETE CASCADE,
    name text NOT NULL,                        -- e.g. 'home', 'settings.info.about'
    identifying_cues text,                     -- Markdown: how to recognise this screen visually
    exits text,                                -- Markdown: list of exit transitions (free-form notes)
    layout_type text,                          -- horizontal_tabs | vertical_list | grid | modal
    layout_items jsonb,                        -- Ordered labels, e.g. ["HOME","TV GUIDE",...]
    focus_indicator text,                      -- e.g. "red underline below focused label"
    primitives jsonb,                          -- {"next":{"key":"RIGHT","wait_time":800},...}
    reference_image_path text,                 -- e.g. "screenshot/stb/home.jpg" (git-ignored)
    verified_against text NOT NULL,            -- Build/version string seen when added
    added_by text NOT NULL,                    -- Agent name or user email
    added_at timestamp with time zone DEFAULT now(),
    superseded_at timestamp with time zone,
    superseded_by text,
    superseded_reason text,
    team_id uuid NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    CONSTRAINT ai_userinterface_screens_layout_type_check CHECK (
        layout_type IS NULL OR layout_type IN ('horizontal_tabs', 'vertical_list', 'grid', 'modal')
    )
);


-- Layer 2: one row per verified edge between screens. Replaces the legacy
-- ai_userinterface_flows (which stored end-to-end action arrays and assumed
-- a specific starting state — it failed across stateful sub-menus). A
-- transition is scoped to (from_screen, item_label); its `actions` array
-- moves the device from that known state to an `to_screen`.
-- verification_status is tagged by the Verifier after N replays:
--   'unverified'   — crawler recorded, not yet replayed
--   'deterministic'— >=95% success (fire blind at runtime)
--   'flaky'        — 70-95% success (retry once)
--   'observed'     — <70% success, or stateful (must capture first)
CREATE TABLE ai_userinterface_transitions (
    id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
    ai_userinterface_id uuid NOT NULL REFERENCES ai_userinterfaces(id) ON DELETE CASCADE,
    from_screen text NOT NULL,
    item_label text NOT NULL,
    variant_id text,                           -- null = default variant; else shadows the default row
    actions jsonb NOT NULL,                    -- execute_device_action.actions shape
    to_screen text,                            -- null = terminal / not-yet-classified
    verification_status text NOT NULL DEFAULT 'unverified',
    verification_passes integer,
    verification_runs integer,
    last_verified timestamp with time zone,
    added_by text,
    added_at timestamp with time zone NOT NULL DEFAULT now(),
    superseded_at timestamp with time zone,
    superseded_by uuid REFERENCES ai_userinterface_transitions(id),
    superseded_reason text,
    team_id uuid NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    CONSTRAINT ai_userinterface_transitions_status_check CHECK (
        verification_status IN ('unverified', 'deterministic', 'flaky', 'observed')
    ),
    CONSTRAINT ai_userinterface_transitions_actions_shape CHECK (
        jsonb_typeof(actions) = 'array' AND jsonb_array_length(actions) > 0
    )
);
-- One row per (parent, screen, label) per variant; the default variant is variant_id NULL.
CREATE UNIQUE INDEX ai_userinterface_transitions_uniq_key
    ON ai_userinterface_transitions (ai_userinterface_id, from_screen, item_label, (COALESCE(variant_id, '')));
CREATE INDEX ai_userinterface_transitions_variant_idx
    ON ai_userinterface_transitions (ai_userinterface_id, variant_id);
CREATE INDEX ai_userinterface_transitions_parent_idx
    ON ai_userinterface_transitions (ai_userinterface_id);
CREATE INDEX ai_userinterface_transitions_from_screen_idx
    ON ai_userinterface_transitions (ai_userinterface_id, from_screen);


-- Layer 3: per-screen assertions (the QA-facing layer). What to check on
-- every run for a given screen, separated from transient content.
-- Write-then-replace semantics (no supersession columns — delete + re-add).
CREATE TABLE ai_userinterface_verifications (
    id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
    ai_userinterface_id uuid NOT NULL REFERENCES ai_userinterfaces(id) ON DELETE CASCADE,
    screen_name text NOT NULL,                 -- matches ai_userinterface_screens.name
    kind text NOT NULL,                        -- present | regex | value_matches
    selector text NOT NULL,                    -- OCR keyword or VLM field name
    expected text,                             -- regex / literal (null for 'present')
    severity text NOT NULL DEFAULT 'hard',     -- hard (fail task) | soft (warn only)
    added_by text,
    added_at timestamp with time zone NOT NULL DEFAULT now(),
    team_id uuid NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    CONSTRAINT ai_userinterface_verifications_kind_check CHECK (
        kind IN ('present', 'regex', 'value_matches')
    ),
    CONSTRAINT ai_userinterface_verifications_severity_check CHECK (
        severity IN ('hard', 'soft')
    )
);
CREATE INDEX ai_userinterface_verifications_parent_screen_idx
    ON ai_userinterface_verifications (ai_userinterface_id, screen_name);


-- Layer 4: named user-facing tasks (read_firmware, zap_chup, launch_replay, ...)
-- Composed from Layer 2 transitions and Layer 3 assertions at runtime.
-- steps_md is the prose body the runtime LLM executes; it should use explicit
-- step tags [deterministic] / [observed] / [read] so less-smart providers
-- can follow without judgment calls. Write-then-replace semantics.
CREATE TABLE ai_userinterface_tasks (
    id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
    ai_userinterface_id uuid NOT NULL REFERENCES ai_userinterfaces(id) ON DELETE CASCADE,
    task_name text NOT NULL,                   -- e.g. 'read_firmware', 'zap_chup'
    description text,
    steps_md text NOT NULL,                    -- markdown body with [deterministic]/[observed]/[read] tagged steps
    verify_assertions jsonb,                   -- [{screen, assertion_id}, ...]
    returns jsonb,                             -- [{name, source_screen, extract_via}, ...]
    added_by text,
    added_at timestamp with time zone NOT NULL DEFAULT now(),
    team_id uuid NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    UNIQUE (ai_userinterface_id, task_name)
);
CREATE INDEX ai_userinterface_tasks_parent_idx
    ON ai_userinterface_tasks (ai_userinterface_id);


-- =============================================================================
-- Per-quirk knowledge (append-only)
-- =============================================================================
CREATE TABLE ai_userinterface_quirks (
    id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
    ai_userinterface_id uuid NOT NULL REFERENCES ai_userinterfaces(id) ON DELETE CASCADE,
    description text NOT NULL,                 -- The behaviour observed
    verified_against text NOT NULL,            -- Build/version where it was seen
    added_by text NOT NULL,
    added_at timestamp with time zone DEFAULT now(),
    superseded_at timestamp with time zone,
    superseded_by text,
    superseded_reason text,
    team_id uuid NOT NULL REFERENCES teams(id) ON DELETE CASCADE
);


-- =============================================================================
-- Hardware compatibility: which device models physically rendered this UI
-- =============================================================================
CREATE TABLE ai_userinterface_known_hardware (
    id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
    ai_userinterface_id uuid NOT NULL REFERENCES ai_userinterfaces(id) ON DELETE CASCADE,
    model text NOT NULL,                       -- e.g. 'example-stb'
    hw_rev text,                               -- e.g. 'REV1.0'
    verified_at date NOT NULL,
    added_by text NOT NULL,
    added_at timestamp with time zone DEFAULT now(),
    superseded_at timestamp with time zone,
    superseded_by text,
    superseded_reason text,
    team_id uuid NOT NULL REFERENCES teams(id) ON DELETE CASCADE
);


-- =============================================================================
-- Fingerprints: how to map a device's runtime state to this ui_id
-- (DB-resident replacement for what was originally proposed as _registry.json)
-- =============================================================================
CREATE TABLE ai_userinterface_fingerprints (
    id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
    ai_userinterface_id uuid NOT NULL REFERENCES ai_userinterfaces(id) ON DELETE CASCADE,
    fingerprint_type text NOT NULL,            -- 'software_version_glob' | 'foreground_package' | 'url_host'
    pattern text NOT NULL,                     -- The glob / exact value to match
    verified_against text NOT NULL,            -- One literal value the pattern actually matched
    added_by text NOT NULL,
    added_at timestamp with time zone DEFAULT now(),
    superseded_at timestamp with time zone,
    superseded_by text,
    superseded_reason text,
    team_id uuid NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    CHECK (fingerprint_type IN ('software_version_glob','foreground_package','url_host'))
);


-- =============================================================================
-- Snapshot history for the parent ai_userinterfaces record
-- (matches navigation_trees_history pattern: full row snapshot, not field diffs)
-- =============================================================================
CREATE TABLE ai_userinterfaces_history (
    id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
    ai_userinterface_id uuid NOT NULL REFERENCES ai_userinterfaces(id) ON DELETE CASCADE,
    team_id uuid NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    version_number integer NOT NULL,           -- Matches ai_userinterfaces.current_version at write time
    modification_type text NOT NULL CHECK (modification_type IN ('create','update','delete','restore')),
    modified_by text NOT NULL,                 -- Agent name or user UUID-as-text
    snapshot jsonb NOT NULL,                   -- Full ai_userinterfaces row at this version
    changes_summary text,                      -- Human-readable summary of what changed
    created_at timestamp with time zone DEFAULT now(),
    restored_from_version integer              -- Set by 'restore' rows; the version they restored from
);


-- =============================================================================
-- Indexes
-- =============================================================================

-- Parent
CREATE INDEX idx_ai_userinterfaces_team       ON ai_userinterfaces(team_id);
CREATE INDEX idx_ai_userinterfaces_ui_id      ON ai_userinterfaces(ui_id);
CREATE INDEX idx_ai_userinterfaces_category   ON ai_userinterfaces(category);
CREATE INDEX idx_ai_userinterfaces_team_ui    ON ai_userinterfaces(team_id, ui_id);
CREATE INDEX idx_ai_userinterfaces_prod_ui    ON ai_userinterfaces(userinterface_id) WHERE userinterface_id IS NOT NULL;

-- Screens
CREATE INDEX idx_ai_uif_screens_parent        ON ai_userinterface_screens(ai_userinterface_id);
CREATE INDEX idx_ai_uif_screens_team          ON ai_userinterface_screens(team_id);
CREATE INDEX idx_ai_uif_screens_active        ON ai_userinterface_screens(ai_userinterface_id) WHERE superseded_at IS NULL;

-- Transitions (Layer 2) — indexes declared inline in CREATE TABLE above;
-- listed here for parity with the pattern used by other tables.
--   ai_userinterface_transitions_parent_idx
--   ai_userinterface_transitions_from_screen_idx

-- Verifications (Layer 3) — inline: ai_userinterface_verifications_parent_screen_idx
-- Tasks (Layer 4)          — inline: ai_userinterface_tasks_parent_idx

-- Quirks
CREATE INDEX idx_ai_uif_quirks_parent         ON ai_userinterface_quirks(ai_userinterface_id);
CREATE INDEX idx_ai_uif_quirks_active         ON ai_userinterface_quirks(ai_userinterface_id) WHERE superseded_at IS NULL;

-- Known hardware
CREATE INDEX idx_ai_uif_hw_parent             ON ai_userinterface_known_hardware(ai_userinterface_id);
CREATE INDEX idx_ai_uif_hw_active             ON ai_userinterface_known_hardware(ai_userinterface_id) WHERE superseded_at IS NULL;

-- Fingerprints
CREATE INDEX idx_ai_uif_fp_parent             ON ai_userinterface_fingerprints(ai_userinterface_id);
CREATE INDEX idx_ai_uif_fp_type               ON ai_userinterface_fingerprints(fingerprint_type);
CREATE INDEX idx_ai_uif_fp_active             ON ai_userinterface_fingerprints(ai_userinterface_id) WHERE superseded_at IS NULL;
CREATE INDEX idx_ai_uif_fp_pattern_lookup     ON ai_userinterface_fingerprints(fingerprint_type, pattern) WHERE superseded_at IS NULL;

-- History
CREATE INDEX idx_ai_uif_history_parent        ON ai_userinterfaces_history(ai_userinterface_id);
CREATE INDEX idx_ai_uif_history_team          ON ai_userinterfaces_history(team_id);
CREATE INDEX idx_ai_uif_history_version       ON ai_userinterfaces_history(ai_userinterface_id, version_number);


-- =============================================================================
-- Row Level Security (matches navigation_trees pattern: team-scoped + service_role bypass)
-- =============================================================================
ALTER TABLE ai_userinterfaces                ENABLE ROW LEVEL SECURITY;
ALTER TABLE ai_userinterface_screens         ENABLE ROW LEVEL SECURITY;
ALTER TABLE ai_userinterface_transitions     ENABLE ROW LEVEL SECURITY;
ALTER TABLE ai_userinterface_verifications   ENABLE ROW LEVEL SECURITY;
ALTER TABLE ai_userinterface_tasks           ENABLE ROW LEVEL SECURITY;
ALTER TABLE ai_userinterface_quirks          ENABLE ROW LEVEL SECURITY;
ALTER TABLE ai_userinterface_known_hardware  ENABLE ROW LEVEL SECURITY;
ALTER TABLE ai_userinterface_fingerprints    ENABLE ROW LEVEL SECURITY;
ALTER TABLE ai_userinterfaces_history        ENABLE ROW LEVEL SECURITY;

CREATE POLICY "ai_userinterfaces_access_policy" ON ai_userinterfaces
FOR ALL USING (true);

CREATE POLICY "ai_userinterface_screens_access_policy" ON ai_userinterface_screens
FOR ALL USING (true);

CREATE POLICY "ai_userinterface_transitions_access_policy" ON ai_userinterface_transitions
FOR ALL USING (true);

CREATE POLICY "ai_userinterface_verifications_access_policy" ON ai_userinterface_verifications
FOR ALL USING (true);

CREATE POLICY "ai_userinterface_tasks_access_policy" ON ai_userinterface_tasks
FOR ALL USING (true);

CREATE POLICY "ai_userinterface_quirks_access_policy" ON ai_userinterface_quirks
FOR ALL USING (true);

CREATE POLICY "ai_userinterface_known_hardware_access_policy" ON ai_userinterface_known_hardware
FOR ALL USING (true);

CREATE POLICY "ai_userinterface_fingerprints_access_policy" ON ai_userinterface_fingerprints
FOR ALL USING (true);

CREATE POLICY "ai_userinterfaces_history_access_policy" ON ai_userinterfaces_history
FOR ALL
TO public
USING (true);


-- =============================================================================
-- Comments
-- =============================================================================
COMMENT ON TABLE  ai_userinterfaces                    IS 'AI-learned UI knowledge base. Standalone from production `userinterfaces`. See docs/agent/navigation/AI_USERINTERFACE.md for the agent workflow.';
COMMENT ON COLUMN ai_userinterfaces.ui_id              IS 'Stable agent-facing slug (operator-version for stb, app-version for apps, domain for web). UNIQUE per team.';
COMMENT ON COLUMN ai_userinterfaces.current_version    IS 'Bumped by application code on every UPDATE; matches the latest ai_userinterfaces_history.version_number row.';
COMMENT ON COLUMN ai_userinterfaces.userinterface_id   IS 'Soft link to the production userinterfaces.id modelling the same UI. No FK by design (independent lifecycles); dangling values are ignored by application code.';

COMMENT ON TABLE  ai_userinterface_transitions         IS 'Layer 2 of the pack model: verified edges between screens. Replaces the legacy ai_userinterface_flows. Scoped by (ai_userinterface_id, from_screen, item_label).';
COMMENT ON COLUMN ai_userinterface_transitions.verification_status IS 'Tag written by the Verifier after replay N times. deterministic (>=95%) fires blind; flaky (70-95%) retries once; observed (<70%) must capture first.';
COMMENT ON COLUMN ai_userinterface_transitions.actions  IS 'Literal execute_device_action.actions[] array. No shorthand, no iterator>1 for IR. Stored expanded so the agent emits it verbatim.';

COMMENT ON TABLE  ai_userinterface_verifications       IS 'Layer 3: per-screen assertions the Packager surfaces in the compiled pack. Used by the runtime LLM to validate state after navigation.';
COMMENT ON TABLE  ai_userinterface_tasks               IS 'Layer 4: named user-facing flows (read_firmware, zap_chup, launch_replay, ...). steps_md is the prose the runtime LLM executes; composes Layer 2 transitions + Layer 3 assertions.';

COMMENT ON TABLE  ai_userinterface_fingerprints        IS 'Runtime fingerprints used to resolve a device''s state to a ui_id. Replaces the legacy _registry.json file approach.';

COMMENT ON TABLE  ai_userinterfaces_history            IS 'Per-version snapshot of the ai_userinterfaces parent record. Enables one-call rollback when an AI edit was wrong.';
COMMENT ON COLUMN ai_userinterfaces_history.snapshot   IS 'Full ai_userinterfaces row at this version, as jsonb. Used to restore on `revert_userinterface(ui_id, version)`.';
