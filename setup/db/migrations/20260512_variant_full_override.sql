-- 20260512 — Variant overrides switched from patch-merge to full replacement.
-- See docs/agent/navigation/VARIANT.md.
--
-- New JSONB shape (server-validated, see _validate_overrides_map in
-- backend_server/src/routes/server_userinterface_routes.py):
--   userinterface_variants.node_overrides[<node_id>] = {
--     disabled?: boolean,
--     verifications?: <Verification>[]    -- FULLY replaces base verifications
--   }
--   userinterface_variants.edge_overrides[<edge_id>] = {
--     disabled?: boolean,
--     action_sets?:  <ActionSet>[]        -- FULLY replaces base action_sets
--   }
--
-- The old `patches` field is dropped. There is no automatic data conversion
-- from patches → full overrides (patches can't represent the variant's actual
-- end-state, only a diff from base at write time). Existing entries are
-- wiped: any variant that previously held patches will fall through to base
-- until re-authored in the editor.

BEGIN;

-- Wipe every variant's override maps. The variant rows themselves
-- (team_id, userinterface_id, name, description) are preserved.
UPDATE public.userinterface_variants
SET node_overrides = '{}'::jsonb,
    edge_overrides = '{}'::jsonb,
    updated_at = NOW()
WHERE node_overrides <> '{}'::jsonb
   OR edge_overrides <> '{}'::jsonb;

-- Refresh column docs to reflect the new shape.
COMMENT ON COLUMN public.userinterface_variants.node_overrides IS
'Map keyed by navigation_nodes.node_id. Each entry: {disabled?: bool, verifications?: <Verification>[]}.
 disabled=true and verifications are mutually exclusive (server-validated).
 When verifications is present it FULLY REPLACES the base row''s verifications
 for this variant. There is no patch / param-merge layer.';

COMMENT ON COLUMN public.userinterface_variants.edge_overrides IS
'Map keyed by navigation_edges.edge_id. Each entry: {disabled?: bool, action_sets?: <ActionSet>[]}.
 disabled=true and action_sets are mutually exclusive (server-validated).
 When action_sets is present it FULLY REPLACES the base row''s action_sets for
 this variant. There is no patch / param-merge layer.';

COMMIT;

SELECT '20260512_variant_full_override.sql applied' AS status;
