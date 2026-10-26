-- Rollback for 20261023b_screen_fingerprint_writer.sql.
-- Drops the single writer for a fingerprint.  It touches no row data: the fingerprints written
-- while it existed stay where they are (they are the screen's own identity, and the rows that
-- carry them are the ones the owner counts).
BEGIN;

DROP FUNCTION IF EXISTS public.link_screen_fingerprint(uuid, uuid, jsonb, text);

COMMIT;
