-- 20261005d_fire_tv_models_by_os_rollback.sql
-- Inverse of 20261005d_fire_tv_models_by_os.sql: back to `fire_tv` / `vega_tv`.

BEGIN;

CREATE OR REPLACE FUNCTION public.create_default_device_models(p_team_id uuid)
RETURNS void
LANGUAGE plpgsql
SET search_path = public, auth, extensions
AS $$
BEGIN
    INSERT INTO device_models (team_id, name, types, version, description, is_default)
    SELECT p_team_id, d.name, d.types, '', d.description, true
    FROM (VALUES
        ('web',            '["safari", "chrome", "firefox", "edge"]'::jsonb,         'Web browser testing via Playwright'),
        ('android_tv',     '["Android TV", "Fire TV", "Nvidia Shield"]'::jsonb,      'Android TV and streaming devices'),
        ('fire_tv',        '["Fire TV"]'::jsonb,                                     'Amazon Fire TV (ADB, plus IR/BLE when configured)'),
        ('vega_tv',        '["Fire TV (Vega OS)"]'::jsonb,                           'Amazon Fire TV on Vega OS (adb + inputd-cli, plus IR/BLE when configured)'),
        ('stb',            '["STB"]'::jsonb,                                         'Generic Set-Top Box'),
        ('android_mobile', '["Android Phone", "Android TV"]'::jsonb,                 'Android mobile devices'),
        ('android_tablet', '["Android Tablet"]'::jsonb,                              'Android tablets'),
        ('ios_mobile',     '["iOS Phone"]'::jsonb,                                   'iPhone driven through Appium'),
        ('apple_tv',       '["apple_tv"]'::jsonb,                                    'Apple TV devices'),
        ('tizen',          '["Tizen TV"]'::jsonb,                                    'Samsung Tizen TV filmed by a camera'),
        ('camera',         '["Camera"]'::jsonb,                                      'Any device filmed by a camera instead of HDMI capture'),
        ('host_vnc',       '["Desktop"]'::jsonb,                                     'The host''s own desktop over VNC (desktop + web)')
    ) AS d(name, types, description)
    WHERE NOT EXISTS (
        SELECT 1 FROM device_models dm WHERE dm.team_id = p_team_id AND dm.name = d.name
    );
END;
$$;


-- fire_tv_fireos -> fire_tv
UPDATE device_models SET name = 'fire_tv' WHERE name = 'fire_tv_fireos'
    AND NOT EXISTS (SELECT 1 FROM device_models d2 WHERE d2.team_id = device_models.team_id AND d2.name = 'fire_tv');
UPDATE userinterfaces SET models = array_replace(models, 'fire_tv_fireos', 'fire_tv') WHERE 'fire_tv_fireos' = ANY(models);
-- fire_tv_vega -> vega_tv
UPDATE device_models SET name = 'vega_tv' WHERE name = 'fire_tv_vega'
    AND NOT EXISTS (SELECT 1 FROM device_models d2 WHERE d2.team_id = device_models.team_id AND d2.name = 'vega_tv');
