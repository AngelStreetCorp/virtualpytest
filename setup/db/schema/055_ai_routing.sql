-- 055 — AI usage routing (TASK-30). Same content as migration 20260929e_ai_routing.sql;
-- fresh installs get the tables and the seeded server default from here.
--
-- TASK-30: pick the AI model per usage, from one place.
--
-- Every AI call names a usage key (agent.atlas, vision.banner, analyzer.sherlock...).
-- These tables map usages to models:
--
--   ai_endpoints  where requests go (a provider preset + base URL + secret NAME; the key
--                 value lives server-side in ai_secrets.json, never here)
--   ai_profiles   a model on an endpoint, with its parameters and an optional fallback
--   ai_routes     usage -> profile. team_id NULL = the server default; a team row
--                 overrides it for that team. Optional scope (host / device model /
--                 userinterface) and A/B split.
--   ai_usage_stats hourly rollup of calls, errors, latency and tokens per usage.
--
-- Endpoints and profiles are server-level (no team column): one server = one
-- customer's default configuration. A team only adds route overrides.
--
-- The server default can never be empty: the default routes for the root usages
-- (agent, vision, text) cannot be deleted or disabled, only repointed.
--
-- Seed: the same providers/models the code used as defaults before TASK-30
-- (Anthropic Sonnet 4 for agents, OpenRouter qwen3-vl-8b for vision, OpenRouter
-- gpt-4.1-mini for text). Keys are added in Settings -> AI or by
-- scripts/ai_routing_import_env.py.
--
-- ⚠ Deploy order: apply this migration, run scripts/ai_routing_import_env.py on the
-- server (moves the old AI_* env config and keys into these tables / the secrets
-- file), THEN deploy the code. Old code ignores these tables; new code ignores env.
--
-- RLS: service_role only, anon/authenticated revoked (post-TASK-10 posture).
-- Idempotent: safe to re-run; the seed never overwrites edited rows.
-- Inverse: 20260929e_ai_routing_rollback.sql.

BEGIN;

CREATE TABLE IF NOT EXISTS public.ai_endpoints (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name             TEXT NOT NULL UNIQUE CHECK (name ~ '^[a-z0-9][a-z0-9_-]{0,62}$'),
    preset           TEXT NOT NULL CHECK (preset IN
                        ('anthropic', 'openrouter', 'openai', 'minimax', 'minimax_vlm', 'google', 'openai_compatible')),
    base_url         TEXT,
    secret_name      TEXT,
    reach            TEXT NOT NULL DEFAULT 'server' CHECK (reach IN ('server', 'host')),
    timeout_s        INTEGER NOT NULL DEFAULT 120 CHECK (timeout_s BETWEEN 5 AND 1800),
    max_concurrency  INTEGER CHECK (max_concurrency IS NULL OR max_concurrency > 0),
    allowed_team_ids UUID[],
    enabled          BOOLEAN NOT NULL DEFAULT true,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ai_endpoints_base_url_required
        CHECK (preset <> 'openai_compatible' OR (base_url IS NOT NULL AND length(btrim(base_url)) > 0)),
    CONSTRAINT ai_endpoints_host_reach_keyless
        CHECK (reach <> 'host' OR secret_name IS NULL)
);

CREATE TABLE IF NOT EXISTS public.ai_profiles (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name                TEXT NOT NULL UNIQUE CHECK (length(btrim(name)) > 0),
    endpoint_id         UUID NOT NULL REFERENCES public.ai_endpoints(id) ON DELETE RESTRICT,
    model               TEXT NOT NULL CHECK (length(btrim(model)) > 0),
    temperature         NUMERIC CHECK (temperature IS NULL OR (temperature >= 0 AND temperature <= 2)),
    max_tokens_cap      INTEGER CHECK (max_tokens_cap IS NULL OR max_tokens_cap > 0),
    thinking            TEXT NOT NULL DEFAULT 'auto' CHECK (thinking IN ('auto', 'on', 'off')),
    image_max_edge      INTEGER CHECK (image_max_edge IS NULL OR image_max_edge >= 64),
    extra               JSONB NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(extra) = 'object'),
    fallback_profile_id UUID REFERENCES public.ai_profiles(id) ON DELETE SET NULL,
    capabilities        TEXT[] NOT NULL DEFAULT '{}'::text[]
                        CHECK (capabilities <@ ARRAY['tools', 'vision', 'web']::text[]),
    enabled             BOOLEAN NOT NULL DEFAULT true,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ai_profiles_no_self_fallback CHECK (fallback_profile_id IS DISTINCT FROM id)
);

