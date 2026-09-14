-- Drop the legacy ai_userinterface_flows table
-- ------------------------------------------------------
-- The flows table stored open-loop action sequences that were executed via
-- the now-removed execute_verified_flow MCP tool. Replacement Layer 2
-- (ai_userinterface_transitions) has been populated and validated end-to-end
-- on host1 device3 (example-5.02 read_firmware task: 116.6 s, 8 tool
-- calls, 0 errors via the DB-stored pack — see docs/agent/navigation/AI_USERINTERFACE_MARKDOWN_PACKS.md).
--
-- No production code references this table:
--   - MCP tool execute_verified_flow: removed (20260424 code migration)
--   - add_ai_userinterface_flow:       removed (20260424 code migration)
--   - Python db lib:                    no longer exports flow helpers
--   - test_scripts:                     never used flow tools
--   - frontend:                         never queried flows
--
-- Idempotent: DROP TABLE IF EXISTS. Supersession history for any rows is not
-- preserved — the flow content was duplicated into the new transitions table
-- during the example-5.02 backfill.

BEGIN;

DROP TABLE IF EXISTS ai_userinterface_flows CASCADE;

COMMIT;
