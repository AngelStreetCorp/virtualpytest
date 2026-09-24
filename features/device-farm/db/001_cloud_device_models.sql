-- 2026-09-17 (TASK-20): the cloud farm device model rows.
--
-- shared/src/lib/config/device_capabilities.py carries cloud_android_mobile and
-- cloud_ios_mobile, but the UserInterface editor builds its model dropdown from
-- device_models (frontend/src/pages/UserInterface.tsx) — without these rows no
-- navigation tree can be created for a farm device, so every tree-driven script
-- (goto, validation, device_get_info) would have nothing to run against it. Same
-- gap the mobile-app feature hit; same fix.
--
-- Not seeded by create_default_device_models() in setup/db/schema/001_core_tables.sql:
-- these models belong to the optional device-farm feature, and the core defaults must
-- stay identical whether or not the feature is installed.
--
-- The controllers blob mirrors DEVICE_CONTROLLER_MAP: av is the ordinary hdmi_stream
-- (the feature's frame pump feeds the host's imagefile grabber, so nothing downstream
-- of the captures folder changes) and the remote is appium_cloud.
--
-- Idempotent, and applied to every existing team. NOT run by any deploy script —
-- apply by hand (docs/technical/FEATURES.md).

INSERT INTO device_models (team_id, name, types, controllers, description, is_default)
SELECT t.id,
       'cloud_android_mobile',
       '["Android Phone"]'::jsonb,
       '{"av": "hdmi_stream", "power": "", "remote": "appium_cloud", "network": ""}'::jsonb,
       'Android phone in a cloud device farm (features/device-farm)',
       true
FROM teams t
WHERE NOT EXISTS (
    SELECT 1 FROM device_models dm WHERE dm.team_id = t.id AND dm.name = 'cloud_android_mobile'
);

INSERT INTO device_models (team_id, name, types, controllers, description, is_default)
SELECT t.id,
       'cloud_ios_mobile',
       '["iOS Phone"]'::jsonb,
       '{"av": "hdmi_stream", "power": "", "remote": "appium_cloud", "network": ""}'::jsonb,
       'iPhone in a cloud device farm (features/device-farm)',
       true
FROM teams t
WHERE NOT EXISTS (
    SELECT 1 FROM device_models dm WHERE dm.team_id = t.id AND dm.name = 'cloud_ios_mobile'
);