CREATE TABLE IF NOT EXISTS public.ai_routes (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    team_id            UUID REFERENCES public.teams(id) ON DELETE CASCADE,
    usage_key          TEXT NOT NULL CHECK (usage_key ~ '^[a-z][a-z0-9_.-]*$'),
    profile_id         UUID NOT NULL REFERENCES public.ai_profiles(id) ON DELETE RESTRICT,
    host_name          TEXT,
    device_model       TEXT,
    userinterface_name TEXT,
    split_profile_id   UUID REFERENCES public.ai_profiles(id) ON DELETE SET NULL,
    split_percent      INTEGER CHECK (split_percent IS NULL OR split_percent BETWEEN 1 AND 99),
    priority           INTEGER NOT NULL DEFAULT 100,
    enabled            BOOLEAN NOT NULL DEFAULT true,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT ai_routes_split_pair CHECK ((split_profile_id IS NULL) = (split_percent IS NULL))
);

-- One rule per (layer, usage, scope).
CREATE UNIQUE INDEX IF NOT EXISTS ai_routes_unique_scope ON public.ai_routes (
    COALESCE(team_id, '00000000-0000-0000-0000-000000000000'::uuid),
    usage_key,
    COALESCE(host_name, ''), COALESCE(device_model, ''), COALESCE(userinterface_name, '')
);
CREATE INDEX IF NOT EXISTS ai_routes_team_idx ON public.ai_routes (team_id);

-- The server default's root routes are the floor every usage falls back to.
CREATE OR REPLACE FUNCTION public.ai_routes_protect_roots() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.team_id IS NULL AND OLD.usage_key IN ('agent', 'vision', 'text')
       AND OLD.host_name IS NULL AND OLD.device_model IS NULL AND OLD.userinterface_name IS NULL THEN
        IF TG_OP = 'DELETE' THEN
            RAISE EXCEPTION 'The server default route for "%" cannot be deleted; repoint it instead', OLD.usage_key;
        END IF;
        IF NEW.enabled = false OR NEW.team_id IS NOT NULL OR NEW.usage_key <> OLD.usage_key
           OR NEW.host_name IS NOT NULL OR NEW.device_model IS NOT NULL OR NEW.userinterface_name IS NOT NULL THEN
            RAISE EXCEPTION 'The server default route for "%" can only be repointed', OLD.usage_key;
        END IF;
    END IF;
    IF TG_OP = 'DELETE' THEN
        RETURN OLD;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS ai_routes_protect_roots ON public.ai_routes;
CREATE TRIGGER ai_routes_protect_roots BEFORE UPDATE OR DELETE ON public.ai_routes
    FOR EACH ROW EXECUTE FUNCTION public.ai_routes_protect_roots();

CREATE TABLE IF NOT EXISTS public.ai_usage_stats (
    bucket      TIMESTAMPTZ NOT NULL,
    usage_key   TEXT NOT NULL,
    team_id     UUID REFERENCES public.teams(id) ON DELETE CASCADE,
    profile     TEXT NOT NULL,
    endpoint    TEXT NOT NULL,
    split_arm   TEXT NOT NULL DEFAULT '',
    calls       INTEGER NOT NULL DEFAULT 0,
    errors      INTEGER NOT NULL DEFAULT 0,
    fallbacks   INTEGER NOT NULL DEFAULT 0,
    total_ms    BIGINT NOT NULL DEFAULT 0,
    tokens_in   BIGINT NOT NULL DEFAULT 0,
    tokens_out  BIGINT NOT NULL DEFAULT 0
);
CREATE UNIQUE INDEX IF NOT EXISTS ai_usage_stats_key ON public.ai_usage_stats (
    bucket, usage_key, COALESCE(team_id, '00000000-0000-0000-0000-000000000000'::uuid), profile, split_arm
);

