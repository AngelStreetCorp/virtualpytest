-- 20261012b_ai_calls_rollback.sql — inverse of 20261012b_ai_calls.sql.
-- Drops the call log and the extra rollup columns (their history is lost). cleanup_all() is rebuilt
-- WITHOUT cleanup_ai_calls: it must be re-created before the function is dropped.

BEGIN;

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
  SELECT *, NOW() as executed_at FROM retention.cleanup_training_samples();

  RAISE NOTICE '[retention] Completed scheduled cleanup at %', NOW();
END;
$$;

DROP FUNCTION IF EXISTS retention.cleanup_ai_calls();
DROP INDEX IF EXISTS public.idx_ai_training_samples_request;
ALTER TABLE public.ai_endpoints DROP COLUMN IF EXISTS region;
DROP FUNCTION IF EXISTS public.ai_calls_rollup(TIMESTAMPTZ, UUID, BOOLEAN, TEXT, TEXT);
DROP FUNCTION IF EXISTS public.ai_calls_ingest(JSONB);
DROP TABLE IF EXISTS public.ai_calls;

-- Rollup rows written with origin / host would collide on the old key: fold them first.
DELETE FROM public.ai_usage_stats WHERE origin <> '' OR host_name <> '';
DROP INDEX IF EXISTS public.ai_usage_stats_key_origin;
CREATE UNIQUE INDEX IF NOT EXISTS ai_usage_stats_key ON public.ai_usage_stats (
    bucket, usage_key, COALESCE(team_id, '00000000-0000-0000-0000-000000000000'::uuid), profile, split_arm
);
ALTER TABLE public.ai_usage_stats
    DROP COLUMN IF EXISTS origin, DROP COLUMN IF EXISTS host_name, DROP COLUMN IF EXISTS cost,
    DROP COLUMN IF EXISTS priced_calls, DROP COLUMN IF EXISTS tokens_cache_read,
    DROP COLUMN IF EXISTS tokens_cache_write, DROP COLUMN IF EXISTS tokens_reasoning,
    DROP COLUMN IF EXISTS web_searches, DROP COLUMN IF EXISTS avoided, DROP COLUMN IF EXISTS cache_saved;

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

COMMIT;
