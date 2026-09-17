-- 2026-09-16: the `phone_agent` device model row.
--
-- shared/src/lib/config/device_capabilities.py has carried this model since TASK-17,
-- but nothing ever added it to device_models — and the UserInterface editor builds its
-- model dropdown from that table (frontend/src/pages/UserInterface.tsx). So no
-- navigation tree could be created for a paired phone, and every tree-driven script
-- (goto, validation, device_get_info) had nothing to run against it.
--
-- Not seeded by create_default_device_models() in setup/db/schema/001_core_tables.sql:
-- phone_agent belongs to the optional mobile-app feature, and the core defaults must
-- stay the same whether or not the feature is installed.
--
-- Idempotent, and applied to every existing team.
INSERT INTO device_models (team_id, name, types, controllers, description, is_default)
SELECT t.id,
       'phone_agent',
       '["Android Phone"]'::jsonb,
       '{"av": "hdmi_stream", "power": "", "remote": "phone_agent", "network": ""}'::jsonb,
       'Phone paired through the VirtualPyTest app (features/mobile-app)',
       true
FROM teams t
WHERE NOT EXISTS (
    SELECT 1 FROM device_models dm WHERE dm.team_id = t.id AND dm.name = 'phone_agent'
);
