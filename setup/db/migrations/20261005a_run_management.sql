-- 20261005a_run_management.sql
-- TASK-42 — Test Run Management Parity (Wave 1A, data worker).
--
-- Run governance + run-quality schema for v1 parity:
--
--   run_groups              — folder-like container for completed script results.
--   run_milestones          — date-bound delivery targets with completion timestamps.
--   run_label_definitions   — team-scoped label catalog (case-insensitive names,
--                             trimmed length check, team-scoped unique).
--   script_result_labels    — composite FK join: team_id + script_result_id + label.
--   testcase_labels         — composite FK join: team_id + testcase_id + label.
--   script_results          — ALTER adds milestone_id + run_group_id FK columns +
--                             scoped indexes for the new assignments.
--   defects                 — local defects (integration NULL) and pushed-to-Jira
--                             defects (integration='jira', external_key unique).
--   defect_script_results   — composite FK join so one defect can cover many runs.
--   run_share_snapshots     — sanitized public share payload; token_hash only (never
--                             plaintext); revocable; expiry-checked.
--   custom_reports          — private saved report: validated filter, columns, chart.
--   manual_sessions         — resumable manual run + idempotent finalize.
--   manual_session_steps    — ordinal step list with optional evidence.
--
-- Composite FK behavior: every link spans (team_id, parent_id) so a row pointing at
-- a parent from another tenant is rejected at the DB layer even when the app uses
-- the service role (RLS would not catch it).
--
-- RLS: every new table enables row-level security. The service_role is the only
-- writer (matches the established ai_routing/ai_decisions posture). Reads from
-- anon/authenticated are blocked — the backend service is the data-plane.
--
-- 10-label-maximum-per-entity invariant:
--   Enforced by a BEFORE INSERT OR UPDATE trigger (run_mgmt_enforce_label_cap) that
--   first takes a transaction-scoped advisory lock on (kind, team, entity), then
--   counts, so two concurrent transactions cannot both add the 10th label. The
--   replace/batch RPCs take the same lock before changing a label set.
--
-- This migration is forward-only. The matching rollback file is
-- 20261005a_run_management_rollback.sql. The fresh-install equivalent is
-- setup/db/schema/061_run_management.sql.

BEGIN;

-- ============================================================================
-- Run governance: run_groups, run_milestones, run_label_definitions, label
-- assignments, script_results.milestone_id / run_group_id, group rerun requests.
--
-- Every link is a composite (team_id, parent_id) foreign key onto a unique
-- (team_id, id) parent key, so a row can never point at another team's parent,
-- even when written through the service role (which bypasses RLS).
-- Governance objects are archived, never deleted: script_results references use
-- the default NO ACTION, so deleting a group/milestone that still has members is
-- refused, while a team delete (which cascades to both sides) still succeeds.
-- ============================================================================

-- Parent keys for the composite FKs in this file (defects and manual sessions
-- reference them too).
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'script_results_team_id_id_key'
          AND conrelid = 'public.script_results'::regclass
    ) THEN
        ALTER TABLE public.script_results
            ADD CONSTRAINT script_results_team_id_id_key UNIQUE (team_id, id);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'testcase_definitions_team_id_testcase_id_key'
          AND conrelid = 'public.testcase_definitions'::regclass
    ) THEN
        ALTER TABLE public.testcase_definitions
            ADD CONSTRAINT testcase_definitions_team_id_testcase_id_key UNIQUE (team_id, testcase_id);
    END IF;
END$$;

CREATE OR REPLACE FUNCTION public.run_mgmt_touch_updated_at() RETURNS trigger
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
BEGIN
    NEW.updated_at := NOW();
    RETURN NEW;
END;
$$;

-- ----------------------------------------------------------------------------
-- run_groups — organizes completed script results (one group per result).
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.run_groups (
    id          UUID NOT NULL DEFAULT gen_random_uuid(),
    team_id     UUID NOT NULL REFERENCES public.teams(id) ON DELETE CASCADE,
    name        TEXT NOT NULL,
    description TEXT,
    color       TEXT,
    pinned      BOOLEAN NOT NULL DEFAULT false,
    archived    BOOLEAN NOT NULL DEFAULT false,
    created_by  TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT run_groups_pkey PRIMARY KEY (id),
    CONSTRAINT run_groups_team_id_id_key UNIQUE (team_id, id),
    CONSTRAINT run_groups_name_check
        CHECK (name = btrim(name) AND length(name) BETWEEN 1 AND 120),
    CONSTRAINT run_groups_description_check
        CHECK (description IS NULL OR length(description) <= 2000),
    CONSTRAINT run_groups_color_check
        CHECK (color IS NULL OR color ~ '^#([0-9a-f]{3}|[0-9a-f]{6}|[0-9a-f]{8})$')
);

COMMENT ON TABLE public.run_groups IS
    'Organizes completed script_results (script_results.run_group_id; at most one group per result). Archived, never deleted.';

CREATE UNIQUE INDEX IF NOT EXISTS run_groups_team_lower_name_key
    ON public.run_groups (team_id, lower(name));
CREATE INDEX IF NOT EXISTS run_groups_team_archived_idx
    ON public.run_groups (team_id, archived);

DROP TRIGGER IF EXISTS run_groups_touch_updated_at ON public.run_groups;
CREATE TRIGGER run_groups_touch_updated_at
    BEFORE UPDATE ON public.run_groups
    FOR EACH ROW EXECUTE FUNCTION public.run_mgmt_touch_updated_at();

-- ----------------------------------------------------------------------------
-- run_milestones — delivery targets.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.run_milestones (
    id           UUID NOT NULL DEFAULT gen_random_uuid(),
    team_id      UUID NOT NULL REFERENCES public.teams(id) ON DELETE CASCADE,
    name         TEXT NOT NULL,
    description  TEXT,
    due_at       TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    archived     BOOLEAN NOT NULL DEFAULT false,
    created_by   TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT run_milestones_pkey PRIMARY KEY (id),
    CONSTRAINT run_milestones_team_id_id_key UNIQUE (team_id, id),
    CONSTRAINT run_milestones_name_check
        CHECK (name = btrim(name) AND length(name) BETWEEN 1 AND 120),
    CONSTRAINT run_milestones_description_check
        CHECK (description IS NULL OR length(description) <= 2000)
);

COMMENT ON TABLE public.run_milestones IS
    'Delivery target for script_results (script_results.milestone_id). completed_at is set by a person. Archived, never deleted.';

CREATE UNIQUE INDEX IF NOT EXISTS run_milestones_team_lower_name_key
    ON public.run_milestones (team_id, lower(name));
CREATE INDEX IF NOT EXISTS run_milestones_team_archived_idx
    ON public.run_milestones (team_id, archived);

DROP TRIGGER IF EXISTS run_milestones_touch_updated_at ON public.run_milestones;
CREATE TRIGGER run_milestones_touch_updated_at
    BEFORE UPDATE ON public.run_milestones
    FOR EACH ROW EXECUTE FUNCTION public.run_mgmt_touch_updated_at();

-- ----------------------------------------------------------------------------
-- run_label_definitions — team label catalog. Stored trimmed, 1..20 chars,
-- unique per team ignoring case. Assignments reference the id, so a rename is
-- seen everywhere at once.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.run_label_definitions (
    id         UUID NOT NULL DEFAULT gen_random_uuid(),
    team_id    UUID NOT NULL REFERENCES public.teams(id) ON DELETE CASCADE,
    name       TEXT NOT NULL,
    color      TEXT,
    created_by TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT run_label_definitions_pkey PRIMARY KEY (id),
    CONSTRAINT run_label_definitions_team_id_id_key UNIQUE (team_id, id),
    CONSTRAINT run_label_definitions_name_check
        CHECK (name = btrim(name) AND length(name) BETWEEN 1 AND 20),
    CONSTRAINT run_label_definitions_color_check
        CHECK (color IS NULL OR color ~ '^#([0-9a-f]{3}|[0-9a-f]{6}|[0-9a-f]{8})$')
);

COMMENT ON TABLE public.run_label_definitions IS
    'Team label catalog: trimmed 1..20 chars, case-insensitive unique per team. Deleting a label removes its assignments only.';

CREATE UNIQUE INDEX IF NOT EXISTS run_label_definitions_team_lower_name_key
    ON public.run_label_definitions (team_id, lower(name));

DROP TRIGGER IF EXISTS run_label_definitions_touch_updated_at ON public.run_label_definitions;
CREATE TRIGGER run_label_definitions_touch_updated_at
    BEFORE UPDATE ON public.run_label_definitions
    FOR EACH ROW EXECUTE FUNCTION public.run_mgmt_touch_updated_at();

-- ----------------------------------------------------------------------------
-- Label assignments. Deleting a label or the labelled entity removes the
-- assignment rows only.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.script_result_labels (
    team_id          UUID NOT NULL,
    script_result_id UUID NOT NULL,
    run_label_id     UUID NOT NULL,
    created_by       TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT script_result_labels_pkey PRIMARY KEY (team_id, script_result_id, run_label_id),
    CONSTRAINT script_result_labels_result_fk FOREIGN KEY (team_id, script_result_id)
        REFERENCES public.script_results (team_id, id) ON DELETE CASCADE,
    CONSTRAINT script_result_labels_label_fk FOREIGN KEY (team_id, run_label_id)
        REFERENCES public.run_label_definitions (team_id, id) ON DELETE CASCADE
);

