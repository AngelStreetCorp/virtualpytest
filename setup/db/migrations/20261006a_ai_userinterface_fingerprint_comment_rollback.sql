-- 20261006a_ai_userinterface_fingerprint_comment_rollback.sql
-- Inverse of 20261006a_ai_userinterface_fingerprint_comment.sql. Restores the
-- table comment set by setup/db/schema/033_ai_userinterface.sql verbatim.
--
-- Only the COMMENT metadata is reverted. No data, column, index or constraint was
-- ever changed, so there is nothing else to undo.

BEGIN;

COMMENT ON TABLE public.ai_userinterface_fingerprints IS
    'Runtime fingerprints used to resolve a device''s state to a ui_id. Replaces the legacy _registry.json file approach.';

COMMIT;