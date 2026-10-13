-- 20261002a_ai_decisions_rollback.sql — inverse of 20261002a_ai_decisions.sql.
-- Keeps the "jev" profile: on the lab it existed before this migration (created by hand).

BEGIN;

DELETE FROM public.ai_routes WHERE team_id IS NULL AND usage_key = 'text.decision'
    AND host_name IS NULL AND device_model IS NULL AND userinterface_name IS NULL;
DROP TABLE IF EXISTS public.ai_decisions;

COMMIT;
