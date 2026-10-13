-- 20261012e_ai_calls_rollup_times.sql — TASK-87 review round 1: ai_calls_rollup() also returns the first and last
-- request time of every group (first_ts, last_ts), so the AI usage page can say "since 21:44 · last 22:41" and
-- show the last call per feature to the minute instead of the hour. Same signature; additive columns only.
-- No data change. Idempotent. Twin: setup/db/schema/066_ai_calls_rollup_times.sql. Inverse: 20261012e_ai_calls_rollup_times_rollback.sql.
-- The page works without it (it falls back to the hour bucket); apply to every database the release reaches.

BEGIN;

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
               COALESCE(sum(images), 0) AS images, COALESCE(sum(image_bytes), 0) AS image_bytes,
               min(ts) FILTER (WHERE outcome = 'served') AS first_ts, max(ts) FILTER (WHERE outcome = 'served') AS last_ts
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

COMMIT;
