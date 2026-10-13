-- 20261007a_userinterface_unknown_screens_rollback.sql
-- Removes the unknown-screens table added by 20261007a.
--
-- DESTRUCTIVE: every pending row is a screen an operator had not yet acted on, and this drops
-- them. Accepted rows have already become navigation nodes, which this does not touch -- so a
-- rollback can leave nodes in trees with no record of where they came from. Dump the table
-- before running this if the pending rows matter.
--
-- Idempotent: safe to re-run.

BEGIN;

DROP TRIGGER IF EXISTS trg_userinterface_unknown_screens_updated_at
    ON public.userinterface_unknown_screens;
DROP FUNCTION IF EXISTS public.touch_userinterface_unknown_screens_updated_at();
DROP TABLE IF EXISTS public.userinterface_unknown_screens;

COMMIT;