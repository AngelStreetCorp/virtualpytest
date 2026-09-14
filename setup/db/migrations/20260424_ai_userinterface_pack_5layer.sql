-- ai_userinterface: 5-layer pack structure
-- ------------------------------------------------------
-- After validating the Markdown-pack approach end-to-end (host1 device3,
-- firmware 5.02, read_firmware task at 163 s on Minimax), migrate the schema
-- to the 5-layer model documented in docs/agent/navigation/AI_USERINTERFACE_MARKDOWN_PACKS.md.
--
-- Layer 0 (anchor)   : ai_userinterfaces.goto_home_actions (renamed from reset_actions)
-- Layer 1 (screens)  : ai_userinterface_screens gets layout_items, layout_type,
--                      focus_indicator, primitives, reference_image_path
-- Layer 2 (edges)    : new table ai_userinterface_transitions
-- Layer 3 (asserts)  : new table ai_userinterface_verifications
-- Layer 4 (tasks)    : new table ai_userinterface_tasks
-- + ai_userinterfaces.ui_pack_markdown for the compiled view the runtime LLM reads
--
-- FK pattern: children reference ai_userinterfaces(id) (the uuid PK), consistent
-- with ai_userinterface_screens / _flows / _quirks / etc.
--
-- Idempotent: every ADD COLUMN uses IF NOT EXISTS; CREATE TABLE uses
-- IF NOT EXISTS; the rename uses DO block to be a no-op if already renamed.

BEGIN;

-- ============================================================
-- Layer 0: rename reset_actions -> goto_home_actions + add compiled pack column
-- ============================================================

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_name = 'ai_userinterfaces'
               AND column_name = 'reset_actions')
     AND NOT EXISTS (SELECT 1 FROM information_schema.columns
                     WHERE table_name = 'ai_userinterfaces'
                       AND column_name = 'goto_home_actions')
  THEN
    EXECUTE 'ALTER TABLE ai_userinterfaces RENAME COLUMN reset_actions TO goto_home_actions';
    -- Best-effort: rename matching constraint if it exists under the old name
    BEGIN
      EXECUTE 'ALTER TABLE ai_userinterfaces RENAME CONSTRAINT ai_userinterfaces_reset_actions_shape TO ai_userinterfaces_goto_home_actions_shape';
    EXCEPTION WHEN undefined_object THEN
      NULL;
    END;
  END IF;
END $$;

ALTER TABLE ai_userinterfaces
  ADD COLUMN IF NOT EXISTS ui_pack_markdown text;

-- ============================================================
-- Layer 1: enrich ai_userinterface_screens
-- ============================================================

ALTER TABLE ai_userinterface_screens
  ADD COLUMN IF NOT EXISTS layout_type text,
  ADD COLUMN IF NOT EXISTS layout_items jsonb,
  ADD COLUMN IF NOT EXISTS focus_indicator text,
  ADD COLUMN IF NOT EXISTS primitives jsonb,
  ADD COLUMN IF NOT EXISTS reference_image_path text;

ALTER TABLE ai_userinterface_screens
  DROP CONSTRAINT IF EXISTS ai_userinterface_screens_layout_type_check;
ALTER TABLE ai_userinterface_screens
  ADD CONSTRAINT ai_userinterface_screens_layout_type_check CHECK (
    layout_type IS NULL OR layout_type IN
    ('horizontal_tabs', 'vertical_list', 'grid', 'modal')
  );

-- ============================================================
-- Layer 2: transitions (edges between screens)
-- ============================================================

