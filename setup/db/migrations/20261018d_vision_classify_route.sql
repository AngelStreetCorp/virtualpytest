-- vision.classify (product path, 2026-10-17): the closed-choice stage of the
-- unknown-screen classifier.
--
-- screen_classifier.classify_screen offers the abstaining interface's real
-- node ids to a chat model.  typesafe/jev-router is the verified image-capable
-- closed-choice model (2026-10-17: answered a red/blue two-option probe
-- correctly through the chat API).  The open-set fallback (qwen3-vl-8b) is
-- pinned in the code, not routed.
--
-- Idempotent: the profile is inserted only when absent, and the route only
-- when no default route for the usage exists yet.

BEGIN;

INSERT INTO public.ai_profiles (name, endpoint_id, model, capabilities, thinking)
SELECT 'jev-router', e.id, 'typesafe/jev-router', ARRAY['vision']::text[], 'off'
FROM public.ai_endpoints e
WHERE e.name = 'openrouter'
ON CONFLICT (name) DO NOTHING;

-- A classifier wants the answer, not reasoning tokens.
UPDATE public.ai_profiles
SET thinking = 'off', updated_at = NOW()
WHERE name = 'jev-router' AND thinking <> 'off';

INSERT INTO public.ai_routes (team_id, usage_key, profile_id)
SELECT NULL, 'vision.classify', p.id
FROM public.ai_profiles p
WHERE p.name = 'jev-router'
  AND NOT EXISTS (
      SELECT 1 FROM public.ai_routes r
      WHERE r.team_id IS NULL AND r.usage_key = 'vision.classify'
  )
ON CONFLICT DO NOTHING;

COMMIT;
