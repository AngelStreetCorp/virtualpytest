-- 20261001a_device_models_catalog_rollback.sql
-- Inverse of 20261001a_device_models_catalog.sql: restores device_models.controllers (empty,
-- as nothing reads it) and the seed-only-an-empty-team function. The six seeded rows stay —
-- the older code lists them fine. Apply BEFORE deploying the older code, which selects
-- `controllers`.

BEGIN;

ALTER TABLE public.device_models ADD COLUMN IF NOT EXISTS controllers jsonb
    DEFAULT '{"av": "", "power": "", "remote": "", "network": ""}'::jsonb NOT NULL
    CHECK (jsonb_typeof(controllers) = 'object'::text);

CREATE OR REPLACE FUNCTION public.create_default_device_models(p_team_id uuid)
RETURNS void
LANGUAGE plpgsql
SET search_path = public, auth, extensions
AS $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM device_models WHERE team_id = p_team_id LIMIT 1) THEN
        INSERT INTO device_models (team_id, name, types, version, description, is_default)
        VALUES
            (p_team_id, 'web', '["safari", "chrome", "firefox", "edge"]'::jsonb, '', 'Web browser testing via Playwright', true),
            (p_team_id, 'android_tv', '["Android TV", "Fire TV", "Nvidia Shield"]'::jsonb, '', 'Android TV and streaming devices', true),
            (p_team_id, 'stb', '["STB"]'::jsonb, '', 'Generic Set-Top Box', true),
            (p_team_id, 'android_mobile', '["Android Phone", "Android TV"]'::jsonb, '', 'Android mobile devices', true),
            (p_team_id, 'apple_tv', '["apple_tv"]'::jsonb, '', 'Apple TV devices', true);
    END IF;
END;
$$;

COMMIT;
