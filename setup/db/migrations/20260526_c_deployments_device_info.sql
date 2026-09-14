-- 20260526_c — Per-deployment manual device info.
--
-- Lets the run UI attach key/value device info (per selected device) that is
-- merged into metadata.info of every script the deployment runs (scripts,
-- campaign scripts, test cases) — so users can provide device info instead of
-- fetching it via the get_info OCR script. Carried to the script subprocess as
-- the VPT_DEVICE_INFO env var; merged in ScriptExecutor._merge_final_metadata.

BEGIN;

ALTER TABLE public.deployments
    ADD COLUMN IF NOT EXISTS device_info jsonb;

COMMENT ON COLUMN public.deployments.device_info IS
'Optional manual device info ({key: value}) merged into metadata.info of every '
'script this deployment runs. Set per-device in the run UI (Selected Items → '
'Device Info). device_get_info ignores it (it fetches its own).';

COMMIT;
