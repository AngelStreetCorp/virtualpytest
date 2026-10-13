-- 20260928c_fix_device_info_track_null_guard.sql
--
-- HOTFIX for 20260928a / 052 (TASK-29). The trigger aborted the INSERT it was
-- supposed to observe: every get_info / device_get_info run failed to record at
-- all, with
--
--   null value in column "info" of relation "device_info_latest"
--   violates not-null constraint  (SQLSTATE 23502)
--
-- raised inside record_script_execution_start. No script_results row was
-- written, so no SCRIPT_RESULT_ID was printed, so deployment_executions.
-- script_result_id stayed NULL and the Run Tests page had no report or logs
-- link for the run.
--
-- Two independent faults, both fixed here.
--
-- 1) THE GUARD WAS NOT NULL-SAFE. It read
--
--        IF ... OR jsonb_typeof(NEW.metadata->'info') <> 'object' THEN RETURN NEW;
--
--    When `info` is ABSENT (the normal shape of a start record, which carries
--    only trigger/parameters/versions), `metadata->'info'` is NULL and
--    jsonb_typeof(NULL) is NULL, so the comparison is NULL — not TRUE. A NULL
--    disjunct leaves the whole condition NULL, `IF NULL` is not taken, and the
--    INSERT ran with info = NULL.
--
--    035's view expressed the same rule as `WHERE jsonb_typeof(...) = 'object'`,
--    where NULL correctly excludes the row. Translating a WHERE into a negated
--    IF is what lost it. `IS DISTINCT FROM` restores NULL-safety, and COALESCE
--    does the same for script_name.
--
-- 2) A DERIVED CACHE MUST NEVER BREAK ITS SOURCE. Even with a correct guard, any
--    future failure inserting into device_info_latest (constraint, FK, lock)
--    would abort the script_results write and lose a test run. The upsert is now
--    wrapped so it can only ever warn.
--
-- Idempotent: CREATE OR REPLACE only. No data change; rows missed while the bad
-- version was live are gone from script_results entirely and cannot be recovered
-- from here (the runs themselves still uploaded their reports to R2).

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