CREATE TABLE IF NOT EXISTS ai_userinterface_transitions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  ai_userinterface_id uuid NOT NULL REFERENCES ai_userinterfaces(id) ON DELETE CASCADE,
  from_screen text NOT NULL,                 -- matches ai_userinterface_screens.name
  item_label text NOT NULL,                  -- label of the item being selected
  actions jsonb NOT NULL,                    -- execute_device_action.actions shape
  to_screen text,                            -- null = terminal or not-yet-classified
  verification_status text NOT NULL DEFAULT 'unverified',
  verification_passes int,
  verification_runs int,
  last_verified timestamptz,
  team_id uuid NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
  added_by text,
  added_at timestamptz NOT NULL DEFAULT now(),
  superseded_by uuid REFERENCES ai_userinterface_transitions(id),
  superseded_at timestamptz,
  superseded_reason text,
  CONSTRAINT ai_userinterface_transitions_status_check CHECK (
    verification_status IN ('unverified', 'deterministic', 'flaky', 'observed')
  ),
  CONSTRAINT ai_userinterface_transitions_actions_shape CHECK (
    jsonb_typeof(actions) = 'array' AND jsonb_array_length(actions) > 0
  ),
  UNIQUE (ai_userinterface_id, from_screen, item_label)
);

CREATE INDEX IF NOT EXISTS ai_userinterface_transitions_parent_idx
  ON ai_userinterface_transitions (ai_userinterface_id);

CREATE INDEX IF NOT EXISTS ai_userinterface_transitions_from_screen_idx
  ON ai_userinterface_transitions (ai_userinterface_id, from_screen);

-- ============================================================
-- Layer 3: verifications (per-screen assertions)
-- ============================================================

CREATE TABLE IF NOT EXISTS ai_userinterface_verifications (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  ai_userinterface_id uuid NOT NULL REFERENCES ai_userinterfaces(id) ON DELETE CASCADE,
  screen_name text NOT NULL,                 -- matches ai_userinterface_screens.name
  kind text NOT NULL,                        -- present | regex | value_matches
  selector text NOT NULL,                    -- OCR keyword or VLM field name
  expected text,                             -- regex or literal (null for 'present')
  severity text NOT NULL DEFAULT 'hard',     -- hard | soft
  team_id uuid NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
  added_by text,
  added_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT ai_userinterface_verifications_kind_check CHECK (
    kind IN ('present', 'regex', 'value_matches')
  ),
  CONSTRAINT ai_userinterface_verifications_severity_check CHECK (
    severity IN ('hard', 'soft')
  )
);

CREATE INDEX IF NOT EXISTS ai_userinterface_verifications_parent_screen_idx
  ON ai_userinterface_verifications (ai_userinterface_id, screen_name);

-- ============================================================
-- Layer 4: tasks (named user-facing flows)
-- ============================================================

CREATE TABLE IF NOT EXISTS ai_userinterface_tasks (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  ai_userinterface_id uuid NOT NULL REFERENCES ai_userinterfaces(id) ON DELETE CASCADE,
  task_name text NOT NULL,                   -- 'read_firmware', 'zap_chup', 'launch_replay'
  description text,
  steps_md text NOT NULL,                    -- prose of the task body (LLM-readable)
  verify_assertions jsonb,                   -- [{screen, assertion_id}, ...]
  returns jsonb,                             -- [{name, source_screen, extract_via}, ...]
  team_id uuid NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
  added_by text,
  added_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (ai_userinterface_id, task_name)
);

CREATE INDEX IF NOT EXISTS ai_userinterface_tasks_parent_idx
  ON ai_userinterface_tasks (ai_userinterface_id);

-- Row Level Security: platform default (added 2026-09-07, see 20260907_enable_rls_missing_tables.sql)
ALTER TABLE ai_userinterface_transitions   ENABLE ROW LEVEL SECURITY;
ALTER TABLE ai_userinterface_verifications ENABLE ROW LEVEL SECURITY;
ALTER TABLE ai_userinterface_tasks         ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "ai_userinterface_transitions_access_policy"   ON ai_userinterface_transitions;
DROP POLICY IF EXISTS "ai_userinterface_verifications_access_policy" ON ai_userinterface_verifications;
DROP POLICY IF EXISTS "ai_userinterface_tasks_access_policy"         ON ai_userinterface_tasks;
CREATE POLICY "ai_userinterface_transitions_access_policy" ON ai_userinterface_transitions
FOR ALL TO public USING (true);
CREATE POLICY "ai_userinterface_verifications_access_policy" ON ai_userinterface_verifications
FOR ALL TO public USING (true);
CREATE POLICY "ai_userinterface_tasks_access_policy" ON ai_userinterface_tasks
FOR ALL TO public USING (true);

COMMIT;
