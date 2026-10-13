-- 20260930a_ai_web_capability.sql
-- TASK-05 — AI profiles may declare the "web" capability (the model can answer from a live web
-- search). Recorded by the profile's "web" Test button; required by the text.web usages, which
-- the gateway never answers without searching.
--
-- Canonical twin: setup/db/schema/055_ai_routing.sql. Idempotent.
-- Inverse: 20260930a_ai_web_capability_rollback.sql.

BEGIN;

ALTER TABLE public.ai_profiles DROP CONSTRAINT IF EXISTS ai_profiles_capabilities_check;
ALTER TABLE public.ai_profiles ADD CONSTRAINT ai_profiles_capabilities_check
    CHECK (capabilities <@ ARRAY['tools', 'vision', 'web']::text[]);

COMMIT;