UPDATE userinterfaces SET models = array_replace(models, 'fire_tv_vega', 'vega_tv') WHERE 'fire_tv_vega' = ANY(models);
-- History tables (some exist only on some installs).
DO $$
BEGIN
    IF to_regclass('public.ai_graph_cache') IS NOT NULL THEN UPDATE public.ai_graph_cache SET device_model = 'fire_tv' WHERE device_model = 'fire_tv_fireos'; END IF;
    IF to_regclass('public.ai_graph_cache') IS NOT NULL THEN UPDATE public.ai_graph_cache SET device_model = 'vega_tv' WHERE device_model = 'fire_tv_vega'; END IF;
    IF to_regclass('public.ai_routes') IS NOT NULL THEN UPDATE public.ai_routes SET device_model = 'fire_tv' WHERE device_model = 'fire_tv_fireos'; END IF;
    IF to_regclass('public.ai_routes') IS NOT NULL THEN UPDATE public.ai_routes SET device_model = 'vega_tv' WHERE device_model = 'fire_tv_vega'; END IF;
    IF to_regclass('public.ai_training_samples') IS NOT NULL THEN UPDATE public.ai_training_samples SET device_model = 'fire_tv' WHERE device_model = 'fire_tv_fireos'; END IF;
    IF to_regclass('public.ai_training_samples') IS NOT NULL THEN UPDATE public.ai_training_samples SET device_model = 'vega_tv' WHERE device_model = 'fire_tv_vega'; END IF;
    IF to_regclass('public.device') IS NOT NULL THEN UPDATE public.device SET model = 'fire_tv' WHERE model = 'fire_tv_fireos'; END IF;
    IF to_regclass('public.device') IS NOT NULL THEN UPDATE public.device SET model = 'vega_tv' WHERE model = 'fire_tv_vega'; END IF;
    IF to_regclass('public.execution_results') IS NOT NULL THEN UPDATE public.execution_results SET device_model = 'fire_tv' WHERE device_model = 'fire_tv_fireos'; END IF;
    IF to_regclass('public.execution_results') IS NOT NULL THEN UPDATE public.execution_results SET device_model = 'vega_tv' WHERE device_model = 'fire_tv_vega'; END IF;
    IF to_regclass('public.fleet_health') IS NOT NULL THEN UPDATE public.fleet_health SET device_model = 'fire_tv' WHERE device_model = 'fire_tv_fireos'; END IF;
    IF to_regclass('public.fleet_health') IS NOT NULL THEN UPDATE public.fleet_health SET device_model = 'vega_tv' WHERE device_model = 'fire_tv_vega'; END IF;
    IF to_regclass('public.requirements') IS NOT NULL THEN UPDATE public.requirements SET device_model = 'fire_tv' WHERE device_model = 'fire_tv_fireos'; END IF;
    IF to_regclass('public.requirements') IS NOT NULL THEN UPDATE public.requirements SET device_model = 'vega_tv' WHERE device_model = 'fire_tv_vega'; END IF;
    IF to_regclass('public.system_device_metrics') IS NOT NULL THEN UPDATE public.system_device_metrics SET device_model = 'fire_tv' WHERE device_model = 'fire_tv_fireos'; END IF;
    IF to_regclass('public.system_device_metrics') IS NOT NULL THEN UPDATE public.system_device_metrics SET device_model = 'vega_tv' WHERE device_model = 'fire_tv_vega'; END IF;
    IF to_regclass('public.verifications_references') IS NOT NULL THEN UPDATE public.verifications_references SET device_model = 'fire_tv' WHERE device_model = 'fire_tv_fireos'; END IF;
    IF to_regclass('public.verifications_references') IS NOT NULL THEN UPDATE public.verifications_references SET device_model = 'vega_tv' WHERE device_model = 'fire_tv_vega'; END IF;
    IF to_regclass('public.zap_results') IS NOT NULL THEN UPDATE public.zap_results SET device_model = 'fire_tv' WHERE device_model = 'fire_tv_fireos'; END IF;
    IF to_regclass('public.zap_results') IS NOT NULL THEN UPDATE public.zap_results SET device_model = 'vega_tv' WHERE device_model = 'fire_tv_vega'; END IF;
    IF to_regclass('public.verification_commands') IS NOT NULL THEN UPDATE public.verification_commands SET device_model = 'fire_tv' WHERE device_model = 'fire_tv_fireos'; END IF;
    IF to_regclass('public.verification_commands') IS NOT NULL THEN UPDATE public.verification_commands SET device_model = 'vega_tv' WHERE device_model = 'fire_tv_vega'; END IF;
END
$$;

UPDATE device_models SET types = '["Fire TV"]'::jsonb,
    description = 'Amazon Fire TV (ADB, plus IR/BLE when configured)'
    WHERE name = 'fire_tv' AND is_default;
DELETE FROM device_models WHERE name IN ('fire_tv_fireos', 'fire_tv_vega') AND is_default;

COMMIT;
