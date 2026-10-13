-- 20261005c_vega_tv_device_model.sql
-- TASK-57: adds the core model `vega_tv` (Fire TV on Vega OS) to the catalog, so a
-- userinterface can target it. create_default_device_models() inserts each missing core
-- model by name, so re-running it adds only the new row for every existing team.
-- Data only, idempotent; safe before or after the code deploy.
-- Canonical twin: setup/db/schema/001_core_tables.sql.
-- Inverse: 20261005c_vega_tv_device_model_rollback.sql.

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

SELECT public.create_default_device_models(t.id) FROM teams t;

COMMIT;
