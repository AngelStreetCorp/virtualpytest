-- Rollback of 20261022e_agent_faq_count_fn.sql.
-- Drops the count-bump RPC and the promoted-row CHECK. The CHECK is dropped rather than
-- re-created permissively: row 1edc58d8 was demoted by the phase-9b clobber before this
-- migration existed, and an operator should re-check the table before re-adding the constraint.
BEGIN;
ALTER TABLE public.agent_faq DROP CONSTRAINT IF EXISTS agent_faq_proposed_shape;
DROP FUNCTION IF EXISTS public.atlas_faq_bump(UUID);
COMMIT;
