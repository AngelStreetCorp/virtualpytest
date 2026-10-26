-- Rollback for 20261022f: removes the guarded prune function (auto_classify then needs the 20261016c one again).
BEGIN;

DROP FUNCTION IF EXISTS public.prune_unnamed_screen_noise(uuid, integer, integer, integer);

COMMIT;
