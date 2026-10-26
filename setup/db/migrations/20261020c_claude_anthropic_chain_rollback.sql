-- 20261020c_claude_anthropic_chain_rollback — inverse of 20261020c: the fallbacks the lab had before
-- (haiku-text -> minimax-m3, haiku-vision -> minimax-m3-1-flash, the others none), the Individual twins and endpoint
-- removed, the OpenRouter Claude profiles enabled again (the router still refuses them: router.claude_off_anthropic).

BEGIN;

UPDATE public.ai_profiles SET fallback_profile_id = NULL
WHERE name IN ('claude-sonnet-5-5', 'claude-sonnet-4', 'claude-haiku-5-5');
UPDATE public.ai_profiles SET fallback_profile_id = (SELECT id FROM public.ai_profiles WHERE name = 'minimax-m3')
WHERE name = 'haiku-text';
UPDATE public.ai_profiles SET fallback_profile_id = (SELECT id FROM public.ai_profiles WHERE name = 'minimax-m3-1-flash')
WHERE name = 'haiku-vision';

DELETE FROM public.ai_profiles
WHERE endpoint_id = (SELECT id FROM public.ai_endpoints WHERE name = 'anthropic-individual');
DELETE FROM public.ai_endpoints WHERE name = 'anthropic-individual';

UPDATE public.ai_profiles SET enabled = true
WHERE name IN ('openrouter-claude-haiku-5-5', 'openrouter-claude-sonnet-5-5');

COMMIT;
