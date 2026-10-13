-- 20260928a_device_info_latest.sql
--
-- TASK-29 — device info stored once: device_info_latest, the device mirror of
-- TASK-16's gw_info_latest (20260910c).
--
-- Why: device_info_corrected (035) still derived "latest scan per device" with a
-- DISTINCT ON over EVERY get_info / device_get_info row on each read. That is the
-- same shape PostgREST's 8 s statement timeout killed for the gateway view on the
-- customer DB (BUG-0075), and the hosts listing swallows the failure
-- (device_info_overrides_db._get_corrected_map returns {} on error), so the symptom
-- is device info silently disappearing from the whole fleet rather than an error.
--
-- What: a row trigger on script_results maintains device_info_latest — one row per
-- (team, device, host), holding exactly what the former `latest` CTE produced. Both
-- device views are recreated over it with identical columns and security_invoker, so
-- the server code, the editor UI and the PostgREST contract are unchanged.
--
-- Grants / RLS: copied from script_results on the DB this runs on, so one file is
-- right on every posture. Plain SQL, one transaction (customer migration tool wraps
-- files in one; on the lab run with `psql -1 -v ON_ERROR_STOP=1`). Backfill: one pass
-- over the get_info rows, reads only. A get_info run that commits during the
-- migration is missed by the backfill and picked up by its next run.
--
-- Folded into setup/db/schema/052_device_info_latest.sql for fresh installs.
-- Rollback: 20260928a_device_info_latest_rollback.sql (restores the 035 views).

CREATE TABLE IF NOT EXISTS public.device_info_latest (
    team_id                uuid        NOT NULL REFERENCES public.teams(id) ON DELETE CASCADE,
    device_name            text        NOT NULL,
    host_name              text        NOT NULL,
    script_result_id       uuid        NOT NULL REFERENCES public.script_results(id) ON DELETE CASCADE,
    userinterface_name     text,
    started_at             timestamptz NOT NULL,
    html_report_r2_url     text,
    initial_screenshot_url text,
    final_screenshot_url   text,
    video_url              text,
    info                   jsonb       NOT NULL,
    updated_at             timestamptz NOT NULL DEFAULT timezone('utc'::text, now()),
    PRIMARY KEY (team_id, device_name, host_name)
);

