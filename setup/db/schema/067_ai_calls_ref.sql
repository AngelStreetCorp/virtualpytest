-- 067_ai_calls_ref — TASK-87 O17: ai_calls records WHAT a call was about, in three generic columns usable by any feature:
--   ref_type  the kind of thing ('alert' for an alert-triage call), ref_id its id, ref_kind its sub-kind
--   (an alert's incident type: freeze, blackscreen, audio, macroblocks, zap…).
-- ai_calls_ingest() writes them; ai_calls_rollup() also groups by ref_type / ref_kind (the "Incident type" grouping).
-- WRITTEN, NOT APPLIED. Idempotent. Apply to every database the release reaches. The code works without it: the
-- writer's unknown JSON keys are ignored by jsonb_to_recordset, and the page hides "Incident type" while the rollup
-- carries no ref_kind. Twin: setup/db/migrations/20261013a_ai_calls_ref.sql. Inverse: 20261013a_ai_calls_ref_rollback.sql (drops the data).

BEGIN;

ALTER TABLE public.ai_calls ADD COLUMN IF NOT EXISTS ref_type TEXT;
ALTER TABLE public.ai_calls ADD COLUMN IF NOT EXISTS ref_id TEXT;
ALTER TABLE public.ai_calls ADD COLUMN IF NOT EXISTS ref_kind TEXT;
CREATE INDEX IF NOT EXISTS ai_calls_ref_idx ON public.ai_calls (ref_type, ref_id) WHERE ref_id IS NOT NULL;

CREATE OR REPLACE FUNCTION public.ai_calls_ingest(p_rows JSONB) RETURNS INTEGER
LANGUAGE plpgsql AS $$
DECLARE
    n INTEGER;
BEGIN
    INSERT INTO public.ai_calls (
        ts, server, request_id, usage_key, team_id, user_id, origin, route, script_name, script_result_id,
        campaign_id, host_name, device_id, device_model, userinterface_name, session_id, client_hash, turn_index,
        tool_calls, stop_reason, split_arm, profile, endpoint, model, effort_sent, fallback_used, attempt_index,
        ok, outcome, error_type, tokens_in, tokens_out, tokens_cache_read, tokens_cache_write, tokens_reasoning,
        web_searches, images, image_bytes, parse_ok, latency_ms, cost, cost_source, cache_saved,
        ref_type, ref_id, ref_kind)
    SELECT COALESCE(x.ts, NOW()), x.server, x.request_id, x.usage_key, x.team_id, x.user_id,
           COALESCE(x.origin, 'unknown'), x.route, x.script_name, x.script_result_id, x.campaign_id, x.host_name,
           x.device_id, x.device_model, x.userinterface_name, x.session_id, x.client_hash, x.turn_index,
           x.tool_calls, x.stop_reason, COALESCE(x.split_arm, ''), x.profile, x.endpoint, x.model, x.effort_sent,
           COALESCE(x.fallback_used, false), COALESCE(x.attempt_index, 0), x.ok, COALESCE(x.outcome, 'served'),
           x.error_type, COALESCE(x.tokens_in, 0), COALESCE(x.tokens_out, 0), COALESCE(x.tokens_cache_read, 0),
           COALESCE(x.tokens_cache_write, 0), COALESCE(x.tokens_reasoning, 0), COALESCE(x.web_searches, 0),
           COALESCE(x.images, 0), COALESCE(x.image_bytes, 0), x.parse_ok, COALESCE(x.latency_ms, 0), x.cost,
           COALESCE(x.cost_source, 'none'), x.cache_saved,
           x.ref_type, x.ref_id, x.ref_kind
    FROM jsonb_to_recordset(p_rows) AS x(
        ts TIMESTAMPTZ, server TEXT, request_id TEXT, usage_key TEXT, team_id UUID, user_id TEXT, origin TEXT,
        route TEXT, script_name TEXT, script_result_id TEXT, campaign_id TEXT, host_name TEXT, device_id TEXT,
        device_model TEXT, userinterface_name TEXT, session_id TEXT, client_hash TEXT, turn_index INTEGER,
        tool_calls INTEGER, stop_reason TEXT, split_arm TEXT, profile TEXT, endpoint TEXT, model TEXT,
        effort_sent TEXT, fallback_used BOOLEAN, attempt_index INTEGER, ok BOOLEAN, outcome TEXT,
        error_type TEXT, tokens_in INTEGER, tokens_out INTEGER, tokens_cache_read INTEGER,
        tokens_cache_write INTEGER, tokens_reasoning INTEGER, web_searches INTEGER, images INTEGER,
        image_bytes INTEGER, parse_ok BOOLEAN, latency_ms INTEGER, cost NUMERIC, cost_source TEXT,
        cache_saved NUMERIC, ref_type TEXT, ref_id TEXT, ref_kind TEXT);
    GET DIAGNOSTICS n = ROW_COUNT;

    INSERT INTO public.ai_usage_stats AS s
        (bucket, usage_key, team_id, profile, endpoint, split_arm, origin, host_name, calls, errors, fallbacks,
         total_ms, tokens_in, tokens_out, cost, priced_calls, tokens_cache_read, tokens_cache_write,
         tokens_reasoning, web_searches, avoided, cache_saved)
    SELECT date_trunc('hour', COALESCE(x.ts, NOW())), x.usage_key, x.team_id, x.profile, max(x.endpoint),
           COALESCE(x.split_arm, ''), COALESCE(x.origin, ''), COALESCE(x.host_name, ''),
           count(*) FILTER (WHERE COALESCE(x.outcome, 'served') = 'served'),
           count(*) FILTER (WHERE COALESCE(x.outcome, 'served') = 'served' AND NOT x.ok),
           count(*) FILTER (WHERE COALESCE(x.outcome, 'served') = 'served' AND COALESCE(x.fallback_used, false)),
           COALESCE(sum(GREATEST(COALESCE(x.latency_ms, 0), 0)) FILTER (WHERE COALESCE(x.outcome, 'served') = 'served'), 0),
           COALESCE(sum(GREATEST(COALESCE(x.tokens_in, 0), 0)), 0),
           COALESCE(sum(GREATEST(COALESCE(x.tokens_out, 0), 0)), 0),
           COALESCE(sum(x.cost), 0),
           count(*) FILTER (WHERE x.cost IS NOT NULL),
           COALESCE(sum(COALESCE(x.tokens_cache_read, 0)), 0),
           COALESCE(sum(COALESCE(x.tokens_cache_write, 0)), 0),
           COALESCE(sum(COALESCE(x.tokens_reasoning, 0)), 0),
           COALESCE(sum(COALESCE(x.web_searches, 0)), 0),
           count(*) FILTER (WHERE x.outcome = 'avoided'),
           COALESCE(sum(x.cache_saved), 0)
    FROM jsonb_to_recordset(p_rows) AS x(
        ts TIMESTAMPTZ, usage_key TEXT, team_id UUID, profile TEXT, endpoint TEXT, split_arm TEXT, origin TEXT,
        host_name TEXT, outcome TEXT, ok BOOLEAN, fallback_used BOOLEAN, latency_ms INTEGER, tokens_in INTEGER,
        tokens_out INTEGER, cost NUMERIC, tokens_cache_read INTEGER, tokens_cache_write INTEGER,
        tokens_reasoning INTEGER, web_searches INTEGER, cache_saved NUMERIC)
    WHERE COALESCE(x.outcome, 'served') <> 'skipped'
    GROUP BY 1, x.usage_key, x.team_id, x.profile, COALESCE(x.split_arm, ''), COALESCE(x.origin, ''),
             COALESCE(x.host_name, '')
    ON CONFLICT (bucket, usage_key, COALESCE(team_id, '00000000-0000-0000-0000-000000000000'::uuid), profile,
                 split_arm, origin, host_name)
    DO UPDATE SET calls = s.calls + EXCLUDED.calls,
                  errors = s.errors + EXCLUDED.errors,
                  fallbacks = s.fallbacks + EXCLUDED.fallbacks,
                  total_ms = s.total_ms + EXCLUDED.total_ms,
                  tokens_in = s.tokens_in + EXCLUDED.tokens_in,
                  tokens_out = s.tokens_out + EXCLUDED.tokens_out,
                  cost = s.cost + EXCLUDED.cost,
                  priced_calls = s.priced_calls + EXCLUDED.priced_calls,
                  tokens_cache_read = s.tokens_cache_read + EXCLUDED.tokens_cache_read,
                  tokens_cache_write = s.tokens_cache_write + EXCLUDED.tokens_cache_write,
                  tokens_reasoning = s.tokens_reasoning + EXCLUDED.tokens_reasoning,
                  web_searches = s.web_searches + EXCLUDED.web_searches,
                  avoided = s.avoided + EXCLUDED.avoided,
                  cache_saved = s.cache_saved + EXCLUDED.cache_saved,
                  endpoint = EXCLUDED.endpoint;
    RETURN n;
END;
$$;

REVOKE ALL ON FUNCTION public.ai_calls_ingest(JSONB) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.ai_calls_ingest(JSONB) TO service_role;

CREATE OR REPLACE FUNCTION public.ai_calls_rollup(
    p_since TIMESTAMPTZ, p_team UUID, p_all BOOLEAN, p_step TEXT DEFAULT 'hour', p_user TEXT DEFAULT NULL
) RETURNS JSONB LANGUAGE sql STABLE AS $$
    SELECT COALESCE(jsonb_agg(to_jsonb(r)), '[]'::jsonb) FROM (
        SELECT date_trunc(CASE WHEN p_step = 'day' THEN 'day' ELSE 'hour' END, ts) AS bucket,
               usage_key, team_id, profile, endpoint, split_arm, origin,
               COALESCE(host_name, '') AS host_name, COALESCE(device_id, '') AS device_id,
               COALESCE(script_name, '') AS script_name, COALESCE(campaign_id, '') AS campaign_id,
               COALESCE(user_id, '') AS user_id, COALESCE(server, '') AS server,
               COALESCE(error_type, '') AS error_type, COALESCE(client_hash, '') AS client_hash,
               COALESCE(ref_type, '') AS ref_type, COALESCE(ref_kind, '') AS ref_kind,
               count(*) FILTER (WHERE outcome = 'served') AS calls,
               count(*) FILTER (WHERE outcome = 'served' AND NOT ok) AS errors,
               count(*) FILTER (WHERE outcome = 'served' AND fallback_used) AS fallbacks,
               COALESCE(sum(latency_ms) FILTER (WHERE outcome = 'served'), 0) AS total_ms,
               COALESCE(sum(tokens_in), 0) AS tokens_in, COALESCE(sum(tokens_out), 0) AS tokens_out,
               COALESCE(sum(tokens_cache_read), 0) AS tokens_cache_read,
               COALESCE(sum(tokens_cache_write), 0) AS tokens_cache_write,
               COALESCE(sum(tokens_reasoning), 0) AS tokens_reasoning,
               COALESCE(sum(web_searches), 0) AS web_searches,
               COALESCE(sum(cost), 0) AS cost, count(*) FILTER (WHERE cost IS NOT NULL) AS priced_calls,
               COALESCE(sum(cache_saved), 0) AS cache_saved,
               count(*) FILTER (WHERE outcome = 'avoided') AS avoided,
               count(*) FILTER (WHERE parse_ok IS NOT NULL) AS parse_total,
               count(*) FILTER (WHERE parse_ok) AS parse_ok_n,
               count(*) FILTER (WHERE stop_reason = 'max_tokens') AS truncated,
               COALESCE(sum(images), 0) AS images, COALESCE(sum(image_bytes), 0) AS image_bytes,
               min(ts) FILTER (WHERE outcome = 'served') AS first_ts, max(ts) FILTER (WHERE outcome = 'served') AS last_ts
        FROM public.ai_calls
        WHERE ts >= p_since AND outcome <> 'skipped'
          AND (p_all OR team_id IS NULL OR team_id = p_team)
          AND (p_user IS NULL OR user_id = p_user)
        GROUP BY 1, usage_key, team_id, profile, endpoint, split_arm, origin, COALESCE(host_name, ''),
                 COALESCE(device_id, ''), COALESCE(script_name, ''), COALESCE(campaign_id, ''),
                 COALESCE(user_id, ''), COALESCE(server, ''), COALESCE(error_type, ''), COALESCE(client_hash, ''),
                 COALESCE(ref_type, ''), COALESCE(ref_kind, '')
    ) r
$$;

REVOKE ALL ON FUNCTION public.ai_calls_rollup(TIMESTAMPTZ, UUID, BOOLEAN, TEXT, TEXT) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.ai_calls_rollup(TIMESTAMPTZ, UUID, BOOLEAN, TEXT, TEXT) TO service_role;

COMMIT;