COMMENT ON TABLE public.script_result_labels IS
    'Labels on a script_result (max 10, enforced by run_mgmt_enforce_label_cap under an advisory lock).';

CREATE INDEX IF NOT EXISTS script_result_labels_label_idx
    ON public.script_result_labels (team_id, run_label_id);

CREATE TABLE IF NOT EXISTS public.testcase_labels (
    team_id      UUID NOT NULL,
    testcase_id  UUID NOT NULL,
    run_label_id UUID NOT NULL,
    created_by   TEXT,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT testcase_labels_pkey PRIMARY KEY (team_id, testcase_id, run_label_id),
    CONSTRAINT testcase_labels_testcase_fk FOREIGN KEY (team_id, testcase_id)
        REFERENCES public.testcase_definitions (team_id, testcase_id) ON DELETE CASCADE,
    CONSTRAINT testcase_labels_label_fk FOREIGN KEY (team_id, run_label_id)
        REFERENCES public.run_label_definitions (team_id, id) ON DELETE CASCADE
);

COMMENT ON TABLE public.testcase_labels IS
    'Labels on a testcase_definition (max 10, enforced by run_mgmt_enforce_label_cap under an advisory lock).';

CREATE INDEX IF NOT EXISTS testcase_labels_label_idx
    ON public.testcase_labels (team_id, run_label_id);

-- At most 10 labels per entity. A count alone is not safe under READ COMMITTED:
-- two transactions adding the 10th and 11th label would both count 9. The
-- transaction-scoped advisory lock on (kind, team, entity) serializes writers of
-- one entity; the count then runs with a fresh snapshot that sees every
-- committed assignment. run_mgmt_replace_labels takes the same lock first.
CREATE OR REPLACE FUNCTION public.run_mgmt_enforce_label_cap() RETURNS trigger
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
DECLARE
    v_count INTEGER;
BEGIN
    IF TG_TABLE_NAME = 'script_result_labels' THEN
        PERFORM pg_advisory_xact_lock(hashtextextended(
            'run_mgmt_labels:script_result:' || NEW.team_id::text || ':' || NEW.script_result_id::text, 0));
        SELECT count(*) INTO v_count
        FROM public.script_result_labels
        WHERE team_id = NEW.team_id
          AND script_result_id = NEW.script_result_id
          AND run_label_id <> NEW.run_label_id;
    ELSE
        PERFORM pg_advisory_xact_lock(hashtextextended(
            'run_mgmt_labels:testcase:' || NEW.team_id::text || ':' || NEW.testcase_id::text, 0));
        SELECT count(*) INTO v_count
        FROM public.testcase_labels
        WHERE team_id = NEW.team_id
          AND testcase_id = NEW.testcase_id
          AND run_label_id <> NEW.run_label_id;
    END IF;
    IF v_count >= 10 THEN
        RAISE EXCEPTION 'run_mgmt:label_limit: at most 10 labels per entity'
            USING ERRCODE = 'check_violation';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS script_result_labels_enforce_cap ON public.script_result_labels;
CREATE TRIGGER script_result_labels_enforce_cap
    BEFORE INSERT OR UPDATE ON public.script_result_labels
    FOR EACH ROW EXECUTE FUNCTION public.run_mgmt_enforce_label_cap();

DROP TRIGGER IF EXISTS testcase_labels_enforce_cap ON public.testcase_labels;
CREATE TRIGGER testcase_labels_enforce_cap
    BEFORE INSERT OR UPDATE ON public.testcase_labels
    FOR EACH ROW EXECUTE FUNCTION public.run_mgmt_enforce_label_cap();

-- ----------------------------------------------------------------------------
-- script_results — optional milestone and group membership.
-- ----------------------------------------------------------------------------
ALTER TABLE public.script_results ADD COLUMN IF NOT EXISTS milestone_id UUID;
ALTER TABLE public.script_results ADD COLUMN IF NOT EXISTS run_group_id UUID;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'script_results_milestone_fk'
          AND conrelid = 'public.script_results'::regclass
    ) THEN
        ALTER TABLE public.script_results
            ADD CONSTRAINT script_results_milestone_fk
            FOREIGN KEY (team_id, milestone_id)
            REFERENCES public.run_milestones (team_id, id);
    END IF;
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'script_results_run_group_fk'
          AND conrelid = 'public.script_results'::regclass
    ) THEN
        ALTER TABLE public.script_results
            ADD CONSTRAINT script_results_run_group_fk
            FOREIGN KEY (team_id, run_group_id)
            REFERENCES public.run_groups (team_id, id);
    END IF;
END$$;

CREATE INDEX IF NOT EXISTS script_results_team_milestone_idx
    ON public.script_results (team_id, milestone_id) WHERE milestone_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS script_results_team_run_group_idx
    ON public.script_results (team_id, run_group_id) WHERE run_group_id IS NOT NULL;

COMMENT ON COLUMN public.script_results.milestone_id IS
    'Optional run_milestones link (same team, composite FK). Governance only; never changes the execution verdict.';
COMMENT ON COLUMN public.script_results.run_group_id IS
    'Optional run_groups link (same team, composite FK); at most one group per result. Governance only.';

-- ----------------------------------------------------------------------------
-- run_group_rerun_requests — durable idempotency for POST /run-groups/:id/rerun.
-- The (team_id, idempotency_key) unique key makes a retried request return the
-- recorded dispatch instead of launching the runs a second time.
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.run_group_rerun_requests (
    id              UUID NOT NULL DEFAULT gen_random_uuid(),
    team_id         UUID NOT NULL REFERENCES public.teams(id) ON DELETE CASCADE,
    run_group_id    UUID NOT NULL,
    idempotency_key TEXT NOT NULL,
    mode            TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'dispatching',
    requested_by    TEXT,
    dispatched      JSONB NOT NULL DEFAULT '[]'::jsonb,
    skipped         JSONB NOT NULL DEFAULT '[]'::jsonb,
    error           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at    TIMESTAMPTZ,
    CONSTRAINT run_group_rerun_requests_pkey PRIMARY KEY (id),
    CONSTRAINT run_group_rerun_requests_team_key_key UNIQUE (team_id, idempotency_key),
    CONSTRAINT run_group_rerun_requests_group_fk FOREIGN KEY (team_id, run_group_id)
        REFERENCES public.run_groups (team_id, id) ON DELETE CASCADE,
    CONSTRAINT run_group_rerun_requests_key_check
        CHECK (length(btrim(idempotency_key)) BETWEEN 1 AND 120),
    CONSTRAINT run_group_rerun_requests_mode_check
        CHECK (mode IN ('all', 'failures')),
    CONSTRAINT run_group_rerun_requests_status_check
        CHECK (status IN ('dispatching', 'dispatched', 'failed')),
    CONSTRAINT run_group_rerun_requests_dispatched_check
        CHECK (jsonb_typeof(dispatched) = 'array'),
    CONSTRAINT run_group_rerun_requests_skipped_check
        CHECK (jsonb_typeof(skipped) = 'array')
);

COMMENT ON TABLE public.run_group_rerun_requests IS
    'One row per group rerun request; unique (team_id, idempotency_key) prevents a retry from dispatching twice.';

CREATE INDEX IF NOT EXISTS run_group_rerun_requests_group_idx
    ON public.run_group_rerun_requests (team_id, run_group_id, created_at DESC);

-- ----------------------------------------------------------------------------
-- Atomic assignment RPCs (PostgREST cannot run a multi-statement transaction).
-- SECURITY DEFINER with explicit team + host-scope checks; callable by the
-- server's service role only.
-- ----------------------------------------------------------------------------

