-- 052 — Device info stored once (TASK-29): device_info_latest, and the two
-- device views (moved here from 035) now read the table.
--
-- The device mirror of 046_gw_info_latest.sql. `device_get_info` / `get_info`
-- OCR a device's info screen into script_results.metadata->'info'. Instead of
-- re-deriving "latest scan per device" with a DISTINCT ON over every get_info
-- row on each read — the exact shape PostgREST's 8 s statement timeout killed
-- for gateway info at ~100K rows (BUG-0075) — a row trigger on script_results
-- keeps:
--   device_info_latest — latest scan carrying an `info` object per
--                        (team, device, host); `info` = metadata->'info'.
-- Corrections still come from device_info_overrides (035, info_source='device').
-- Grants/RLS/policies mirror script_results on the DB this runs on.
--
-- Two deliberate differences from the gateway side:
--   * No `device_info_values` sibling. Gateway info has five fixed keys that
--     back Grafana filter dropdowns; device info is free-form by design (an STB
--     and an IAD share no keys — see 035), so there is nothing to enumerate.
--   * No extracted value columns, for the same reason: `info` stays opaque jsonb.
--
-- See docs/tasks/TASK-29-device-info-latest-table.md,
-- docs/agent/devices/DEVICE_INFO_CORRECTION.md.

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

-- Same predicates as the former view CTE (035), plus device_name NOT NULL which
-- the primary key requires.
--
-- The guard MUST be NULL-safe and is written with IS DISTINCT FROM / COALESCE.
-- 035 expressed this as `WHERE jsonb_typeof(metadata->'info') = 'object'`, where
-- a NULL (the key absent — the normal shape of a start record) excludes the row.
-- The first version of this trigger negated it as `<> 'object'`, which is NULL,
-- not TRUE, so it fell through and inserted info = NULL — and the NOT NULL
-- constraint then aborted the caller's script_results INSERT, losing the run
-- entirely. See 20260928c.
--
-- The upsert is wrapped so it can only warn: this table is a derived cache of
-- script_results and must never be able to break the write it observes.
CREATE OR REPLACE FUNCTION public.device_info_track()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    -- NULL-safe. `metadata->'info'` absent => jsonb_typeof is NULL =>
    -- IS DISTINCT FROM 'object' is TRUE => skip. Covers metadata IS NULL too,
    -- since NULL->'info' is NULL.
    IF COALESCE(NEW.script_name, '') NOT IN ('get_info', 'device_get_info')
       OR NEW.device_name IS NULL
       OR jsonb_typeof(NEW.metadata->'info') IS DISTINCT FROM 'object' THEN
        RETURN NEW;
    END IF;

    BEGIN
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
    EXCEPTION WHEN others THEN
        -- device_info_latest is a derived cache of script_results. Losing a row
        -- here costs one device's info panel until its next scan; aborting the
        -- caller's INSERT loses the test run itself. Never do the latter.
        RAISE WARNING '[device_info_track] skipped % (%): %', NEW.id, SQLSTATE, SQLERRM;
    END;

    RETURN NEW;
END
$$;

COMMENT ON FUNCTION public.device_info_track() IS
    'Maintains device_info_latest from script_results. Device mirror of gw_info_track() (046). Guard is NULL-safe and the upsert can only warn — it must never abort the script_results write it observes (20260928c).';

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