CREATE INDEX IF NOT EXISTS idx_device_info_latest_team_started
    ON public.device_info_latest (team_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_device_info_latest_script_result
    ON public.device_info_latest (script_result_id);

COMMENT ON TABLE public.device_info_latest IS
    'Latest get_info / device_get_info scan carrying an info object, per (team, device, host), maintained by trg_device_info_track on script_results. info = metadata->''info'' verbatim. Source of device_info_corrected / device_info_key_status.';
COMMENT ON COLUMN public.device_info_latest.info IS
    'metadata->''info'' of the source run — free-form OCR keys, varying per UI/panel. Raw: overrides are applied at read time by device_info_corrected, never stored here.';

-- Same predicates as the former view CTE (035). script_name and device_name are
-- NOT NULL in script_results (003), but the guard is written NULL-safe anyway:
-- the primary key here cannot take a NULL device_name, and a row without one
-- could never be matched by the hosts listing (which keys on
-- (device_name, host_name)) or by the editor, so skipping it loses nothing.
CREATE OR REPLACE FUNCTION public.device_info_track()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.script_name IS NULL
       OR NEW.script_name NOT IN ('get_info', 'device_get_info')
       OR NEW.device_name IS NULL
       OR NEW.metadata IS NULL
       OR jsonb_typeof(NEW.metadata->'info') <> 'object' THEN
        RETURN NEW;
    END IF;

    INSERT INTO public.device_info_latest (
        team_id, device_name, host_name, script_result_id, userinterface_name, started_at,
        html_report_r2_url, initial_screenshot_url, final_screenshot_url, video_url, info, updated_at)
    VALUES (
        NEW.team_id, NEW.device_name, NEW.host_name, NEW.id, NEW.userinterface_name, NEW.started_at,
        NEW.html_report_r2_url,
        NEW.metadata->'report_artifacts'->>'initial_screenshot_url',
        NEW.metadata->'report_artifacts'->>'final_screenshot_url',
        NEW.metadata->'report_artifacts'->>'video_url',
        NEW.metadata->'info', timezone('utc'::text, now()))
    ON CONFLICT (team_id, device_name, host_name) DO UPDATE SET
        script_result_id       = EXCLUDED.script_result_id,
        userinterface_name     = EXCLUDED.userinterface_name,
        started_at             = EXCLUDED.started_at,
        html_report_r2_url     = EXCLUDED.html_report_r2_url,
        initial_screenshot_url = EXCLUDED.initial_screenshot_url,
        final_screenshot_url   = EXCLUDED.final_screenshot_url,
        video_url              = EXCLUDED.video_url,
        info                   = EXCLUDED.info,
        updated_at             = EXCLUDED.updated_at
    -- Out-of-order arrival must not let an older scan overwrite a newer one.
    WHERE EXCLUDED.started_at >= public.device_info_latest.started_at;

    RETURN NEW;
END
$$;

COMMENT ON FUNCTION public.device_info_track() IS
    'Maintains device_info_latest from script_results. Device mirror of gw_info_track() (046).';

-- UPDATE OF lists exactly the columns copied above: a run is inserted at start
-- and updated with its result, so `metadata` is what actually triggers the
-- upsert. Unlike the gateway trigger there is no `success` here — 035 never
-- filtered on it, and a failed run that still OCR'd an info object is the
-- latest info we have.
DROP TRIGGER IF EXISTS trg_device_info_track ON public.script_results;
CREATE TRIGGER trg_device_info_track
    AFTER INSERT OR UPDATE OF metadata, device_name, host_name, started_at,
                              userinterface_name, html_report_r2_url
    ON public.script_results
    FOR EACH ROW
    WHEN (NEW.script_name IN ('get_info', 'device_get_info'))
    EXECUTE FUNCTION public.device_info_track();

-- ---------------------------------------------------------------------------
-- Backfill from history (idempotent — same ON CONFLICT rule as the trigger).
-- Predicates and ordering are character-for-character the former `latest` CTE
-- of 035_device_info_overrides.sql, plus device_name IS NOT NULL (the primary
-- key requires it; such rows were unmatchable by every consumer anyway).
-- ---------------------------------------------------------------------------
INSERT INTO public.device_info_latest (
    team_id, device_name, host_name, script_result_id, userinterface_name, started_at,
    html_report_r2_url, initial_screenshot_url, final_screenshot_url, video_url, info, updated_at)
SELECT DISTINCT ON (sr.team_id, sr.device_name, sr.host_name)
    sr.team_id, sr.device_name, sr.host_name, sr.id, sr.userinterface_name, sr.started_at,
    sr.html_report_r2_url,
    sr.metadata->'report_artifacts'->>'initial_screenshot_url',
    sr.metadata->'report_artifacts'->>'final_screenshot_url',
    sr.metadata->'report_artifacts'->>'video_url',
    sr.metadata->'info', timezone('utc'::text, now())
FROM public.script_results sr
WHERE sr.script_name IN ('get_info', 'device_get_info')
  AND jsonb_typeof(sr.metadata->'info') = 'object'
  AND sr.device_name IS NOT NULL
ORDER BY sr.team_id, sr.device_name, sr.host_name, sr.started_at DESC
ON CONFLICT (team_id, device_name, host_name) DO UPDATE SET
    script_result_id       = EXCLUDED.script_result_id,
    userinterface_name     = EXCLUDED.userinterface_name,
    started_at             = EXCLUDED.started_at,
    html_report_r2_url     = EXCLUDED.html_report_r2_url,
    initial_screenshot_url = EXCLUDED.initial_screenshot_url,
    final_screenshot_url   = EXCLUDED.final_screenshot_url,
    video_url              = EXCLUDED.video_url,
    info                   = EXCLUDED.info,
    updated_at             = EXCLUDED.updated_at
WHERE EXCLUDED.started_at >= public.device_info_latest.started_at;

-- Views (same columns as their 035 versions; `latest` reads the table).
DROP VIEW IF EXISTS public.device_info_key_status;
DROP VIEW IF EXISTS public.device_info_corrected;

CREATE VIEW public.device_info_corrected AS
WITH latest AS (
    SELECT team_id, device_name, host_name, userinterface_name, started_at, html_report_r2_url,
           info AS info_raw, initial_screenshot_url, final_screenshot_url, video_url
    FROM public.device_info_latest
),
ov AS (
    SELECT team_id, device_name, host_name, userinterface_name,
           jsonb_object_agg(info_key, to_jsonb(corrected_value)) AS overrides
    FROM public.device_info_overrides
    WHERE info_source = 'device'
    GROUP BY team_id, device_name, host_name, userinterface_name
)
SELECT
    l.team_id, l.device_name, l.host_name, l.userinterface_name,
    l.started_at, l.html_report_r2_url,
    l.info_raw,
    COALESCE(l.info_raw || ov.overrides, l.info_raw) AS info_corrected,
    (ov.overrides IS NOT NULL) AS has_override,
    l.initial_screenshot_url, l.final_screenshot_url, l.video_url
FROM latest l
LEFT JOIN ov
    ON  ov.team_id            = l.team_id
    AND ov.device_name        = l.device_name
    AND ov.host_name          = l.host_name
    AND ov.userinterface_name IS NOT DISTINCT FROM COALESCE(l.userinterface_name, '');

CREATE VIEW public.device_info_key_status AS
WITH latest AS (
    SELECT team_id, device_name, host_name, userinterface_name, info
    FROM public.device_info_latest
),
latest_kv AS (
    SELECT l.team_id, l.device_name, l.host_name, l.userinterface_name,
           kv.key AS info_key, kv.value AS raw_value
    FROM latest l
    CROSS JOIN LATERAL jsonb_each_text(l.info) AS kv(key, value)
)
SELECT
    lk.team_id, lk.device_name, lk.host_name, lk.userinterface_name,
    lk.info_key, lk.raw_value,
    o.corrected_value                              AS override_value,
    (o.id IS NOT NULL)                             AS is_overridden,
    COALESCE(o.corrected_value, lk.raw_value)      AS effective_value,
    (o.id IS NOT NULL AND o.raw_value_at_edit IS DISTINCT FROM lk.raw_value) AS override_stale
FROM latest_kv lk
LEFT JOIN public.device_info_overrides o
    ON  o.team_id = lk.team_id AND o.device_name = lk.device_name
    AND o.host_name = lk.host_name
    AND o.userinterface_name IS NOT DISTINCT FROM COALESCE(lk.userinterface_name, '')
    AND o.info_source = 'device'
    AND o.info_key = lk.info_key;

-- Views run with the caller's privileges (Studio lint security_definer_view).
ALTER VIEW public.device_info_corrected  SET (security_invoker = on);
ALTER VIEW public.device_info_key_status SET (security_invoker = on);

COMMENT ON VIEW public.device_info_corrected IS
    'Latest device info scan per (team, device, host) from device_info_latest, with device_info_overrides (info_source=device) applied on top. Read by the hosts listing to attach device_info to each device, and by the device-information Grafana dashboard.';
COMMENT ON VIEW public.device_info_key_status IS
    'Per-key view of device_info_corrected: raw value, override value, staleness — for the correction UI.';

-- Ownership, grants, RLS and policies: same as script_results on this DB.
DO $$
DECLARE
    v_owner text := (SELECT pg_get_userbyid(relowner) FROM pg_class WHERE oid = 'public.script_results'::regclass);
    v_rls   boolean := (SELECT relrowsecurity FROM pg_class WHERE oid = 'public.script_results'::regclass);
    v_rel   text;
    r       record;
    v_sql   text;
BEGIN
    EXECUTE format('ALTER TABLE public.device_info_latest OWNER TO %I', v_owner);
    IF v_rls THEN
        EXECUTE 'ALTER TABLE public.device_info_latest ENABLE ROW LEVEL SECURITY';
    END IF;

    FOREACH v_rel IN ARRAY ARRAY['device_info_latest',
                                 'device_info_corrected', 'device_info_key_status'] LOOP
        FOR r IN
            SELECT grantee, string_agg(privilege_type, ', ') AS privs
            FROM information_schema.role_table_grants
            WHERE table_schema = 'public' AND table_name = 'script_results'
            GROUP BY grantee
        LOOP
            IF r.grantee = 'PUBLIC' THEN
                EXECUTE format('GRANT %s ON public.%I TO PUBLIC', r.privs, v_rel);
            ELSE
                EXECUTE format('GRANT %s ON public.%I TO %I', r.privs, v_rel, r.grantee);
            END IF;
        END LOOP;
    END LOOP;

    FOR r IN
        SELECT policyname, permissive, roles, cmd, qual, with_check
        FROM pg_policies WHERE schemaname = 'public' AND tablename = 'script_results'
    LOOP
        v_sql := format('CREATE POLICY %I ON public.device_info_latest AS %s FOR %s TO %s',
                        replace(r.policyname, 'script_results', 'device_info_latest'),
                        r.permissive, r.cmd, array_to_string(r.roles, ', '));
        IF r.cmd <> 'INSERT' AND r.qual IS NOT NULL THEN
            v_sql := v_sql || format(' USING (%s)', r.qual);
        END IF;
        IF r.cmd IN ('ALL', 'INSERT', 'UPDATE') AND r.with_check IS NOT NULL THEN
            v_sql := v_sql || format(' WITH CHECK (%s)', r.with_check);
        END IF;
        BEGIN
            EXECUTE v_sql;
        EXCEPTION WHEN others THEN
            RAISE NOTICE 'policy % not copied to device_info_latest: %', r.policyname, SQLERRM;
        END;
    END LOOP;
END
$$;