-- Replace the whole label set of one script_result or testcase.
-- p_host_names: the caller's host scope for script results (NULL = unscoped).
-- p_device_keys: the workspace device filter as 'host_name:device_name' keys
-- (NULL = no device filter).
CREATE OR REPLACE FUNCTION public.run_mgmt_replace_labels(
    p_team_id     UUID,
    p_entity_kind TEXT,
    p_entity_id   UUID,
    p_label_ids   UUID[],
    p_host_names  TEXT[] DEFAULT NULL,
    p_actor       TEXT DEFAULT NULL,
    p_device_keys TEXT[] DEFAULT NULL
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    v_labels UUID[];
    v_found  INTEGER;
BEGIN
    IF p_team_id IS NULL OR p_entity_id IS NULL THEN
        RAISE EXCEPTION 'run_mgmt:invalid: team_id and entity id are required'
            USING ERRCODE = 'invalid_parameter_value';
    END IF;
    IF p_entity_kind IS NULL OR p_entity_kind NOT IN ('script_result', 'testcase') THEN
        RAISE EXCEPTION 'run_mgmt:invalid: entity kind must be script_result or testcase'
            USING ERRCODE = 'invalid_parameter_value';
    END IF;

    SELECT COALESCE(array_agg(DISTINCT l ORDER BY l), '{}'::uuid[]) INTO v_labels
    FROM unnest(COALESCE(p_label_ids, '{}'::uuid[])) AS l
    WHERE l IS NOT NULL;

    IF cardinality(v_labels) > 10 THEN
        RAISE EXCEPTION 'run_mgmt:label_limit: at most 10 labels per entity'
            USING ERRCODE = 'check_violation';
    END IF;

    PERFORM pg_advisory_xact_lock(hashtextextended(
        'run_mgmt_labels:' || p_entity_kind || ':' || p_team_id::text || ':' || p_entity_id::text, 0));

    IF p_entity_kind = 'script_result' THEN
        PERFORM 1 FROM public.script_results
        WHERE team_id = p_team_id AND id = p_entity_id
          AND (p_host_names IS NULL OR host_name = ANY (p_host_names))
          AND (p_device_keys IS NULL OR (host_name || ':' || device_name) = ANY (p_device_keys));
    ELSE
        PERFORM 1 FROM public.testcase_definitions
        WHERE team_id = p_team_id AND testcase_id = p_entity_id;
    END IF;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'run_mgmt:not_found: % not found in this scope', p_entity_kind
            USING ERRCODE = 'no_data_found';
    END IF;

    SELECT count(*) INTO v_found
    FROM public.run_label_definitions
    WHERE team_id = p_team_id AND id = ANY (v_labels);
    IF v_found <> cardinality(v_labels) THEN
        RAISE EXCEPTION 'run_mgmt:foreign_label: % label id(s) are not in this team',
            cardinality(v_labels) - v_found
            USING ERRCODE = 'invalid_parameter_value';
    END IF;

    IF p_entity_kind = 'script_result' THEN
        DELETE FROM public.script_result_labels
        WHERE team_id = p_team_id AND script_result_id = p_entity_id
          AND NOT (run_label_id = ANY (v_labels));
        INSERT INTO public.script_result_labels (team_id, script_result_id, run_label_id, created_by)
        SELECT p_team_id, p_entity_id, l, p_actor FROM unnest(v_labels) AS l
        ON CONFLICT DO NOTHING;
    ELSE
        DELETE FROM public.testcase_labels
        WHERE team_id = p_team_id AND testcase_id = p_entity_id
          AND NOT (run_label_id = ANY (v_labels));
        INSERT INTO public.testcase_labels (team_id, testcase_id, run_label_id, created_by)
        SELECT p_team_id, p_entity_id, l, p_actor FROM unnest(v_labels) AS l
        ON CONFLICT DO NOTHING;
    END IF;

    RETURN jsonb_build_object(
        'entity_kind', p_entity_kind,
        'entity_id', p_entity_id,
        'label_ids', to_jsonb(v_labels)
    );
END;
$$;

-- Assign milestone / group / label set to many script results at once. All or
-- nothing: every id must belong to the team and the host scope, the target
-- milestone/group must be in the team and not archived (clearing is always
-- allowed), and any label failure rolls the whole batch back.
CREATE OR REPLACE FUNCTION public.run_mgmt_assign_script_results(
    p_team_id           UUID,
    p_script_result_ids UUID[],
    p_host_names        TEXT[],
    p_set_milestone     BOOLEAN,
    p_milestone_id      UUID,
    p_set_run_group     BOOLEAN,
    p_run_group_id      UUID,
    p_set_labels        BOOLEAN,
    p_label_ids         UUID[],
    p_actor             TEXT DEFAULT NULL,
    p_device_keys       TEXT[] DEFAULT NULL
) RETURNS JSONB
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_temp
AS $$
DECLARE
    v_ids   UUID[];
    v_found INTEGER;
    v_id    UUID;
BEGIN
    IF p_team_id IS NULL THEN
        RAISE EXCEPTION 'run_mgmt:invalid: team_id is required'
            USING ERRCODE = 'invalid_parameter_value';
    END IF;
    IF NOT (COALESCE(p_set_milestone, false) OR COALESCE(p_set_run_group, false)
            OR COALESCE(p_set_labels, false)) THEN
        RAISE EXCEPTION 'run_mgmt:invalid: nothing to assign'
            USING ERRCODE = 'invalid_parameter_value';
    END IF;

    SELECT COALESCE(array_agg(DISTINCT x ORDER BY x), '{}'::uuid[]) INTO v_ids
    FROM unnest(COALESCE(p_script_result_ids, '{}'::uuid[])) AS x
    WHERE x IS NOT NULL;

    IF cardinality(v_ids) = 0 OR cardinality(v_ids) > 500 THEN
        RAISE EXCEPTION 'run_mgmt:invalid: between 1 and 500 script result ids are required'
            USING ERRCODE = 'invalid_parameter_value';
    END IF;

    -- Lock the members in id order (NO KEY UPDATE does not block the FK key-share
    -- locks taken by label inserts, so this cannot deadlock with label writers).
    SELECT count(*) INTO v_found FROM (
        SELECT id FROM public.script_results
        WHERE team_id = p_team_id AND id = ANY (v_ids)
          AND (p_host_names IS NULL OR host_name = ANY (p_host_names))
          AND (p_device_keys IS NULL OR (host_name || ':' || device_name) = ANY (p_device_keys))
        ORDER BY id
        FOR NO KEY UPDATE
    ) AS members;
    IF v_found <> cardinality(v_ids) THEN
        RAISE EXCEPTION 'run_mgmt:not_found: % of % script results are not in this scope',
            cardinality(v_ids) - v_found, cardinality(v_ids)
            USING ERRCODE = 'no_data_found';
    END IF;

    IF COALESCE(p_set_milestone, false) AND p_milestone_id IS NOT NULL THEN
        PERFORM 1 FROM public.run_milestones
        WHERE team_id = p_team_id AND id = p_milestone_id AND NOT archived;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'run_mgmt:not_found: milestone not found or archived'
                USING ERRCODE = 'no_data_found';
        END IF;
    END IF;
    IF COALESCE(p_set_run_group, false) AND p_run_group_id IS NOT NULL THEN
        PERFORM 1 FROM public.run_groups
        WHERE team_id = p_team_id AND id = p_run_group_id AND NOT archived;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'run_mgmt:not_found: run group not found or archived'
                USING ERRCODE = 'no_data_found';
        END IF;
    END IF;

    IF COALESCE(p_set_milestone, false) OR COALESCE(p_set_run_group, false) THEN
        UPDATE public.script_results
        SET milestone_id = CASE WHEN COALESCE(p_set_milestone, false) THEN p_milestone_id ELSE milestone_id END,
            run_group_id = CASE WHEN COALESCE(p_set_run_group, false) THEN p_run_group_id ELSE run_group_id END,
            updated_at   = timezone('utc'::text, now())
        WHERE team_id = p_team_id AND id = ANY (v_ids);
    END IF;

    IF COALESCE(p_set_labels, false) THEN
        FOREACH v_id IN ARRAY v_ids LOOP
            PERFORM public.run_mgmt_replace_labels(
                p_team_id, 'script_result', v_id, p_label_ids, p_host_names, p_actor, p_device_keys);
        END LOOP;
    END IF;

    RETURN jsonb_build_object(
        'script_result_ids', to_jsonb(v_ids),
        'updated', cardinality(v_ids)
    );
END;
$$;

REVOKE ALL ON FUNCTION public.run_mgmt_replace_labels(UUID, TEXT, UUID, UUID[], TEXT[], TEXT, TEXT[])
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.run_mgmt_replace_labels(UUID, TEXT, UUID, UUID[], TEXT[], TEXT, TEXT[])
    TO service_role;
REVOKE ALL ON FUNCTION public.run_mgmt_assign_script_results(
    UUID, UUID[], TEXT[], BOOLEAN, UUID, BOOLEAN, UUID, BOOLEAN, UUID[], TEXT, TEXT[])
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.run_mgmt_assign_script_results(
    UUID, UUID[], TEXT[], BOOLEAN, UUID, BOOLEAN, UUID, BOOLEAN, UUID[], TEXT, TEXT[])
    TO service_role;

-- ----------------------------------------------------------------------------
-- RLS for the governance tables: service_role only, browser roles hold nothing
-- (049/050 posture). The server is the data plane and enforces team + host scope.
-- ----------------------------------------------------------------------------
DO $$
DECLARE
    t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY[
        'run_groups', 'run_milestones', 'run_label_definitions',
        'script_result_labels', 'testcase_labels', 'run_group_rerun_requests'
    ] LOOP
        EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', 'service_role_all_' || t, t);
        EXECUTE format(
            'CREATE POLICY %I ON public.%I FOR ALL TO service_role USING (true) WITH CHECK (true)',
            'service_role_all_' || t, t);
        EXECUTE format('REVOKE ALL ON public.%I FROM anon, authenticated', t);
        EXECUTE format('GRANT ALL ON public.%I TO service_role', t);
    END LOOP;
END$$;

-- ============================================================================
-- defects — local-first test-result defects. integration = 'local' until an
-- explicit Jira push succeeds; then 'jira' + external_key. Resolving a defect
-- never touches script_results (discard, verdict and evidence stay as recorded).
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.defects (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    team_id             UUID NOT NULL REFERENCES public.teams(id) ON DELETE CASCADE,
    title               TEXT NOT NULL CHECK (length(btrim(title)) BETWEEN 1 AND 200),
    description         TEXT CHECK (description IS NULL OR length(description) <= 5000),
    severity            TEXT NOT NULL DEFAULT 'medium'
                        CHECK (severity IN ('low', 'medium', 'high', 'critical')),
    status              TEXT NOT NULL DEFAULT 'open'
                        CHECK (status IN ('open', 'in_progress', 'resolved', 'closed')),
    assignee            TEXT CHECK (assignee IS NULL OR length(assignee) <= 200),
    created_by          TEXT,
    integration         TEXT NOT NULL DEFAULT 'local'
                        CHECK (integration IN ('local', 'jira')),
    external_key        TEXT,
    external_url        TEXT,
    external_status     TEXT,
    external_updated_at TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT defects_team_id_id_key UNIQUE (team_id, id),
    CONSTRAINT defects_external_key_matches_integration CHECK (
        (integration = 'local' AND external_key IS NULL)
        OR (integration = 'jira' AND external_key IS NOT NULL)
    )
);

COMMENT ON TABLE public.defects IS
    'Local-first test-result defects (TASK-42). Separate from support/customer issue tracking. Status changes never modify script_results.';
COMMENT ON COLUMN public.defects.external_updated_at IS
    'Jira issue "updated" timestamp of the last applied refresh; older refresh responses are ignored (out-of-order tolerance).';

CREATE INDEX IF NOT EXISTS defects_team_status_idx ON public.defects (team_id, status, updated_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS defects_team_integration_external_unique
    ON public.defects (team_id, integration, external_key)
    WHERE external_key IS NOT NULL;

-- ============================================================================
-- defect_script_results — evidence links. Composite FKs keep defect and result
-- in the same team even for service-role writes.
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.defect_script_results (
    team_id          UUID NOT NULL,
    defect_id        UUID NOT NULL,
    script_result_id UUID NOT NULL,
    linked_by        TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (team_id, defect_id, script_result_id),
    CONSTRAINT defect_script_results_defect_fk
        FOREIGN KEY (team_id, defect_id)
        REFERENCES public.defects (team_id, id) ON DELETE CASCADE,
    CONSTRAINT defect_script_results_result_fk
        FOREIGN KEY (team_id, script_result_id)
        REFERENCES public.script_results (team_id, id) ON DELETE CASCADE
);

COMMENT ON TABLE public.defect_script_results IS
    'Defect -> script_result evidence links (one defect may cover many failed attempts).';

CREATE INDEX IF NOT EXISTS defect_script_results_result_idx
    ON public.defect_script_results (team_id, script_result_id);

-- ============================================================================
-- run_share_snapshots — sanitized, revocable share of one run summary. Only the
-- SHA-256 of the bearer token is stored; lookup requires id AND hash.
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.run_share_snapshots (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    team_id           UUID NOT NULL REFERENCES public.teams(id) ON DELETE CASCADE,
    creator_id        TEXT,
    run_kind          TEXT NOT NULL CHECK (run_kind IN ('script', 'campaign', 'group')),
    run_id            UUID NOT NULL,
    sanitized_payload JSONB NOT NULL CHECK (jsonb_typeof(sanitized_payload) = 'object'),
    token_hash        TEXT NOT NULL CHECK (token_hash ~ '^[0-9a-f]{64}$'),
    expires_at        TIMESTAMPTZ NOT NULL,
    revoked_at        TIMESTAMPTZ,
    revoked_by        TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT run_share_snapshots_ttl_check
        CHECK (expires_at > created_at AND expires_at <= created_at + INTERVAL '90 days'),
    CONSTRAINT run_share_snapshots_token_hash_key UNIQUE (token_hash)
);

COMMENT ON TABLE public.run_share_snapshots IS
    'Sanitized allowlisted snapshot of a run summary for token-only reading. No plaintext token is stored.';

CREATE INDEX IF NOT EXISTS run_share_snapshots_team_run_idx
    ON public.run_share_snapshots (team_id, run_kind, run_id, created_at DESC);

-- ============================================================================
-- custom_reports — private saved report (creator within team). The filter is a
-- versioned, server-validated structure; never SQL.
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.custom_reports (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    team_id        UUID NOT NULL REFERENCES public.teams(id) ON DELETE CASCADE,
    created_by     TEXT NOT NULL CHECK (length(created_by) BETWEEN 1 AND 200),
    name           TEXT NOT NULL CHECK (length(btrim(name)) BETWEEN 1 AND 120),
    schema_version INTEGER NOT NULL CHECK (schema_version >= 1),
    filter         JSONB NOT NULL CHECK (jsonb_typeof(filter) = 'object'),
    columns        JSONB NOT NULL DEFAULT '[]'::jsonb CHECK (jsonb_typeof(columns) = 'array'),
    chart          JSONB NOT NULL DEFAULT '{"type": "none"}'::jsonb CHECK (jsonb_typeof(chart) = 'object'),
    created_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE public.custom_reports IS
    'Saved custom report, private to created_by within team_id. filter is revalidated on load and execute.';

CREATE INDEX IF NOT EXISTS custom_reports_team_creator_idx
    ON public.custom_reports (team_id, created_by, updated_at DESC);

-- ============================================================================
-- manual_sessions — resumable manual run. testcase_snapshot is the definition
-- copied at creation; finalize (rm_finalize_manual_session) writes exactly one
-- script_results row (script_type = 'manual') and links it here.
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.manual_sessions (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    team_id            UUID NOT NULL REFERENCES public.teams(id) ON DELETE CASCADE,
    actor_id           TEXT NOT NULL,
    idempotency_key    TEXT NOT NULL CHECK (length(btrim(idempotency_key)) BETWEEN 1 AND 120),
    testcase_id        UUID,
    testcase_version   INTEGER,
    testcase_name      TEXT NOT NULL CHECK (length(btrim(testcase_name)) BETWEEN 1 AND 255),
    testcase_snapshot  JSONB NOT NULL CHECK (jsonb_typeof(testcase_snapshot) = 'object'),
    userinterface_name TEXT,
    environment        VARCHAR(10) NOT NULL DEFAULT 'prod' CHECK (environment IN ('dev', 'test', 'prod')),
    host_name          TEXT NOT NULL,
    device_name        TEXT NOT NULL,
    status             TEXT NOT NULL DEFAULT 'in_progress'
                       CHECK (status IN ('in_progress', 'finalized', 'abandoned')),
    optimistic_version INTEGER NOT NULL DEFAULT 1 CHECK (optimistic_version >= 1),
    notes              TEXT CHECK (notes IS NULL OR length(notes) <= 5000),
    started_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    finalized_at       TIMESTAMPTZ,
    finalized_by       TEXT,
    script_result_id   UUID,
    CONSTRAINT manual_sessions_team_id_id_key UNIQUE (team_id, id),
    CONSTRAINT manual_sessions_team_idempotency_key UNIQUE (team_id, idempotency_key),
    CONSTRAINT manual_sessions_testcase_fk
        FOREIGN KEY (team_id, testcase_id)
        REFERENCES public.testcase_definitions (team_id, testcase_id)
        ON DELETE SET NULL (testcase_id),
    CONSTRAINT manual_sessions_result_fk
        FOREIGN KEY (team_id, script_result_id)
        REFERENCES public.script_results (team_id, id)
        ON DELETE SET NULL (script_result_id),
    CONSTRAINT manual_sessions_finalized_shape CHECK (
        (status = 'finalized') = (finalized_at IS NOT NULL)
    )
);

COMMENT ON TABLE public.manual_sessions IS
    'Resumable manual run (TASK-42). Optimistic concurrency via optimistic_version; exactly one script_results row on finalize.';
COMMENT ON COLUMN public.manual_sessions.host_name IS
    'Registered host the manual run was performed on; scoped readers filter script_results by it.';

CREATE INDEX IF NOT EXISTS manual_sessions_team_actor_idx
    ON public.manual_sessions (team_id, actor_id, started_at DESC);
CREATE UNIQUE INDEX IF NOT EXISTS manual_sessions_team_result_unique
    ON public.manual_sessions (team_id, script_result_id)
    WHERE script_result_id IS NOT NULL;

-- ============================================================================
-- manual_session_steps — per-step human outcome; evidence optional.
-- ============================================================================
CREATE TABLE IF NOT EXISTS public.manual_session_steps (
    team_id      UUID NOT NULL,
    session_id   UUID NOT NULL,
    ordinal      INTEGER NOT NULL CHECK (ordinal >= 0),
    label        TEXT NOT NULL CHECK (length(btrim(label)) BETWEEN 1 AND 500),
    required     BOOLEAN NOT NULL DEFAULT true,
    expected     TEXT CHECK (expected IS NULL OR length(expected) <= 1000),
    outcome      TEXT CHECK (outcome IS NULL OR outcome IN ('passed', 'failed', 'skipped', 'blocked')),
    note         TEXT CHECK (note IS NULL OR length(note) <= 2000),
    evidence_url TEXT CHECK (evidence_url IS NULL OR (length(evidence_url) <= 2000 AND evidence_url ~ '^https?://')),
    updated_by   TEXT,
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (team_id, session_id, ordinal),
    CONSTRAINT manual_session_steps_session_fk
        FOREIGN KEY (team_id, session_id)
        REFERENCES public.manual_sessions (team_id, id) ON DELETE CASCADE
);

COMMENT ON TABLE public.manual_session_steps IS
    'Per-step outcome for a manual session. NULL evidence_url = no evidence supplied (shown as missing).';

-- ============================================================================
-- Row Level Security — service_role only on the new tables, matching the
-- TASK-10 / ai_routing / ai_decisions posture.
-- ============================================================================
ALTER TABLE public.run_groups              ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.run_milestones          ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.run_label_definitions   ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.script_result_labels    ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.testcase_labels         ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.defects                 ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.defect_script_results   ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.run_share_snapshots     ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.custom_reports          ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.manual_sessions         ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.manual_session_steps    ENABLE ROW LEVEL SECURITY;

-- Drop any pre-existing service_role policy (idempotent), then create.
DO $$
DECLARE
    t TEXT;
    p TEXT;
    tables TEXT[] := ARRAY[
        'run_groups', 'run_milestones', 'run_label_definitions',
        'script_result_labels', 'testcase_labels',
        'defects', 'defect_script_results',
        'run_share_snapshots', 'custom_reports',
        'manual_sessions', 'manual_session_steps'
    ];
BEGIN
    FOREACH t IN ARRAY tables LOOP
        p := 'service_role_all_' || t;
        EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', p, t);
        EXECUTE format(
            'CREATE POLICY %I ON public.%I FOR ALL TO service_role USING (true) WITH CHECK (true)',
            p, t
        );
        EXECUTE format('REVOKE ALL ON public.%I FROM anon, authenticated', t);
    END LOOP;
END$$;

-- ============================================================================
-- Run services (defects/Jira, quality, report query, manual) — tables and SQL
-- functions added after the governance sections. Every function takes the
-- team and this server's host list explicitly; none is callable by anon or
-- authenticated (the backend calls them with the service role).
-- ============================================================================

-- defect_jira_pushes — durable push attempt recorded BEFORE the external call so
-- a retry after a timeout reconciles (search by correlation label) instead of
-- creating a second issue. One row per defect.
CREATE TABLE IF NOT EXISTS public.defect_jira_pushes (
    team_id           UUID NOT NULL,
    defect_id         UUID NOT NULL,
    instance_id       TEXT NOT NULL,
    project_key       TEXT NOT NULL,
    correlation_label TEXT NOT NULL,
    state             TEXT NOT NULL DEFAULT 'pending' CHECK (state IN ('pending', 'created', 'failed')),
    attempts          INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    lease_until       TIMESTAMPTZ,
    external_key      TEXT,
    external_url      TEXT,
    last_error        TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (team_id, defect_id),
    CONSTRAINT defect_jira_pushes_defect_fk
        FOREIGN KEY (team_id, defect_id)
        REFERENCES public.defects (team_id, id) ON DELETE CASCADE,
    CONSTRAINT defect_jira_pushes_created_shape
        CHECK ((state = 'created') = (external_key IS NOT NULL))
);

COMMENT ON TABLE public.defect_jira_pushes IS
    'Jira push state machine per defect: pending (lease while in flight) -> created | failed. Retries reconcile by correlation_label first.';

-- RLS for every run-services table (idempotent; service_role only).
DO $$
DECLARE
    t TEXT;
    p TEXT;
    tables TEXT[] := ARRAY[
        'defects', 'defect_script_results', 'defect_jira_pushes',
        'run_share_snapshots', 'custom_reports',
        'manual_sessions', 'manual_session_steps'
    ];
BEGIN
    FOREACH t IN ARRAY tables LOOP
        EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', t);
        p := 'service_role_all_' || t;
        EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', p, t);
        EXECUTE format(
            'CREATE POLICY %I ON public.%I FOR ALL TO service_role USING (true) WITH CHECK (true)',
            p, t
        );
        EXECUTE format('REVOKE ALL ON public.%I FROM anon, authenticated', t);
    END LOOP;
END$$;

-- ---------------------------------------------------------------------------
-- rm_eligible_attempts — the analytics population: one team, this server's
-- hosts, optional workspace device keys ('host:device'), [since, until),
-- not discarded, terminal (passed, or failed with a recorded duration).
-- Rows still running carry success=false and no execution_time_ms; they are
-- nonterminal and excluded.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.rm_eligible_attempts(
    p_team_id     UUID,
    p_host_names  TEXT[],
    p_device_keys TEXT[],
    p_since       TIMESTAMPTZ,
    p_until       TIMESTAMPTZ
) RETURNS TABLE (
    id                 UUID,
    script_name        TEXT,
    script_type        TEXT,
    userinterface_name TEXT,
    environment        TEXT,
    host_name          TEXT,
    device_name        TEXT,
    success            BOOLEAN,
    execution_time_ms  INTEGER,
    started_at         TIMESTAMPTZ
)
LANGUAGE sql STABLE
SET search_path = public, pg_temp
AS $$
    SELECT sr.id, sr.script_name, sr.script_type, sr.userinterface_name,
           sr.environment::text, sr.host_name, sr.device_name,
           sr.success, sr.execution_time_ms, sr.started_at
    FROM public.script_results sr
    WHERE sr.team_id = p_team_id
      AND sr.host_name = ANY (COALESCE(p_host_names, ARRAY[]::text[]))
      AND (p_device_keys IS NULL OR (sr.host_name || ':' || sr.device_name) = ANY (p_device_keys))
      AND sr.started_at >= p_since
      AND sr.started_at < p_until
      AND sr.discard IS NOT TRUE
      AND (sr.success OR sr.execution_time_ms IS NOT NULL)
$$;

-- ---------------------------------------------------------------------------
-- rm_quality_flaky — per comparable identity (script_name, script_type, UI,
-- environment, host, device): attempts, passes, fails and adjacent
-- pass<->fail transitions ordered by (started_at, id).
-- score = transitions / (attempts - 1). Only identities with at least
-- p_min_attempts attempts are returned; is_flaky = at least one pass and one
-- fail. Different devices/environments are different identities by design.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.rm_quality_flaky(
    p_team_id      UUID,
    p_host_names   TEXT[],
    p_device_keys  TEXT[],
    p_since        TIMESTAMPTZ,
    p_until        TIMESTAMPTZ,
    p_min_attempts INTEGER DEFAULT 5
) RETURNS TABLE (
    script_name        TEXT,
    script_type        TEXT,
    userinterface_name TEXT,
    environment        TEXT,
    host_name          TEXT,
    device_name        TEXT,
    attempts           INTEGER,
    passes             INTEGER,
    fails              INTEGER,
    transitions        INTEGER,
    flaky_score        NUMERIC,
    is_flaky           BOOLEAN,
    first_started_at   TIMESTAMPTZ,
    last_started_at    TIMESTAMPTZ,
    last_result_id     UUID,
    last_status        TEXT
)
LANGUAGE sql STABLE
SET search_path = public, pg_temp
AS $$
    WITH ordered AS (
        SELECT a.*,
               lag(a.success) OVER w AS prev_success,
               row_number() OVER (PARTITION BY a.script_name, a.script_type, a.userinterface_name,
                                               a.environment, a.host_name, a.device_name
                                  ORDER BY a.started_at DESC, a.id DESC) AS recency
        FROM public.rm_eligible_attempts(p_team_id, p_host_names, p_device_keys, p_since, p_until) a
        WINDOW w AS (PARTITION BY a.script_name, a.script_type, a.userinterface_name,
                                  a.environment, a.host_name, a.device_name
                     ORDER BY a.started_at, a.id)
    ), grouped AS (
        SELECT o.script_name, o.script_type, o.userinterface_name, o.environment,
               o.host_name, o.device_name,
               count(*)::int AS attempts,
               count(*) FILTER (WHERE o.success)::int AS passes,
               count(*) FILTER (WHERE NOT o.success)::int AS fails,
               count(*) FILTER (WHERE o.prev_success IS NOT NULL
                                  AND o.prev_success <> o.success)::int AS transitions,
               min(o.started_at) AS first_started_at,
               max(o.started_at) AS last_started_at,
               (array_agg(o.id) FILTER (WHERE o.recency = 1))[1] AS last_result_id,
               (array_agg(CASE WHEN o.success THEN 'passed' ELSE 'failed' END) FILTER (WHERE o.recency = 1))[1] AS last_status
        FROM ordered o
        GROUP BY o.script_name, o.script_type, o.userinterface_name, o.environment,
                 o.host_name, o.device_name
        HAVING count(*) >= GREATEST(COALESCE(p_min_attempts, 5), 2)
    )
    SELECT g.script_name, g.script_type, g.userinterface_name, g.environment,
           g.host_name, g.device_name, g.attempts, g.passes, g.fails, g.transitions,
           round(g.transitions::numeric / (g.attempts - 1), 4) AS flaky_score,
           (g.passes > 0 AND g.fails > 0) AS is_flaky,
           g.first_started_at, g.last_started_at, g.last_result_id, g.last_status
    FROM grouped g
    ORDER BY 11 DESC, g.attempts DESC, g.script_name
$$;

-- ---------------------------------------------------------------------------
-- rm_quality_slow — p50/p95 of execution_time_ms over successful terminal
-- attempts per identity, nearest-rank method (percentile_disc: the smallest
-- value whose cumulative share >= p, i.e. the ceil(p*N)-th ordered value).
-- Manual runs are excluded (human durations are not comparable).
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.rm_quality_slow(
    p_team_id     UUID,
    p_host_names  TEXT[],
    p_device_keys TEXT[],
    p_since       TIMESTAMPTZ,
    p_until       TIMESTAMPTZ,
    p_min_samples INTEGER DEFAULT 5
) RETURNS TABLE (
    script_name        TEXT,
    script_type        TEXT,
    userinterface_name TEXT,
    environment        TEXT,
    host_name          TEXT,
    device_name        TEXT,
    samples            INTEGER,
    p50_ms             INTEGER,
    p95_ms             INTEGER,
    max_ms             INTEGER,
    last_started_at    TIMESTAMPTZ,
    last_result_id     UUID
)
LANGUAGE sql STABLE
SET search_path = public, pg_temp
AS $$
    SELECT a.script_name, a.script_type, a.userinterface_name, a.environment,
           a.host_name, a.device_name,
           count(*)::int AS samples,
           (percentile_disc(0.5) WITHIN GROUP (ORDER BY a.execution_time_ms))::int AS p50_ms,
           (percentile_disc(0.95) WITHIN GROUP (ORDER BY a.execution_time_ms))::int AS p95_ms,
           max(a.execution_time_ms)::int AS max_ms,
           max(a.started_at) AS last_started_at,
           (array_agg(a.id ORDER BY a.started_at DESC, a.id DESC))[1] AS last_result_id
    FROM public.rm_eligible_attempts(p_team_id, p_host_names, p_device_keys, p_since, p_until) a
    WHERE a.success
      AND a.execution_time_ms IS NOT NULL
      AND a.script_type <> 'manual'
    GROUP BY a.script_name, a.script_type, a.userinterface_name, a.environment,
             a.host_name, a.device_name
    HAVING count(*) >= GREATEST(COALESCE(p_min_samples, 5), 1)
    ORDER BY 9 DESC, a.script_name
$$;

-- ---------------------------------------------------------------------------
-- rm_executed_script_names — distinct script names with at least one eligible
-- attempt in the window (input of the "not executed in window" anti-join).
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.rm_executed_script_names(
    p_team_id     UUID,
    p_host_names  TEXT[],
    p_device_keys TEXT[],
    p_since       TIMESTAMPTZ,
    p_until       TIMESTAMPTZ
) RETURNS TABLE (
    script_name     TEXT,
    attempts        INTEGER,
    last_started_at TIMESTAMPTZ
)
LANGUAGE sql STABLE
SET search_path = public, pg_temp
AS $$
    SELECT a.script_name, count(*)::int, max(a.started_at)
    FROM public.rm_eligible_attempts(p_team_id, p_host_names, p_device_keys, p_since, p_until) a
    GROUP BY a.script_name
$$;

-- ---------------------------------------------------------------------------
-- rm_run_query — validated report query. Applies scope + every filter BEFORE
-- counting, charting and paginating, so table, counters, chart and export
-- share one filter model. Repeated keys combine with AND (= ALL). Status is
-- derived from evidence: passed (success), failed (finished with a duration),
-- unknown (no terminal evidence).
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.rm_run_query(
    p_team_id           UUID,
    p_host_names        TEXT[],
    p_device_keys       TEXT[],
    p_since             TIMESTAMPTZ,
    p_until             TIMESTAMPTZ,
    p_scripts           TEXT[],
    p_hosts             TEXT[],
    p_devices           TEXT[],
    p_uis               TEXT[],
    p_envs              TEXT[],
    p_statuses          TEXT[],
    p_milestone_ids     UUID[],
    p_label_ids         UUID[],
    p_flaky_only        BOOLEAN,
    p_include_discarded BOOLEAN,
    p_sort              TEXT,
    p_desc              BOOLEAN,
    p_limit             INTEGER,
    p_offset            INTEGER,
    p_chart             TEXT
) RETURNS JSONB
LANGUAGE sql STABLE
SET search_path = public, pg_temp
AS $$
    WITH base AS (
        SELECT sr.id, sr.script_name, sr.script_type, sr.userinterface_name,
               sr.environment::text AS environment, sr.host_name, sr.device_name,
               sr.success, sr.execution_time_ms, sr.started_at, sr.completed_at,
               COALESCE(sr.discard, false) AS discard, sr.milestone_id, sr.run_group_id,
               CASE WHEN sr.success THEN 'passed'
                    WHEN sr.execution_time_ms IS NOT NULL THEN 'failed'
                    ELSE 'unknown' END AS status
        FROM public.script_results sr
        WHERE sr.team_id = p_team_id
          AND sr.host_name = ANY (COALESCE(p_host_names, ARRAY[]::text[]))
          AND (p_device_keys IS NULL OR (sr.host_name || ':' || sr.device_name) = ANY (p_device_keys))
          AND sr.started_at >= p_since
          AND sr.started_at < p_until
          AND (COALESCE(p_include_discarded, false) OR sr.discard IS NOT TRUE)
          AND (p_scripts IS NULL OR NOT EXISTS (
                SELECT 1 FROM unnest(p_scripts) t(term)
                WHERE NOT CASE WHEN right(t.term, 1) = '*'
                               THEN starts_with(lower(sr.script_name), lower(left(t.term, -1)))
                               ELSE lower(sr.script_name) = lower(t.term) END))
          AND (p_hosts IS NULL OR sr.host_name = ALL (p_hosts))
          AND (p_devices IS NULL OR sr.device_name = ALL (p_devices))
          AND (p_uis IS NULL OR lower(sr.userinterface_name) = ALL (p_uis))
          AND (p_envs IS NULL OR sr.environment::text = ALL (p_envs))
          AND (p_milestone_ids IS NULL OR sr.milestone_id = ALL (p_milestone_ids))
          AND (p_label_ids IS NULL OR (
                SELECT count(DISTINCT l.run_label_id)
                FROM public.script_result_labels l
                WHERE l.team_id = p_team_id
                  AND l.script_result_id = sr.id
                  AND l.run_label_id = ANY (p_label_ids)) = cardinality(ARRAY(SELECT DISTINCT unnest(p_label_ids))))
    ), flaky AS (
        SELECT f.script_name, f.script_type, f.userinterface_name, f.environment, f.host_name, f.device_name
        FROM public.rm_quality_flaky(p_team_id, p_host_names, p_device_keys, p_since, p_until, 5) f
        WHERE f.is_flaky AND COALESCE(p_flaky_only, false)
    ), filtered AS (
        SELECT b.* FROM base b
        WHERE (p_statuses IS NULL OR b.status = ALL (p_statuses))
          AND (NOT COALESCE(p_flaky_only, false) OR EXISTS (
                SELECT 1 FROM flaky f
                WHERE f.script_name = b.script_name
                  AND f.script_type = b.script_type
                  AND f.userinterface_name IS NOT DISTINCT FROM b.userinterface_name
                  AND f.environment = b.environment
                  AND f.host_name = b.host_name
                  AND f.device_name = b.device_name))
    ), page AS (
        SELECT f.* FROM filtered f
        ORDER BY
            CASE WHEN p_sort = 'started_at' AND p_desc THEN f.started_at END DESC NULLS LAST,
            CASE WHEN p_sort = 'started_at' AND NOT p_desc THEN f.started_at END ASC NULLS LAST,
            CASE WHEN p_sort = 'script_name' AND p_desc THEN f.script_name END DESC NULLS LAST,
            CASE WHEN p_sort = 'script_name' AND NOT p_desc THEN f.script_name END ASC NULLS LAST,
            CASE WHEN p_sort = 'execution_time_ms' AND p_desc THEN f.execution_time_ms END DESC NULLS LAST,
            CASE WHEN p_sort = 'execution_time_ms' AND NOT p_desc THEN f.execution_time_ms END ASC NULLS LAST,
            CASE WHEN p_sort = 'status' AND p_desc THEN f.status END DESC NULLS LAST,
            CASE WHEN p_sort = 'status' AND NOT p_desc THEN f.status END ASC NULLS LAST,
            f.started_at DESC, f.id DESC
        LIMIT GREATEST(LEAST(COALESCE(p_limit, 50), 500), 1)
        OFFSET GREATEST(COALESCE(p_offset, 0), 0)
    ), days AS (
        SELECT d::date AS day
        FROM generate_series(
            date_trunc('day', p_since AT TIME ZONE 'UTC'),
            date_trunc('day', (p_until - INTERVAL '1 microsecond') AT TIME ZONE 'UTC'),
            INTERVAL '1 day') d
        WHERE p_chart = 'status_by_day'
    )
    SELECT jsonb_build_object(
        'total', (SELECT count(*) FROM filtered),
        'counts', jsonb_build_object(
            'passed', (SELECT count(*) FROM filtered WHERE status = 'passed'),
            'failed', (SELECT count(*) FROM filtered WHERE status = 'failed'),
            'unknown', (SELECT count(*) FROM filtered WHERE status = 'unknown')),
        'rows', COALESCE((SELECT jsonb_agg(to_jsonb(p.*)) FROM page p), '[]'::jsonb),
        'series', CASE
            WHEN p_chart = 'status_share' THEN jsonb_build_array(jsonb_build_object(
                'x', 'all',
                'passed', (SELECT count(*) FROM filtered WHERE status = 'passed'),
                'failed', (SELECT count(*) FROM filtered WHERE status = 'failed'),
                'other', (SELECT count(*) FROM filtered WHERE status = 'unknown')))
            WHEN p_chart = 'status_by_day' THEN COALESCE((
                SELECT jsonb_agg(jsonb_build_object(
                    'x', to_char(d.day, 'YYYY-MM-DD'),
                    'passed', COALESCE(c.passed, 0),
                    'failed', COALESCE(c.failed, 0),
                    'other', COALESCE(c.other, 0)) ORDER BY d.day)
                FROM days d
                LEFT JOIN (
                    SELECT (f.started_at AT TIME ZONE 'UTC')::date AS day,
                           count(*) FILTER (WHERE f.status = 'passed') AS passed,
                           count(*) FILTER (WHERE f.status = 'failed') AS failed,
                           count(*) FILTER (WHERE f.status = 'unknown') AS other
                    FROM filtered f GROUP BY 1) c ON c.day = d.day), '[]'::jsonb)
            WHEN p_chart IN ('group:script_name', 'group:host_name', 'group:device_name',
                             'group:userinterface_name', 'group:environment') THEN COALESCE((
                SELECT jsonb_agg(jsonb_build_object(
                    'x', g.x, 'passed', g.passed, 'failed', g.failed, 'other', g.other)
                    ORDER BY g.total DESC, g.x)
                FROM (
                    SELECT COALESCE(CASE p_chart
                               WHEN 'group:script_name' THEN f.script_name
                               WHEN 'group:host_name' THEN f.host_name
                               WHEN 'group:device_name' THEN f.device_name
                               WHEN 'group:userinterface_name' THEN f.userinterface_name
                               ELSE f.environment END, '') AS x,
                           count(*) FILTER (WHERE f.status = 'passed') AS passed,
                           count(*) FILTER (WHERE f.status = 'failed') AS failed,
                           count(*) FILTER (WHERE f.status = 'unknown') AS other,
                           count(*) AS total
                    FROM filtered f GROUP BY 1
                    ORDER BY count(*) DESC, 1
                    LIMIT 20) g), '[]'::jsonb)
            ELSE '[]'::jsonb END
    )
$$;

-- ---------------------------------------------------------------------------
-- rm_claim_defect_jira_push — record/claim a push attempt before any external
-- call. Returns claimed=false when already created, when another attempt holds
-- an unexpired lease, or when an earlier attempt targeted a different Jira
-- instance/project. reconcile=true tells the caller to search Jira by the
-- correlation label before creating (an earlier attempt may have succeeded).
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.rm_claim_defect_jira_push(
    p_team_id       UUID,
    p_defect_id     UUID,
    p_instance_id   TEXT,
    p_project_key   TEXT,
    p_lease_seconds INTEGER DEFAULT 120
) RETURNS JSONB
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
DECLARE
    v_push public.defect_jira_pushes%ROWTYPE;
BEGIN
    PERFORM 1 FROM public.defects d
    WHERE d.team_id = p_team_id AND d.id = p_defect_id
    FOR UPDATE;
    IF NOT FOUND THEN
        RETURN jsonb_build_object('claimed', false, 'reason', 'not_found');
    END IF;

    INSERT INTO public.defect_jira_pushes (team_id, defect_id, instance_id, project_key, correlation_label)
    VALUES (p_team_id, p_defect_id, p_instance_id, p_project_key, 'vpt-defect-' || p_defect_id::text)
    ON CONFLICT (team_id, defect_id) DO NOTHING;

    SELECT * INTO v_push FROM public.defect_jira_pushes
    WHERE team_id = p_team_id AND defect_id = p_defect_id
    FOR UPDATE;

    IF v_push.state = 'created' THEN
        RETURN jsonb_build_object('claimed', false, 'reason', 'already_created',
            'external_key', v_push.external_key, 'external_url', v_push.external_url,
            'correlation_label', v_push.correlation_label);
    END IF;
    IF v_push.instance_id <> p_instance_id OR v_push.project_key <> p_project_key THEN
        RETURN jsonb_build_object('claimed', false, 'reason', 'target_mismatch',
            'instance_id', v_push.instance_id, 'project_key', v_push.project_key);
    END IF;
    IF v_push.lease_until IS NOT NULL AND v_push.lease_until > now() THEN
        RETURN jsonb_build_object('claimed', false, 'reason', 'in_flight',
            'lease_until', v_push.lease_until);
    END IF;

    UPDATE public.defect_jira_pushes
    SET attempts = attempts + 1,
        state = 'pending',
        lease_until = now() + make_interval(secs => GREATEST(COALESCE(p_lease_seconds, 120), 1)),
        updated_at = now()
    WHERE team_id = p_team_id AND defect_id = p_defect_id;

    RETURN jsonb_build_object('claimed', true,
        'attempt', v_push.attempts + 1,
        'reconcile', v_push.attempts > 0,
        'correlation_label', v_push.correlation_label,
        'instance_id', v_push.instance_id,
        'project_key', v_push.project_key);
END;
$$;

-- rm_complete_defect_jira_push — mark created and link the defect, atomically.
CREATE OR REPLACE FUNCTION public.rm_complete_defect_jira_push(
    p_team_id      UUID,
    p_defect_id    UUID,
    p_external_key TEXT,
    p_external_url TEXT
) RETURNS BOOLEAN
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
BEGIN
    UPDATE public.defect_jira_pushes
    SET state = 'created', external_key = p_external_key, external_url = p_external_url,
        lease_until = NULL, last_error = NULL, updated_at = now()
    WHERE team_id = p_team_id AND defect_id = p_defect_id;
    IF NOT FOUND THEN
        RETURN false;
    END IF;
    UPDATE public.defects
    SET integration = 'jira', external_key = p_external_key, external_url = p_external_url,
        updated_at = now()
    WHERE team_id = p_team_id AND id = p_defect_id;
    RETURN FOUND;
END;
$$;

-- rm_fail_defect_jira_push — record a failure. p_release_lease=false keeps the
-- lease when the outcome is unknown (timeout), so an immediate retry cannot
-- race Jira's search indexing; the retry then reconciles first.
CREATE OR REPLACE FUNCTION public.rm_fail_defect_jira_push(
    p_team_id       UUID,
    p_defect_id     UUID,
    p_error         TEXT,
    p_release_lease BOOLEAN
) RETURNS BOOLEAN
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
BEGIN
    UPDATE public.defect_jira_pushes
    SET state = 'failed',
        last_error = left(COALESCE(p_error, ''), 500),
        lease_until = CASE WHEN p_release_lease THEN NULL ELSE lease_until END,
        updated_at = now()
    WHERE team_id = p_team_id AND defect_id = p_defect_id AND state <> 'created';
    RETURN FOUND;
END;
$$;

-- ---------------------------------------------------------------------------
-- Manual sessions: atomic create (idempotent by key), step update with
-- optimistic concurrency, and exactly-once finalize under a row lock.
-- Errors use SQLSTATE P0001 with a stable message prefix the server maps:
--   'rm:not_found', 'rm:version_conflict', 'rm:not_in_progress',
--   'rm:incomplete', 'rm:bad_step'.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.rm_create_manual_session(
    p_team_id            UUID,
    p_actor_id           TEXT,
    p_idempotency_key    TEXT,
    p_testcase_id        UUID,
    p_testcase_version   INTEGER,
    p_testcase_name      TEXT,
    p_testcase_snapshot  JSONB,
    p_userinterface_name TEXT,
    p_environment        TEXT,
    p_host_name          TEXT,
    p_device_name        TEXT,
    p_steps              JSONB
) RETURNS JSONB
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
DECLARE
    v_id UUID;
    v_existing public.manual_sessions%ROWTYPE;
    v_step JSONB;
    v_ordinal INTEGER := 0;
BEGIN
    INSERT INTO public.manual_sessions (
        team_id, actor_id, idempotency_key, testcase_id, testcase_version, testcase_name,
        testcase_snapshot, userinterface_name, environment, host_name, device_name)
    VALUES (
        p_team_id, p_actor_id, btrim(p_idempotency_key), p_testcase_id, p_testcase_version,
        p_testcase_name, p_testcase_snapshot, p_userinterface_name, p_environment,
        p_host_name, p_device_name)
    ON CONFLICT (team_id, idempotency_key) DO NOTHING
    RETURNING id INTO v_id;

    IF v_id IS NULL THEN
        SELECT * INTO v_existing FROM public.manual_sessions
        WHERE team_id = p_team_id AND idempotency_key = btrim(p_idempotency_key);
        RETURN jsonb_build_object('id', v_existing.id, 'created', false,
                                  'actor_id', v_existing.actor_id);
    END IF;

    FOR v_step IN SELECT * FROM jsonb_array_elements(COALESCE(p_steps, '[]'::jsonb)) LOOP
        INSERT INTO public.manual_session_steps (team_id, session_id, ordinal, label, expected, required)
        VALUES (p_team_id, v_id, v_ordinal, v_step->>'label', v_step->>'expected',
                COALESCE((v_step->>'required')::boolean, true));
        v_ordinal := v_ordinal + 1;
    END LOOP;

    RETURN jsonb_build_object('id', v_id, 'created', true, 'actor_id', p_actor_id);
END;
$$;

CREATE OR REPLACE FUNCTION public.rm_update_manual_session(
    p_team_id          UUID,
    p_session_id       UUID,
    p_expected_version INTEGER,
    p_actor_id         TEXT,
    p_steps            JSONB,
    p_notes            TEXT,
    p_set_notes        BOOLEAN,
    p_abandon          BOOLEAN
) RETURNS INTEGER
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
DECLARE
    v_session public.manual_sessions%ROWTYPE;
    v_step JSONB;
BEGIN
    SELECT * INTO v_session FROM public.manual_sessions
    WHERE team_id = p_team_id AND id = p_session_id
    FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'rm:not_found';
    END IF;
    IF v_session.status <> 'in_progress' THEN
        RAISE EXCEPTION 'rm:not_in_progress';
    END IF;
    IF v_session.optimistic_version <> p_expected_version THEN
        RAISE EXCEPTION 'rm:version_conflict';
    END IF;

    FOR v_step IN SELECT * FROM jsonb_array_elements(COALESCE(p_steps, '[]'::jsonb)) LOOP
        UPDATE public.manual_session_steps
        SET outcome = CASE WHEN v_step ? 'outcome' THEN v_step->>'outcome' ELSE outcome END,
            note = CASE WHEN v_step ? 'note' THEN v_step->>'note' ELSE note END,
            evidence_url = CASE WHEN v_step ? 'evidence_url' THEN v_step->>'evidence_url' ELSE evidence_url END,
            updated_by = p_actor_id,
            updated_at = now()
        WHERE team_id = p_team_id AND session_id = p_session_id
          AND ordinal = (v_step->>'ordinal')::integer;
        IF NOT FOUND THEN
            RAISE EXCEPTION 'rm:bad_step %', v_step->>'ordinal';
        END IF;
    END LOOP;

    UPDATE public.manual_sessions
    SET optimistic_version = optimistic_version + 1,
        notes = CASE WHEN p_set_notes THEN p_notes ELSE notes END,
        status = CASE WHEN p_abandon THEN 'abandoned' ELSE status END,
        updated_at = now()
    WHERE team_id = p_team_id AND id = p_session_id;

    RETURN v_session.optimistic_version + 1;
END;
$$;

CREATE OR REPLACE FUNCTION public.rm_finalize_manual_session(
    p_team_id          UUID,
    p_session_id       UUID,
    p_actor_id         TEXT,
    p_expected_version INTEGER
) RETURNS JSONB
LANGUAGE plpgsql
SET search_path = public, pg_temp
AS $$
DECLARE
    v_session public.manual_sessions%ROWTYPE;
    v_total INTEGER;
    v_missing INTEGER;
    v_failed INTEGER;
    v_passed INTEGER;
    v_skipped INTEGER;
    v_blocked INTEGER;
    v_required_not_passed INTEGER;
    v_without_evidence INTEGER;
    v_success BOOLEAN;
    v_result_id UUID := gen_random_uuid();
    v_now TIMESTAMPTZ := now();
BEGIN
    SELECT * INTO v_session FROM public.manual_sessions
    WHERE team_id = p_team_id AND id = p_session_id
    FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'rm:not_found';
    END IF;

    IF v_session.status = 'finalized' THEN
        RETURN jsonb_build_object('script_result_id', v_session.script_result_id,
                                  'already_finalized', true, 'optimistic_version', v_session.optimistic_version);
    END IF;
    IF v_session.status <> 'in_progress' THEN
        RAISE EXCEPTION 'rm:not_in_progress';
    END IF;
    IF p_expected_version IS NOT NULL AND v_session.optimistic_version <> p_expected_version THEN
        RAISE EXCEPTION 'rm:version_conflict';
    END IF;

    SELECT count(*),
           count(*) FILTER (WHERE required AND outcome IS NULL),
           count(*) FILTER (WHERE outcome = 'failed'),
           count(*) FILTER (WHERE outcome = 'passed'),
           count(*) FILTER (WHERE outcome = 'skipped'),
           count(*) FILTER (WHERE outcome = 'blocked'),
           count(*) FILTER (WHERE required AND outcome IS DISTINCT FROM 'passed'),
           count(*) FILTER (WHERE outcome IS NOT NULL AND evidence_url IS NULL)
    INTO v_total, v_missing, v_failed, v_passed, v_skipped, v_blocked, v_required_not_passed, v_without_evidence
    FROM public.manual_session_steps
    WHERE team_id = p_team_id AND session_id = p_session_id;

    IF v_total = 0 THEN
        RAISE EXCEPTION 'rm:incomplete no steps';
    END IF;
    IF v_missing > 0 THEN
        RAISE EXCEPTION 'rm:incomplete % required step(s) have no outcome', v_missing;
    END IF;

    v_success := v_failed = 0 AND v_required_not_passed = 0;

    INSERT INTO public.script_results (
        id, team_id, script_name, script_type, userinterface_name, host_name, device_name,
        success, execution_time_ms, started_at, completed_at, environment, error_msg, metadata)
    VALUES (
        v_result_id, p_team_id, v_session.testcase_name, 'manual', v_session.userinterface_name,
        v_session.host_name, v_session.device_name, v_success,
        GREATEST((extract(epoch FROM (v_now - v_session.started_at)) * 1000)::bigint, 0)::integer,
        v_session.started_at, v_now, v_session.environment,
        CASE WHEN v_success THEN NULL
             ELSE format('Manual run: %s step(s) failed, %s required step(s) not passed', v_failed, v_required_not_passed) END,
        jsonb_build_object(
            'manual_session_id', p_session_id,
            'testcase_id', v_session.testcase_id,
            'testcase_version', v_session.testcase_version,
            'trigger', jsonb_build_object('type', 'manual', 'caller_user', p_actor_id),
            'manual', jsonb_build_object(
                'actor_id', v_session.actor_id,
                'finalized_by', p_actor_id,
                'steps_total', v_total,
                'steps_passed', v_passed,
                'steps_failed', v_failed,
                'steps_skipped', v_skipped,
                'steps_blocked', v_blocked,
                'steps_without_evidence', v_without_evidence)));

    UPDATE public.manual_sessions
    SET status = 'finalized', script_result_id = v_result_id, finalized_at = v_now,
        finalized_by = p_actor_id, optimistic_version = optimistic_version + 1, updated_at = v_now
    WHERE team_id = p_team_id AND id = p_session_id;

    RETURN jsonb_build_object('script_result_id', v_result_id, 'already_finalized', false,
                              'success', v_success, 'optimistic_version', v_session.optimistic_version + 1);
END;
$$;

DO $$
DECLARE
    f TEXT;
    fns TEXT[] := ARRAY[
        'public.rm_eligible_attempts(uuid, text[], text[], timestamptz, timestamptz)',
        'public.rm_quality_flaky(uuid, text[], text[], timestamptz, timestamptz, integer)',
        'public.rm_quality_slow(uuid, text[], text[], timestamptz, timestamptz, integer)',
        'public.rm_executed_script_names(uuid, text[], text[], timestamptz, timestamptz)',
        'public.rm_run_query(uuid, text[], text[], timestamptz, timestamptz, text[], text[], text[], text[], text[], text[], uuid[], uuid[], boolean, boolean, text, boolean, integer, integer, text)',
        'public.rm_claim_defect_jira_push(uuid, uuid, text, text, integer)',
        'public.rm_complete_defect_jira_push(uuid, uuid, text, text)',
        'public.rm_fail_defect_jira_push(uuid, uuid, text, boolean)',
        'public.rm_create_manual_session(uuid, text, text, uuid, integer, text, jsonb, text, text, text, text, jsonb)',
        'public.rm_update_manual_session(uuid, uuid, integer, text, jsonb, text, boolean, boolean)',
        'public.rm_finalize_manual_session(uuid, uuid, text, integer)'
    ];
BEGIN
    FOREACH f IN ARRAY fns LOOP
        EXECUTE format('REVOKE ALL ON FUNCTION %s FROM PUBLIC, anon, authenticated', f);
        EXECUTE format('GRANT EXECUTE ON FUNCTION %s TO service_role', f);
    END LOOP;
END$$;

COMMIT;