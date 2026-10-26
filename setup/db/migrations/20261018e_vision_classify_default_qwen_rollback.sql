-- Rollback for 20261018e: put the experimental Jev profile back on the default
-- vision.classify route.

BEGIN;

UPDATE public.ai_routes r
   SET profile_id = j.id,
       updated_at = NOW()
  FROM public.ai_profiles j
 WHERE r.team_id IS NULL
   AND r.usage_key = 'vision.classify'
   AND j.name = 'jev-router';

INSERT INTO public.ai_routes (team_id, usage_key, profile_id)
SELECT NULL, 'vision.classify', j.id
  FROM public.ai_profiles j
 WHERE j.name = 'jev-router'
   AND NOT EXISTS (
       SELECT 1 FROM public.ai_routes r
       WHERE r.team_id IS NULL AND r.usage_key = 'vision.classify'
   )
ON CONFLICT DO NOTHING;

COMMIT;
