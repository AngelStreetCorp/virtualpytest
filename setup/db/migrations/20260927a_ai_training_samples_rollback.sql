-- 20260927a_ai_training_samples_rollback.sql
-- Inverse of 20260927a. Drops the trigger, its function, the table (with its
-- indexes, constraints and policy) and teams.training_data_opt_in.
-- Destroys every training-sample index row; the bucket objects are not touched.

BEGIN;

-- Dropping the table drops its trigger, indexes, constraints and RLS policy.
DROP TABLE IF EXISTS public.ai_training_samples;
DROP FUNCTION IF EXISTS public.ai_training_samples_frozen_guard();

ALTER TABLE public.teams
    DROP COLUMN IF EXISTS training_data_opt_in;

COMMIT;
