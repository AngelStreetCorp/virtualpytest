-- 20261012b_ai_calls.sql
-- TASK-87 — AI usage analytics. WRITTEN, NOT YET APPLIED: apply only after the owner signs off.
--   * ai_calls            per-call log (who called which model, tokens, latency, cost, errors), 90-day retention
--   * ai_usage_stats      hourly rollup gains origin, host_name (in the key), cost, cache / reasoning / web
--                         tokens, avoided; ai_usage_stats_bump keeps working, ai_calls_ingest is the new writer
--   * ai_calls_rollup()   the read behind Monitoring -> AI usage (every dimension, hour / day buckets)
--   * ai_endpoints.region data-residency label shown on the AI usage page
--   * ai_training_samples index on source_ref->>'request_id' (link a sample to the call that produced it)
--   * retention.cleanup_ai_calls() wired into retention.cleanup_all() (static member list, see 20261006a)
-- RLS: service_role only. Idempotent. Canonical twin: setup/db/schema/063_ai_calls.sql. Inverse: 20261012b_ai_calls_rollback.sql.
-- Apply to EVERY database the release reaches (each customer install), before or with the deploy.

BEGIN;

-- ---------------------------------------------------------------- per-call log
-- One row per billed request (or skipped hop / avoided call). No prompt, no answer: text lives in
-- Langfuse (request_id = Langfuse trace id). Tenant is joined from teams, workspace from the user.
CREATE TABLE IF NOT EXISTS public.ai_calls (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ts                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    server              TEXT,
    request_id          TEXT,
    usage_key           TEXT NOT NULL,
    team_id             UUID,
    user_id             TEXT,
    origin              TEXT NOT NULL DEFAULT 'unknown',
    route               TEXT,
    script_name         TEXT,
    script_result_id    TEXT,
    campaign_id         TEXT,
    host_name           TEXT,
    device_id           TEXT,
    device_model        TEXT,
    userinterface_name  TEXT,
    session_id          TEXT,
    client_hash         TEXT,
    turn_index          INTEGER,
    tool_calls          INTEGER,
    stop_reason         TEXT,
    split_arm           TEXT NOT NULL DEFAULT '',
    profile             TEXT NOT NULL,
    endpoint            TEXT NOT NULL,
    model               TEXT,
    effort_sent         TEXT,
    fallback_used       BOOLEAN NOT NULL DEFAULT false,
    attempt_index       INTEGER NOT NULL DEFAULT 0,
    ok                  BOOLEAN NOT NULL,
    outcome             TEXT NOT NULL DEFAULT 'served' CHECK (outcome IN ('served', 'skipped', 'avoided')),
    error_type          TEXT CHECK (error_type IS NULL OR error_type IN (
                            'timeout', 'rate_limit', 'no_credit', 'auth', 'bad_request', 'server', 'connection',
                            'empty_answer', 'busy', 'parse', 'refusal', 'other')),
    tokens_in           INTEGER NOT NULL DEFAULT 0,
    tokens_out          INTEGER NOT NULL DEFAULT 0,
    tokens_cache_read   INTEGER NOT NULL DEFAULT 0,
    tokens_cache_write  INTEGER NOT NULL DEFAULT 0,
    tokens_reasoning    INTEGER NOT NULL DEFAULT 0,
    web_searches        INTEGER NOT NULL DEFAULT 0,
    images              INTEGER NOT NULL DEFAULT 0,
    image_bytes         INTEGER NOT NULL DEFAULT 0,
    parse_ok            BOOLEAN,
    latency_ms          INTEGER NOT NULL DEFAULT 0,
    cost                NUMERIC(14, 8),
    cost_source         TEXT NOT NULL DEFAULT 'none' CHECK (cost_source IN ('provider', 'price_table', 'none')),
    cache_saved         NUMERIC(14, 8)
);
CREATE INDEX IF NOT EXISTS ai_calls_ts_idx ON public.ai_calls (ts);
CREATE INDEX IF NOT EXISTS ai_calls_team_ts_idx ON public.ai_calls (team_id, ts);
CREATE INDEX IF NOT EXISTS ai_calls_usage_ts_idx ON public.ai_calls (usage_key, ts);
CREATE INDEX IF NOT EXISTS ai_calls_script_result_idx ON public.ai_calls (script_result_id) WHERE script_result_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS ai_calls_request_idx ON public.ai_calls (request_id) WHERE request_id IS NOT NULL;

COMMENT ON TABLE public.ai_calls IS
    'TASK-87 per-call AI log, 90-day retention (retention.cleanup_ai_calls). No prompt or answer text: request_id is the Langfuse trace id.';

ALTER TABLE public.ai_calls ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "service_role_all_ai_calls" ON public.ai_calls;
CREATE POLICY "service_role_all_ai_calls" ON public.ai_calls FOR ALL TO service_role USING (true) WITH CHECK (true);
REVOKE ALL ON public.ai_calls FROM anon, authenticated;

