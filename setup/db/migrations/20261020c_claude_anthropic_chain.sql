-- 20261020c_claude_anthropic_chain — Claude runs only on the owner's two Anthropic keys, then MiniMax (owner, 2026-10-20).
--   Chain of every Claude profile: AngelStreet key (endpoint `anthropic`) -> Individual key (endpoint
--   `anthropic-individual`, a user key that needs the `anthropic-individual-workspace` secret) -> MiniMax M3
--   (`minimax-m3`; `minimax-m3-1-flash` for profiles that serve vision usages: MiniMax M3 reads no images).
--   The Individual endpoint is created DISABLED: the router steps over it until the workspace id is stored and the
--   endpoint enabled (Settings -> AI -> Endpoints). Claude profiles on OpenRouter are disabled; the router refuses
--   them anyway (router.claude_off_anthropic).
-- Only touches databases that have the lab's profile names; a no-op elsewhere. Idempotent.
-- Inverse: 20261020c_claude_anthropic_chain_rollback.sql. BUG-0721, docs/agent/ai/AI_ROUTING.md "Claude chain".

BEGIN;

INSERT INTO public.ai_endpoints (name, preset, secret_name, reach, timeout_s, enabled, region)
SELECT 'anthropic-individual', 'anthropic', 'anthropic-individual', 'server', a.timeout_s, false, a.region
FROM public.ai_endpoints a
WHERE a.name = 'anthropic'
ON CONFLICT (name) DO NOTHING;

-- (Claude profile on the AngelStreet key, MiniMax profile that ends its chain)
CREATE TEMP TABLE _claude_chain (claude TEXT, third TEXT) ON COMMIT DROP;
INSERT INTO _claude_chain VALUES
    ('claude-sonnet-5-5', 'minimax-m3'),
    ('claude-sonnet-4',   'minimax-m3'),
    ('haiku-text',        'minimax-m3'),
    ('claude-haiku-5-5',  'minimax-m3-1-flash'),
    ('haiku-vision',      'minimax-m3-1-flash');

-- Twin on the Individual key, same model and parameters, falling back to MiniMax.
INSERT INTO public.ai_profiles (name, endpoint_id, model, temperature, max_tokens_cap, thinking, image_max_edge,
                                extra, capabilities, enabled, fallback_profile_id)
SELECT c.claude || '-individual', ind.id, p.model, p.temperature, p.max_tokens_cap, p.thinking, p.image_max_edge,
       p.extra, p.capabilities, true, mm.id
FROM _claude_chain c
JOIN public.ai_profiles p ON p.name = c.claude
JOIN public.ai_endpoints ae ON ae.id = p.endpoint_id AND ae.name = 'anthropic'
JOIN public.ai_profiles mm ON mm.name = c.third
CROSS JOIN (SELECT id FROM public.ai_endpoints WHERE name = 'anthropic-individual') ind
ON CONFLICT (name) DO UPDATE SET fallback_profile_id = EXCLUDED.fallback_profile_id;

-- AngelStreet profile -> its Individual twin.
UPDATE public.ai_profiles p
SET fallback_profile_id = t.id
FROM _claude_chain c
JOIN public.ai_profiles t ON t.name = c.claude || '-individual'
WHERE p.name = c.claude;

-- No Claude through OpenRouter.
UPDATE public.ai_profiles p
SET enabled = false
FROM public.ai_endpoints e
WHERE e.id = p.endpoint_id AND e.preset <> 'anthropic'
  AND (lower(p.model) LIKE 'claude%' OR lower(p.model) LIKE 'anthropic/%' OR lower(p.model) LIKE '%/claude%');

COMMIT;
