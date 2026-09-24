-- 20260923d_is_platform_admin.sql
-- TASK-23 — Add profiles.is_platform_admin (super admin concept, Q3).
-- Default false so no existing user is auto-promoted. Promotion is DB-only
-- in v1 (Q8):
--   UPDATE public.profiles SET is_platform_admin = true WHERE email = …;
--
-- Idempotent.

BEGIN;

ALTER TABLE public.profiles
  ADD COLUMN IF NOT EXISTS is_platform_admin BOOLEAN NOT NULL DEFAULT false;

COMMIT;