-- ---------------------------------------------------------------- hourly rollup (kept forever)
ALTER TABLE public.ai_usage_stats
    ADD COLUMN IF NOT EXISTS origin             TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS host_name          TEXT NOT NULL DEFAULT '',
    ADD COLUMN IF NOT EXISTS cost               NUMERIC(14, 6) NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS priced_calls       INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS cache_saved        NUMERIC(14, 6) NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS tokens_cache_read  BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS tokens_cache_write BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS tokens_reasoning   BIGINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS web_searches       INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS avoided            INTEGER NOT NULL DEFAULT 0;

-- origin and host become part of the key, so the Monitoring page can group by them for 30 days.
CREATE UNIQUE INDEX IF NOT EXISTS ai_usage_stats_key_origin ON public.ai_usage_stats (
    bucket, usage_key, COALESCE(team_id, '00000000-0000-0000-0000-000000000000'::uuid), profile, split_arm,
    origin, host_name
);
DROP INDEX IF EXISTS public.ai_usage_stats_key;

-- The previous writer, kept working during a rolling deploy: rows land with origin = '' / host = ''.
CREATE OR REPLACE FUNCTION public.ai_usage_stats_bump(
    p_usage_key TEXT, p_team_id UUID, p_profile TEXT, p_endpoint TEXT, p_split_arm TEXT,
    p_ok BOOLEAN, p_fallback BOOLEAN, p_ms INTEGER, p_tokens_in INTEGER, p_tokens_out INTEGER
) RETURNS void LANGUAGE sql AS $$
    INSERT INTO public.ai_usage_stats AS s
        (bucket, usage_key, team_id, profile, endpoint, split_arm, origin, host_name, calls, errors, fallbacks,
         total_ms, tokens_in, tokens_out)
    VALUES (date_trunc('hour', NOW()), p_usage_key, p_team_id, p_profile, p_endpoint, COALESCE(p_split_arm, ''),
            '', '', 1, CASE WHEN p_ok THEN 0 ELSE 1 END, CASE WHEN p_fallback THEN 1 ELSE 0 END,
            GREATEST(p_ms, 0), GREATEST(p_tokens_in, 0), GREATEST(p_tokens_out, 0))
    ON CONFLICT (bucket, usage_key, COALESCE(team_id, '00000000-0000-0000-0000-000000000000'::uuid), profile,
                 split_arm, origin, host_name)
    DO UPDATE SET calls = s.calls + 1,
                  errors = s.errors + EXCLUDED.errors,
                  fallbacks = s.fallbacks + EXCLUDED.fallbacks,
                  total_ms = s.total_ms + EXCLUDED.total_ms,
                  tokens_in = s.tokens_in + EXCLUDED.tokens_in,
                  tokens_out = s.tokens_out + EXCLUDED.tokens_out,
                  endpoint = EXCLUDED.endpoint;
$$;

-- One round trip per batch: insert the call rows and bump the hourly rollup from the same JSON.
-- A 'skipped' row (hop never tried: host-only endpoint on the server, no web search) is logged but not
-- counted; an 'avoided' row (a cache or rule made the call unnecessary) counts only in `avoided`.
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
        web_searches, images, image_bytes, parse_ok, latency_ms, cost, cost_source, cache_saved)
    SELECT COALESCE(x.ts, NOW()), x.server, x.request_id, x.usage_key, x.team_id, x.user_id,
           COALESCE(x.origin, 'unknown'), x.route, x.script_name, x.script_result_id, x.campaign_id, x.host_name,
           x.device_id, x.device_model, x.userinterface_name, x.session_id, x.client_hash, x.turn_index,
           x.tool_calls, x.stop_reason, COALESCE(x.split_arm, ''), x.profile, x.endpoint, x.model, x.effort_sent,
           COALESCE(x.fallback_used, false), COALESCE(x.attempt_index, 0), x.ok, COALESCE(x.outcome, 'served'),
           x.error_type, COALESCE(x.tokens_in, 0), COALESCE(x.tokens_out, 0), COALESCE(x.tokens_cache_read, 0),
           COALESCE(x.tokens_cache_write, 0), COALESCE(x.tokens_reasoning, 0), COALESCE(x.web_searches, 0),
           COALESCE(x.images, 0), COALESCE(x.image_bytes, 0), x.parse_ok, COALESCE(x.latency_ms, 0), x.cost,
           COALESCE(x.cost_source, 'none'), x.cache_saved
    FROM jsonb_to_recordset(p_rows) AS x(
        ts TIMESTAMPTZ, server TEXT, request_id TEXT, usage_key TEXT, team_id UUID, user_id TEXT, origin TEXT,
        route TEXT, script_name TEXT, script_result_id TEXT, campaign_id TEXT, host_name TEXT, device_id TEXT,
        device_model TEXT, userinterface_name TEXT, session_id TEXT, client_hash TEXT, turn_index INTEGER,
        tool_calls INTEGER, stop_reason TEXT, split_arm TEXT, profile TEXT, endpoint TEXT, model TEXT,
        effort_sent TEXT, fallback_used BOOLEAN, attempt_index INTEGER, ok BOOLEAN, outcome TEXT,
        error_type TEXT, tokens_in INTEGER, tokens_out INTEGER, tokens_cache_read INTEGER,
        tokens_cache_write INTEGER, tokens_reasoning INTEGER, web_searches INTEGER, images INTEGER,
        image_bytes INTEGER, parse_ok BOOLEAN, latency_ms INTEGER, cost NUMERIC, cost_source TEXT,
        cache_saved NUMERIC);
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