-- Atomic increment (PostgREST upsert cannot add to an existing row).
CREATE OR REPLACE FUNCTION public.ai_usage_stats_bump(
    p_usage_key TEXT, p_team_id UUID, p_profile TEXT, p_endpoint TEXT, p_split_arm TEXT,
    p_ok BOOLEAN, p_fallback BOOLEAN, p_ms INTEGER, p_tokens_in INTEGER, p_tokens_out INTEGER
) RETURNS void LANGUAGE sql AS $$
    INSERT INTO public.ai_usage_stats AS s
        (bucket, usage_key, team_id, profile, endpoint, split_arm, calls, errors, fallbacks, total_ms, tokens_in, tokens_out)
    VALUES (date_trunc('hour', NOW()), p_usage_key, p_team_id, p_profile, p_endpoint, COALESCE(p_split_arm, ''),
            1, CASE WHEN p_ok THEN 0 ELSE 1 END, CASE WHEN p_fallback THEN 1 ELSE 0 END,
            GREATEST(p_ms, 0), GREATEST(p_tokens_in, 0), GREATEST(p_tokens_out, 0))
    ON CONFLICT (bucket, usage_key, COALESCE(team_id, '00000000-0000-0000-0000-000000000000'::uuid), profile, split_arm)
    DO UPDATE SET calls = s.calls + 1,
                  errors = s.errors + EXCLUDED.errors,
                  fallbacks = s.fallbacks + EXCLUDED.fallbacks,
                  total_ms = s.total_ms + EXCLUDED.total_ms,
                  tokens_in = s.tokens_in + EXCLUDED.tokens_in,
                  tokens_out = s.tokens_out + EXCLUDED.tokens_out,
                  endpoint = EXCLUDED.endpoint;
$$;

-- ---------------------------------------------------------------- seed (default)
INSERT INTO public.ai_endpoints (name, preset, secret_name) VALUES
    ('anthropic', 'anthropic', 'anthropic'),
    ('openrouter', 'openrouter', 'openrouter')
ON CONFLICT (name) DO NOTHING;

INSERT INTO public.ai_profiles (name, endpoint_id, model, capabilities)
SELECT v.name, e.id, v.model, v.caps
FROM (VALUES
    ('claude-sonnet-4', 'anthropic', 'claude-sonnet-4-20250514', ARRAY['tools', 'vision']::text[]),
    ('qwen3-vl-8b', 'openrouter', 'qwen/qwen3-vl-8b-instruct', ARRAY['vision']::text[]),
    ('gpt-4.1-mini', 'openrouter', 'openai/gpt-4.1-mini', ARRAY['tools', 'vision']::text[])
) AS v(name, endpoint, model, caps)
JOIN public.ai_endpoints e ON e.name = v.endpoint
ON CONFLICT (name) DO NOTHING;

INSERT INTO public.ai_routes (team_id, usage_key, profile_id)
SELECT NULL, v.usage_key, p.id
FROM (VALUES ('agent', 'claude-sonnet-4'), ('vision', 'qwen3-vl-8b'), ('text', 'gpt-4.1-mini'))
     AS v(usage_key, profile)
JOIN public.ai_profiles p ON p.name = v.profile
WHERE NOT EXISTS (
    SELECT 1 FROM public.ai_routes r
    WHERE r.team_id IS NULL AND r.usage_key = v.usage_key
      AND r.host_name IS NULL AND r.device_model IS NULL AND r.userinterface_name IS NULL
);

-- ---------------------------------------------------------------- RLS
ALTER TABLE public.ai_endpoints ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ai_profiles ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ai_routes ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.ai_usage_stats ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "service_role_all_ai_endpoints" ON public.ai_endpoints;
CREATE POLICY "service_role_all_ai_endpoints" ON public.ai_endpoints
    FOR ALL TO service_role USING (true) WITH CHECK (true);
DROP POLICY IF EXISTS "service_role_all_ai_profiles" ON public.ai_profiles;
CREATE POLICY "service_role_all_ai_profiles" ON public.ai_profiles
    FOR ALL TO service_role USING (true) WITH CHECK (true);
DROP POLICY IF EXISTS "service_role_all_ai_routes" ON public.ai_routes;
CREATE POLICY "service_role_all_ai_routes" ON public.ai_routes
    FOR ALL TO service_role USING (true) WITH CHECK (true);
DROP POLICY IF EXISTS "service_role_all_ai_usage_stats" ON public.ai_usage_stats;
CREATE POLICY "service_role_all_ai_usage_stats" ON public.ai_usage_stats
    FOR ALL TO service_role USING (true) WITH CHECK (true);

REVOKE ALL ON public.ai_endpoints, public.ai_profiles, public.ai_routes, public.ai_usage_stats
    FROM anon, authenticated;
REVOKE ALL ON FUNCTION public.ai_usage_stats_bump(TEXT, UUID, TEXT, TEXT, TEXT, BOOLEAN, BOOLEAN, INTEGER, INTEGER, INTEGER)
    FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.ai_usage_stats_bump(TEXT, UUID, TEXT, TEXT, TEXT, BOOLEAN, BOOLEAN, INTEGER, INTEGER, INTEGER)
    TO service_role;

COMMIT;
