-- Product-path classification (2026-10-17): remember which interface abstained.
--
-- auto_classify_unknowns offers the abstaining interface's real node labels to
-- the closed-choice classifier.  ``scope`` is host/device; the interface is a
-- different name, known to every bump caller but not stored here before.
--
-- Additive and nullable: legacy rows keep NULL and classify open-set until
-- their next hit fills it in.

BEGIN;

ALTER TABLE public.screen_fingerprints
    ADD COLUMN IF NOT EXISTS userinterface text;

COMMENT ON COLUMN public.screen_fingerprints.userinterface IS
    'Interface the device was using when the matcher abstained. NULL on legacy rows; the '
    'auto-classify scheduler then falls back to the device part of scope.';

COMMIT;
