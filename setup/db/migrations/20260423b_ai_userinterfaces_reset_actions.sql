-- ai_userinterfaces: add per-UI mandatory reset sequence
-- ------------------------------------------------------
-- Verified flows assume a deterministic starting screen (e.g. example-5.02's
-- 'home -> settings.info.about' starts from "top-nav HOME tile selected, on
-- the home dashboard"). When the device is somewhere else, the first key in
-- the flow drifts focus and every press after lands on the wrong tile.
--
-- Fix: store a per-UI `reset_actions` array on the parent. execute_verified_flow
-- prepends it to every flow run so the device snaps to the anchor first.
-- Same JSON shape as ai_userinterface_flows.actions.
--
-- For example-5.02 the verified reset (5/5 trials from a live-TV start, see
-- docs/agent/navigation/AI_USERINTERFACE_TROUBLESHOOT.md) is:
--   TVGUIDE [4s], TVGUIDE [4s], HOME [4s]
-- Anchor screen: top-nav HOME tab underlined red, Example red wordmark,
-- promo tile (GOAT/SpongeBob/etc.) on the right, "Continue Watching" + "Top Picks".
--
-- Idempotent: column add is IF NOT EXISTS, backfill UPDATEs only the row that
-- exists today.

BEGIN;

ALTER TABLE ai_userinterfaces
  ADD COLUMN IF NOT EXISTS reset_actions jsonb;

ALTER TABLE ai_userinterfaces
  DROP CONSTRAINT IF EXISTS ai_userinterfaces_reset_actions_shape;
ALTER TABLE ai_userinterfaces
  ADD CONSTRAINT ai_userinterfaces_reset_actions_shape CHECK (
    reset_actions IS NULL OR (
      jsonb_typeof(reset_actions) = 'array' AND jsonb_array_length(reset_actions) > 0
    )
  );

UPDATE ai_userinterfaces
SET reset_actions = '[
  {"command":"press_key","params":{"action_type":"infrared","key":"TVGUIDE","wait_time":4000}},
  {"command":"press_key","params":{"action_type":"infrared","key":"TVGUIDE","wait_time":4000}},
  {"command":"press_key","params":{"action_type":"infrared","key":"HOME","wait_time":4000}}
]'::jsonb
WHERE ui_id = 'example-5.02'
  AND reset_actions IS NULL;

COMMIT;
