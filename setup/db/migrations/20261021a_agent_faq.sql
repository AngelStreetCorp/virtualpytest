-- 20261021 — Atlas Prepared FAQ (TASK-152 phase 9).
-- TASK-152 — hidden, curated answer store in front of the agent. Atlas answers
-- docs questions in <10s by reading the matching FAQ entry instead of asking
-- the model to re-discover the same docs. Phase 9a ships the storage; phase
-- 9b adds the embedding tier; phase 9c adds per-locale short/long.
--
-- Two tables.
--   agent_faq — the curated knowledge base: one row per question. Seeded from
--               docs/tasks/TASK-152-faq-seed.md; the agent promotes new
--               answers from model calls that cite a `docs/` path. Hot cache
--               (top-64 by count) is built from this table.
--   atlas_faq_log — append-only. One row per Atlas turn that went through the
--               FAQ path: what was asked, the match source (hot_cache /
--               faq_exact / faq_normalised / faq_alias / none), which entry
--               answered (NULL on miss), latency to first byte, latency to
--               full answer. Keeps `atlas_sessions.question_text` joined to
--               what was answered.
--
-- RLS: service_role only. Idempotent. Same content as
-- setup/db/migrations/20261021a_agent_faq.sql.

BEGIN;

CREATE TABLE IF NOT EXISTS public.agent_faq (
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    question_text        TEXT NOT NULL,
    normalised_question  TEXT NOT NULL,
    aliases              TEXT[] NOT NULL DEFAULT '{}'::TEXT[],
    short                TEXT NOT NULL,
    long                 TEXT NOT NULL,
    sources              TEXT[] NOT NULL DEFAULT '{}'::TEXT[],
    tags                 TEXT[] NOT NULL DEFAULT '{}'::TEXT[],
    doc_manifest_hash    TEXT,
    proposed             BOOLEAN NOT NULL DEFAULT FALSE,
    live                 BOOLEAN NOT NULL DEFAULT TRUE,
    count                BIGINT  NOT NULL DEFAULT 0,
    last_asked_at        TIMESTAMPTZ,
    last_reviewed_at     TIMESTAMPTZ,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT agent_faq_question_present CHECK (length(btrim(question_text)) > 0),
    CONSTRAINT agent_faq_short_present    CHECK (length(btrim(short))        > 0),
    CONSTRAINT agent_faq_long_present     CHECK (length(btrim(long))         > 0)
);

CREATE UNIQUE INDEX IF NOT EXISTS agent_faq_normalised_unique
    ON public.agent_faq (normalised_question);
CREATE INDEX IF NOT EXISTS agent_faq_aliases_gin
    ON public.agent_faq USING GIN (aliases);
CREATE INDEX IF NOT EXISTS agent_faq_tags_gin
    ON public.agent_faq USING GIN (tags);
CREATE INDEX IF NOT EXISTS agent_faq_count_live_idx
    ON public.agent_faq (count DESC, last_asked_at DESC) WHERE live;

COMMENT ON TABLE  public.agent_faq IS
    'Atlas Prepared FAQ (TASK-152 phase 9): curated answers in front of the model. Hot cache (top-64 by count) is built from this table.';
COMMENT ON COLUMN public.agent_faq.normalised_question IS
    'NFKC lowercase, punctuation dropped, whitespace collapsed. The dedupe key for canonical SQL lookup.';
COMMENT ON COLUMN public.agent_faq.short IS
    'One-line answer (≤ 280 chars recommended). Sent to the chat when the FAQ hit answers the question.';
COMMENT ON COLUMN public.agent_faq.long IS
    'Full answer in prose. Currently surfaced by the short version; the long is here for follow-up "more" requests and for the model when it cites the entry.';
COMMENT ON COLUMN public.agent_faq.sources IS
    'doc paths that justify this answer; used by the review pass and the doc_manifest_hash invalidation diff.';
COMMENT ON COLUMN public.agent_faq.count IS
    'How many times this entry answered a question. Drives the hot cache ranking and the review pass priority.';

ALTER TABLE public.agent_faq ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "service_role_all_agent_faq" ON public.agent_faq;
CREATE POLICY "service_role_all_agent_faq" ON public.agent_faq
    FOR ALL TO service_role USING (TRUE) WITH CHECK (TRUE);
REVOKE ALL ON public.agent_faq FROM anon, authenticated;

CREATE TABLE IF NOT EXISTS public.atlas_faq_log (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ts              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    team_id         UUID,
    session_id      TEXT,
    user_id         TEXT,
    question_text   TEXT NOT NULL,
    normalised      TEXT NOT NULL,
    match_source    TEXT NOT NULL,                   -- hot_cache | faq_exact | faq_normalised | faq_alias | proposed_promote | none
    faq_id          UUID REFERENCES public.agent_faq(id) ON DELETE SET NULL,
    latency_ms      INTEGER NOT NULL DEFAULT 0,      -- wall clock from message received to answer yielded
    had_answer      BOOLEAN NOT NULL DEFAULT TRUE,   -- false when no FAQ entry matched and the model took over
    CONSTRAINT atlas_faq_log_source_present CHECK (match_source IN
        ('hot_cache', 'faq_exact', 'faq_normalised', 'faq_alias', 'proposed_promote', 'none'))
);

CREATE INDEX IF NOT EXISTS atlas_faq_log_ts_idx            ON public.atlas_faq_log (ts);
CREATE INDEX IF NOT EXISTS atlas_faq_log_question_idx      ON public.atlas_faq_log (normalised, ts DESC);
CREATE INDEX IF NOT EXISTS atlas_faq_log_faq_id_idx        ON public.atlas_faq_log (faq_id, ts DESC);
CREATE INDEX IF NOT EXISTS atlas_faq_log_team_ts_idx       ON public.atlas_faq_log (team_id, ts DESC);
CREATE INDEX IF NOT EXISTS atlas_faq_log_match_source_idx  ON public.atlas_faq_log (match_source, ts DESC);

COMMENT ON TABLE  public.atlas_faq_log IS
    'One row per Atlas turn that went through the FAQ path (TASK-152 phase 9). Used by the count hot cache, the review pass, and the latency benchmark.';
COMMENT ON COLUMN public.atlas_faq_log.match_source IS
    'How the FAQ answered: hot_cache (top-64 in-process), faq_exact (canonical SQL), faq_normalised (canonical SQL on normalised text), faq_alias (token overlap on aliases), proposed_promote (a learned answer the model wrote), none (no match, model took over).';

ALTER TABLE public.atlas_faq_log ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "service_role_all_atlas_faq_log" ON public.atlas_faq_log;
CREATE POLICY "service_role_all_atlas_faq_log" ON public.atlas_faq_log
    FOR ALL TO service_role USING (TRUE) WITH CHECK (TRUE);
REVOKE ALL ON public.atlas_faq_log FROM anon, authenticated;

COMMIT;
