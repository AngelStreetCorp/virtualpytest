-- 20260928b_device_info_overrides_prereq.sql
--
-- Creates `device_info_overrides` on a database that never received 035 —
-- the prerequisite both 20260910c (gateway, TASK-16) and 20260928a (device,
-- TASK-29) need, since each builds its corrected/key_status views on it.
-- TASK-16 recorded QualiAI as blocked for exactly this reason; this unblocks it.
--
-- WHY NOT JUST RUN 035: the canonical schema file ends with
--
--     CREATE POLICY "device_info_overrides_access_policy" ON public.device_info_overrides
--     FOR ALL TO public USING (true) WITH CHECK (true);
--
-- which is precisely the tautology policy TASK-10 removed everywhere
-- (20260908b main env, 20260908d env2). Applying 035 verbatim to a hardened
-- database re-opens one table to the anon key. 035 is fine for a fresh install
-- that is hardened afterwards; it is wrong as a retrofit.
--
-- So this file creates the same TABLE and INDEX, and then copies ownership,
-- grants, RLS and policies from `script_results` on whatever database it runs
-- on — the same DO block 046 and 052 use. That is correct on every posture: on
-- a hardened DB it yields RLS + service_role and no policy; on an un-hardened
-- one it reproduces whatever script_results already allows.
--
-- The VIEWS that 035 also defines are deliberately NOT created here: 20260928a
-- drops and recreates both device views over `device_info_latest` anyway, so
-- creating the read-time versions first would be pure churn.
--
-- Idempotent. Plain SQL, one transaction.

CREATE TABLE IF NOT EXISTS public.device_info_overrides (
    id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    team_id            uuid NOT NULL,
    device_name        text NOT NULL,
    host_name          text NOT NULL,
    userinterface_name text NOT NULL DEFAULT '',
    info_source        text NOT NULL DEFAULT 'device',
    info_key           text NOT NULL,
    corrected_value    text NOT NULL,
    raw_value_at_edit  text,
    note               text,
    updated_by         text,
    created_at         timestamptz NOT NULL DEFAULT NOW(),
    updated_at         timestamptz NOT NULL DEFAULT NOW(),
    CONSTRAINT device_info_overrides_unique
        UNIQUE (team_id, device_name, host_name, userinterface_name, info_source, info_key)
);

CREATE INDEX IF NOT EXISTS idx_device_info_overrides_lookup
    ON public.device_info_overrides (team_id, device_name, host_name, userinterface_name, info_source);

COMMENT ON TABLE public.device_info_overrides IS
    'Per-device, per-key human-entered correction for OCR device info and gw_info gateway info, discriminated by info_source. Applied at read time by device_info_corrected / gateway_info_corrected; raw values in script_results are never mutated.';

-- Ownership, grants, RLS and policies: same as script_results on this DB.
DO $$
DECLARE
    v_owner text := (SELECT pg_get_userbyid(relowner) FROM pg_class WHERE oid = 'public.script_results'::regclass);
    v_rls   boolean := (SELECT relrowsecurity FROM pg_class WHERE oid = 'public.script_results'::regclass);
    r       record;
    v_sql   text;
BEGIN
    EXECUTE format('ALTER TABLE public.device_info_overrides OWNER TO %I', v_owner);
    IF v_rls THEN
        EXECUTE 'ALTER TABLE public.device_info_overrides ENABLE ROW LEVEL SECURITY';
    END IF;

    FOR r IN
        SELECT grantee, string_agg(privilege_type, ', ') AS privs
        FROM information_schema.role_table_grants
        WHERE table_schema = 'public' AND table_name = 'script_results'
        GROUP BY grantee
    LOOP
        IF r.grantee = 'PUBLIC' THEN
            EXECUTE format('GRANT %s ON public.device_info_overrides TO PUBLIC', r.privs);
        ELSE
            EXECUTE format('GRANT %s ON public.device_info_overrides TO %I', r.privs, r.grantee);
        END IF;
    END LOOP;

    FOR r IN
        SELECT policyname, permissive, roles, cmd, qual, with_check
        FROM pg_policies WHERE schemaname = 'public' AND tablename = 'script_results'
    LOOP
        v_sql := format('CREATE POLICY %I ON public.device_info_overrides AS %s FOR %s TO %s',
                        replace(r.policyname, 'script_results', 'device_info_overrides'),
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
            RAISE NOTICE 'policy % not copied to device_info_overrides: %', r.policyname, SQLERRM;
        END;
    END LOOP;
END
$$;