-- ---------------------------------------------------------------- reads for Monitoring -> AI usage
-- The page groups by user / script / device / server, which the hourly rollup does not carry: this
-- aggregates ai_calls by every dimension at once (hour or day buckets) as one JSON array, so the
-- API can regroup it and filter without scanning raw rows. p_user limits to one person's calls
-- (a viewer sees only their own); p_all drops the team filter (platform admin).
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
               COALESCE(sum(images), 0) AS images, COALESCE(sum(image_bytes), 0) AS image_bytes
        FROM public.ai_calls
        WHERE ts >= p_since AND outcome <> 'skipped'
          AND (p_all OR team_id IS NULL OR team_id = p_team)
          AND (p_user IS NULL OR user_id = p_user)
        GROUP BY 1, usage_key, team_id, profile, endpoint, split_arm, origin, COALESCE(host_name, ''),
                 COALESCE(device_id, ''), COALESCE(script_name, ''), COALESCE(campaign_id, ''),
                 COALESCE(user_id, ''), COALESCE(server, ''), COALESCE(error_type, ''), COALESCE(client_hash, '')
    ) r
$$;

REVOKE ALL ON FUNCTION public.ai_calls_rollup(TIMESTAMPTZ, UUID, BOOLEAN, TEXT, TEXT) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.ai_calls_rollup(TIMESTAMPTZ, UUID, BOOLEAN, TEXT, TEXT) TO service_role;

-- ---------------------------------------------------------------- endpoint region (data residency)
ALTER TABLE public.ai_endpoints ADD COLUMN IF NOT EXISTS region TEXT;
COMMENT ON COLUMN public.ai_endpoints.region IS
    'Free text shown on the AI usage page: where this provider hosts the data (e.g. EU, US, local).';

-- ---------------------------------------------------------------- training sample <-> call link
-- Samples carry the call's request id in source_ref (written at capture); this finds the call.
CREATE INDEX IF NOT EXISTS idx_ai_training_samples_request
    ON public.ai_training_samples ((source_ref ->> 'request_id'))
    WHERE (source_ref ->> 'request_id') IS NOT NULL;

-- ---------------------------------------------------------------- 90-day retention
-- Mirrors retention.cleanup_training_samples() in 20261006a. The member list of cleanup_all() is
-- STATIC: keep it equal to the functions that exist in `retention`, or the nightly job skips one.
CREATE OR REPLACE FUNCTION retention.cleanup_ai_calls()
RETURNS TABLE(deleted_count INTEGER, table_name TEXT, retention_days INTEGER)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'retention', 'public', 'extensions'
AS $$
DECLARE
  v_deleted_count INTEGER;
  v_days CONSTANT INTEGER := 90;
BEGIN
  DELETE FROM public.ai_calls WHERE ts < NOW() - (v_days || ' days')::INTERVAL;
  GET DIAGNOSTICS v_deleted_count = ROW_COUNT;
  RAISE NOTICE '[retention] Deleted % records from ai_calls (% day retention)', v_deleted_count, v_days;
  RETURN QUERY SELECT v_deleted_count, 'ai_calls'::TEXT, v_days;
END;
$$;

CREATE OR REPLACE FUNCTION retention.cleanup_all()
RETURNS TABLE(deleted_count INTEGER, table_name TEXT, retention_days INTEGER, executed_at TIMESTAMPTZ)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'retention', 'public', 'extensions'
AS $$
BEGIN
  RAISE NOTICE '[retention] Starting scheduled cleanup at %', NOW();

  RETURN QUERY
  SELECT *, NOW() as executed_at FROM retention.cleanup_system_device_metrics()
  UNION ALL
  SELECT *, NOW() as executed_at FROM retention.cleanup_system_metrics()
  UNION ALL
  SELECT *, NOW() as executed_at FROM retention.cleanup_alerts()
  UNION ALL
  SELECT *, NOW() as executed_at FROM retention.cleanup_adhoc_deployment_receipts()
  UNION ALL
  SELECT *, NOW() as executed_at FROM retention.cleanup_quality_metrics()
  UNION ALL
  SELECT *, NOW() as executed_at FROM retention.cleanup_training_samples()
  UNION ALL
  SELECT *, NOW() as executed_at FROM retention.cleanup_ai_calls();

  RAISE NOTICE '[retention] Completed scheduled cleanup at %', NOW();
END;
$$;

COMMIT;
