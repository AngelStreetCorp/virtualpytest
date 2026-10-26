-- Rollback for 20261018d: the vision.classify default route and the jev-router
-- profile it points at.  Both are removed only when nothing else uses them.

BEGIN;

DELETE FROM public.ai_routes
WHERE team_id IS NULL AND usage_key = 'vision.classify';

DELETE FROM public.ai_profiles p
WHERE p.name = 'jev-router'
  AND NOT EXISTS (SELECT 1 FROM public.ai_routes r
                  WHERE r.profile_id = p.id OR r.split_profile_id = p.id)
  AND NOT EXISTS (SELECT 1 FROM public.ai_profiles q
                  WHERE q.fallback_profile_id = p.id);

COMMIT;
