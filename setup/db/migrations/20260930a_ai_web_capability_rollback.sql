-- 20260930a_ai_web_capability_rollback.sql
-- Inverse of 20260930a_ai_web_capability.sql: strips "web" from every profile, then restores the
-- tools/vision-only CHECK. Deploy the matching older code with it.

BEGIN;

UPDATE public.ai_profiles SET capabilities = array_remove(capabilities, 'web')
 WHERE 'web' = ANY(capabilities);

ALTER TABLE public.ai_profiles DROP CONSTRAINT IF EXISTS ai_profiles_capabilities_check;
ALTER TABLE public.ai_profiles ADD CONSTRAINT ai_profiles_capabilities_check
    CHECK (capabilities <@ ARRAY['tools', 'vision']::text[]);

COMMIT;
