-- 20261001a_device_models_catalog.sql
-- Device Models page: the list matches what a host can run.
--
-- 1. Seeds the core models that hosts support but no team had a row for — fire_tv,
--    android_tablet, ios_mobile, tizen, camera, host_vnc — so a userinterface can target
--    them. create_default_device_models() now inserts each missing core model by name
--    (it used to do nothing once a team had any row), so the same call backfills every
--    existing team and seeds new ones.
-- 2. Drops device_models.controllers. Nothing ever read it: a host builds its controllers
--    from DEVICE_CONTROLLER_MAP (shared/src/lib/config/device_capabilities.py) and its .env.
--
-- APPLY AFTER deploying the matching code: older code still selects `controllers` and the
-- Device Models page fails to load until it is replaced. Idempotent.
-- Canonical twin: setup/db/schema/001_core_tables.sql.
-- Inverse: 20261001a_device_models_catalog_rollback.sql.

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

ALTER TABLE public.device_models DROP COLUMN IF EXISTS controllers;

COMMIT;
