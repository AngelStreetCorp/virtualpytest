-- ============================================================================
-- TASK-16 — gateway facts stored once: gw_info_latest + gw_info_values
-- ============================================================================
-- Why (BUG-0075, BUG-0074): the gateway views (036_gateway_info.sql) computed
-- "latest gw_info scan per device" with a DISTINCT ON over EVERY gw_info row,
-- subtracting each row's jsonb first. On the customer DB (93K gw_info rows)
-- that read is killed by PostgREST's 8 s statement timeout every minute, so
-- the hosts listing waits 8 s and never gets gateway info. The Grafana filter
-- variables (HGW model / firmware / MAC / access type / LAN type) rescan the
-- same rows on every dashboard load for ~50 distinct values.
--
-- What: a row trigger on script_results maintains
--   gw_info_latest  — the latest auth-successful scan per (team, device, host)
--                     (exactly what the views' `latest` CTE produced), plus the
--                     variable keys extracted as columns;
--   gw_info_values  — every value ever seen per variable kind (successful runs).
-- The two views are recreated over gw_info_latest with the same columns and
-- security_invoker, so the server code and PostgREST contract are unchanged.
--
-- Grants / RLS: copied from script_results on the DB this runs on (TASK-10
-- posture on main = RLS + service_role; anon posture on the customer), so one
-- file is right everywhere.
--
-- Plain SQL, one transaction (customer migration tool wraps files in one; on
-- the lab run with `psql -1 -v ON_ERROR_STOP=1`). Backfill: two passes over the
-- gw_info rows — seconds on the customer DB, reads only. A gw_info run that
-- commits during the migration is missed by the backfill and picked up by its
-- next run (daily).

-- ---------------------------------------------------------------------------
-- 1. Tables
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.gw_info_latest (
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
    modem_name             text,
    firmware_version       text,
    technology             text,
    network_type           text,
    cable_mac_address      text,
    pon_mac_address        text,
    wan_mac_address        text,
    serial_number          text,
    hgw_mac                text,
    updated_at             timestamptz NOT NULL DEFAULT timezone('utc'::text, now()),
    PRIMARY KEY (team_id, device_name, host_name)
);

CREATE INDEX IF NOT EXISTS idx_gw_info_latest_team_started
    ON public.gw_info_latest (team_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_gw_info_latest_script_result
    ON public.gw_info_latest (script_result_id);

COMMENT ON TABLE public.gw_info_latest IS
    'Latest auth-successful gw_info scan per (team, device, host), maintained by trg_gw_info_track on script_results. info = metadata minus operational keys (same blacklist as the former view CTE). Source of gateway_info_corrected / gateway_info_key_status.';
COMMENT ON COLUMN public.gw_info_latest.hgw_mac IS
    'Derived: COALESCE(NULLIF(cable_mac_address,''Unknown''), NULLIF(pon_mac_address,''Unknown''), NULLIF(wan_mac_address,''Unknown''), ''Unknown'') — the dashboards'' "HGW MAC".';

CREATE TABLE IF NOT EXISTS public.gw_info_values (
    team_id    uuid        NOT NULL REFERENCES public.teams(id) ON DELETE CASCADE,
    kind       text        NOT NULL,
    value      text        NOT NULL,
    first_seen timestamptz NOT NULL,
    last_seen  timestamptz NOT NULL,
    seen_count integer     NOT NULL DEFAULT 1,
    PRIMARY KEY (team_id, kind, value)
);

COMMENT ON TABLE public.gw_info_values IS
    'Every value seen per gateway variable kind (modem_name, firmware_version, technology, network_type, hgw_mac) in successful gw_info runs; NULL keys recorded as ''Unknown''. Grafana filter variables read this instead of scanning script_results.';

-- ---------------------------------------------------------------------------
-- 2. Helpers + trigger
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.gw_info_curate(p_metadata jsonb)
RETURNS jsonb LANGUAGE sql IMMUTABLE AS $$
    SELECT p_metadata
        - 'gateway_url' - 'gateway_profile' - 'selected_profile' - 'protocol'
        - 'requested_protocol' - 'auth_success' - 'profile_attempts'
        - 'config_path' - 'timestamp' - 'host_name' - 'report_artifacts'
        - 'profile_name' - 'device_name' - 'device_model' - 'device_id'
$$;

CREATE OR REPLACE FUNCTION public.gw_info_hgw_mac(p_metadata jsonb)
RETURNS text LANGUAGE sql IMMUTABLE AS $$
    SELECT COALESCE(
        NULLIF(p_metadata->>'cable_mac_address', 'Unknown'),
        NULLIF(p_metadata->>'pon_mac_address',   'Unknown'),
        NULLIF(p_metadata->>'wan_mac_address',   'Unknown'),
        'Unknown')
$$;

CREATE OR REPLACE FUNCTION public.gw_info_track()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF NEW.script_name <> 'gw_info' OR NEW.metadata IS NULL THEN
        RETURN NEW;
    END IF;

    IF NEW.success THEN
        INSERT INTO public.gw_info_values (team_id, kind, value, first_seen, last_seen, seen_count)
        SELECT NEW.team_id, k.kind, k.value, NEW.started_at, NEW.started_at, 1
        FROM (VALUES
            ('modem_name',       COALESCE(NEW.metadata->>'modem_name',       'Unknown')),
            ('firmware_version', COALESCE(NEW.metadata->>'firmware_version', 'Unknown')),
            ('technology',       COALESCE(NEW.metadata->>'technology',       'Unknown')),
            ('network_type',     COALESCE(NEW.metadata->>'network_type',     'Unknown')),
            ('hgw_mac',          public.gw_info_hgw_mac(NEW.metadata))
        ) AS k(kind, value)
        ON CONFLICT (team_id, kind, value) DO UPDATE
            SET first_seen = LEAST(public.gw_info_values.first_seen, EXCLUDED.first_seen),
                last_seen  = GREATEST(public.gw_info_values.last_seen, EXCLUDED.last_seen),
                seen_count = public.gw_info_values.seen_count + 1;
    END IF;

    IF NEW.metadata->>'auth_success' = 'true'
       AND NEW.device_name IS NOT NULL AND NEW.device_name <> 'host' THEN
        INSERT INTO public.gw_info_latest (
            team_id, device_name, host_name, script_result_id, userinterface_name, started_at,
            html_report_r2_url, initial_screenshot_url, final_screenshot_url, video_url, info,
            modem_name, firmware_version, technology, network_type,
            cable_mac_address, pon_mac_address, wan_mac_address, serial_number, hgw_mac, updated_at)
        VALUES (
            NEW.team_id, NEW.device_name, NEW.host_name, NEW.id, NEW.userinterface_name, NEW.started_at,
            NEW.html_report_r2_url,
            NEW.metadata->'report_artifacts'->>'initial_screenshot_url',
            NEW.metadata->'report_artifacts'->>'final_screenshot_url',
            NEW.metadata->'report_artifacts'->>'video_url',
            public.gw_info_curate(NEW.metadata),
            NEW.metadata->>'modem_name', NEW.metadata->>'firmware_version',
            NEW.metadata->>'technology', NEW.metadata->>'network_type',
            NEW.metadata->>'cable_mac_address', NEW.metadata->>'pon_mac_address',
            NEW.metadata->>'wan_mac_address', NEW.metadata->>'serial_number',
            public.gw_info_hgw_mac(NEW.metadata), timezone('utc'::text, now()))
        ON CONFLICT (team_id, device_name, host_name) DO UPDATE SET
            script_result_id       = EXCLUDED.script_result_id,
            userinterface_name     = EXCLUDED.userinterface_name,
            started_at             = EXCLUDED.started_at,
            html_report_r2_url     = EXCLUDED.html_report_r2_url,
            initial_screenshot_url = EXCLUDED.initial_screenshot_url,
            final_screenshot_url   = EXCLUDED.final_screenshot_url,
            video_url              = EXCLUDED.video_url,
            info                   = EXCLUDED.info,
            modem_name             = EXCLUDED.modem_name,
            firmware_version       = EXCLUDED.firmware_version,
            technology             = EXCLUDED.technology,
            network_type           = EXCLUDED.network_type,
            cable_mac_address      = EXCLUDED.cable_mac_address,
            pon_mac_address        = EXCLUDED.pon_mac_address,
            wan_mac_address        = EXCLUDED.wan_mac_address,
            serial_number          = EXCLUDED.serial_number,
            hgw_mac                = EXCLUDED.hgw_mac,
            updated_at             = EXCLUDED.updated_at
        WHERE EXCLUDED.started_at >= public.gw_info_latest.started_at;
    END IF;

    RETURN NEW;
END
$$;

DROP TRIGGER IF EXISTS trg_gw_info_track ON public.script_results;
CREATE TRIGGER trg_gw_info_track
    AFTER INSERT OR UPDATE OF metadata, success, device_name, host_name, started_at
    ON public.script_results
    FOR EACH ROW
    WHEN (NEW.script_name = 'gw_info')
    EXECUTE FUNCTION public.gw_info_track();

-- ---------------------------------------------------------------------------
-- 3. Backfill from history (idempotent — same ON CONFLICT rules as the trigger)
-- ---------------------------------------------------------------------------
INSERT INTO public.gw_info_values (team_id, kind, value, first_seen, last_seen, seen_count)
SELECT sr.team_id, k.kind, k.value, min(sr.started_at), max(sr.started_at), count(*)
FROM public.script_results sr
CROSS JOIN LATERAL (VALUES
    ('modem_name',       COALESCE(sr.metadata->>'modem_name',       'Unknown')),
    ('firmware_version', COALESCE(sr.metadata->>'firmware_version', 'Unknown')),
    ('technology',       COALESCE(sr.metadata->>'technology',       'Unknown')),
    ('network_type',     COALESCE(sr.metadata->>'network_type',     'Unknown')),
    ('hgw_mac',          public.gw_info_hgw_mac(sr.metadata))
) AS k(kind, value)
WHERE sr.script_name = 'gw_info' AND sr.success = true AND sr.metadata IS NOT NULL
GROUP BY sr.team_id, k.kind, k.value
ON CONFLICT (team_id, kind, value) DO UPDATE
    SET first_seen = LEAST(public.gw_info_values.first_seen, EXCLUDED.first_seen),
        last_seen  = GREATEST(public.gw_info_values.last_seen, EXCLUDED.last_seen),
        seen_count = public.gw_info_values.seen_count + EXCLUDED.seen_count;

INSERT INTO public.gw_info_latest (
    team_id, device_name, host_name, script_result_id, userinterface_name, started_at,
    html_report_r2_url, initial_screenshot_url, final_screenshot_url, video_url, info,
    modem_name, firmware_version, technology, network_type,
    cable_mac_address, pon_mac_address, wan_mac_address, serial_number, hgw_mac, updated_at)
SELECT DISTINCT ON (sr.team_id, sr.device_name, sr.host_name)
    sr.team_id, sr.device_name, sr.host_name, sr.id, sr.userinterface_name, sr.started_at,
    sr.html_report_r2_url,
    sr.metadata->'report_artifacts'->>'initial_screenshot_url',
    sr.metadata->'report_artifacts'->>'final_screenshot_url',
    sr.metadata->'report_artifacts'->>'video_url',
    public.gw_info_curate(sr.metadata),
    sr.metadata->>'modem_name', sr.metadata->>'firmware_version',
    sr.metadata->>'technology', sr.metadata->>'network_type',
    sr.metadata->>'cable_mac_address', sr.metadata->>'pon_mac_address',
    sr.metadata->>'wan_mac_address', sr.metadata->>'serial_number',
    public.gw_info_hgw_mac(sr.metadata), timezone('utc'::text, now())
FROM public.script_results sr
WHERE sr.script_name = 'gw_info'
  AND sr.metadata->>'auth_success' = 'true'
  AND sr.device_name IS NOT NULL
  AND sr.device_name <> 'host'
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
    modem_name             = EXCLUDED.modem_name,
    firmware_version       = EXCLUDED.firmware_version,
    technology             = EXCLUDED.technology,
    network_type           = EXCLUDED.network_type,
    cable_mac_address      = EXCLUDED.cable_mac_address,
    pon_mac_address        = EXCLUDED.pon_mac_address,
    wan_mac_address        = EXCLUDED.wan_mac_address,
    serial_number          = EXCLUDED.serial_number,
    hgw_mac                = EXCLUDED.hgw_mac,
    updated_at             = EXCLUDED.updated_at
WHERE EXCLUDED.started_at >= public.gw_info_latest.started_at;

-- ---------------------------------------------------------------------------
-- 4. Views: same columns as 036, `latest` now reads the table
-- ---------------------------------------------------------------------------
DROP VIEW IF EXISTS public.gateway_info_key_status;
DROP VIEW IF EXISTS public.gateway_info_corrected;

CREATE VIEW public.gateway_info_corrected AS
WITH latest AS (
    SELECT team_id, device_name, host_name, userinterface_name, started_at, html_report_r2_url,
           info AS info_raw, initial_screenshot_url, final_screenshot_url, video_url
    FROM public.gw_info_latest
),
ov AS (
    SELECT team_id, device_name, host_name, userinterface_name,
           jsonb_object_agg(info_key, to_jsonb(corrected_value)) AS overrides
    FROM public.device_info_overrides
    WHERE info_source = 'gateway'
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

CREATE VIEW public.gateway_info_key_status AS
WITH latest AS (
    SELECT team_id, device_name, host_name, userinterface_name, info
    FROM public.gw_info_latest
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
    AND o.info_source = 'gateway'
    AND o.info_key = lk.info_key;

ALTER VIEW public.gateway_info_corrected  SET (security_invoker = on);
ALTER VIEW public.gateway_info_key_status SET (security_invoker = on);

COMMENT ON VIEW public.gateway_info_corrected IS
    'Latest gateway scan per (team, device, host) from gw_info_latest, with device_info_overrides (info_source=gateway) applied on top. Read by the hosts listing to attach gateway_info to each device.';
COMMENT ON VIEW public.gateway_info_key_status IS
    'Per-key view of gateway_info_corrected: raw value, override value, staleness — for the correction UI.';

-- ---------------------------------------------------------------------------
-- 5. Ownership, grants, RLS and policies: same as script_results on this DB
-- ---------------------------------------------------------------------------
DO $$
DECLARE
    v_owner text := (SELECT pg_get_userbyid(relowner) FROM pg_class WHERE oid = 'public.script_results'::regclass);
    v_rls   boolean := (SELECT relrowsecurity FROM pg_class WHERE oid = 'public.script_results'::regclass);
    v_rel   text;
    r       record;
    v_sql   text;
BEGIN
    FOREACH v_rel IN ARRAY ARRAY['gw_info_latest', 'gw_info_values'] LOOP
        EXECUTE format('ALTER TABLE public.%I OWNER TO %I', v_rel, v_owner);
        IF v_rls THEN
            EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', v_rel);
        END IF;
    END LOOP;

    FOREACH v_rel IN ARRAY ARRAY['gw_info_latest', 'gw_info_values',
                                 'gateway_info_corrected', 'gateway_info_key_status'] LOOP
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

    -- Policies (script_results' own quals reference auth.* only; anything that does
    -- not apply to the new tables is reported and skipped, not fatal).
    FOR r IN
        SELECT policyname, permissive, roles, cmd, qual, with_check
        FROM pg_policies WHERE schemaname = 'public' AND tablename = 'script_results'
    LOOP
        FOREACH v_rel IN ARRAY ARRAY['gw_info_latest', 'gw_info_values'] LOOP
            v_sql := format('CREATE POLICY %I ON public.%I AS %s FOR %s TO %s',
                            replace(r.policyname, 'script_results', v_rel), v_rel,
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
                RAISE NOTICE 'policy % not copied to %: %', r.policyname, v_rel, SQLERRM;
            END;
        END LOOP;
    END LOOP;
END
$$;
