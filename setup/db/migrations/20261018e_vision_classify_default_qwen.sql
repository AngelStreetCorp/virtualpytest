-- 20261018e (2026-10-17): the default unknown-screen classifier is Qwen-only.
--
-- The 2026-10-17 benchmark (reports/localize-jev-bench-2026-10-17) found the
-- Jev closed choice loses to Qwen-only on foreign screens (60 % vs 90 % hybrid
-- accuracy) and is 1/10 on a 60-option tree. Qwen open-set naming is now the
-- default; the Jev hybrid is an explicitly selected experimental mode that
-- pins its own jev-router profile, so this route change cannot select Jev.
--
-- Idempotent: update the server-default route, insert it when missing. Team
-- overrides are untouched.

BEGIN;

UPDATE public.ai_routes r
   SET profile_id = q.id,
       updated_at = NOW()
  FROM public.ai_profiles q
 WHERE r.team_id IS NULL
   AND r.usage_key = 'vision.classify'
   AND q.name = 'qwen3-vl-8b';

INSERT INTO public.ai_routes (team_id, usage_key, profile_id)
SELECT NULL, 'vision.classify', q.id
  FROM public.ai_profiles q
 WHERE q.name = 'qwen3-vl-8b'
   AND NOT EXISTS (
       SELECT 1 FROM public.ai_routes r
       WHERE r.team_id IS NULL AND r.usage_key = 'vision.classify'
   )
ON CONFLICT DO NOTHING;

COMMIT;
