-- 20261022d — Prepared FAQ: index that backs the hot-cache rebuild (TASK-152 phase 9a/9b follow-up).
--
-- The hot cache holds the top-64 live rows by count, then by last_asked_at. Phase 9a shipped
-- `agent_faq_count_live_idx (count DESC, last_asked_at DESC) WHERE live`, which Postgres can use
-- for that ORDER BY; this is the same two-column partial index so `load_hot()` stays an
-- index-only scan as the table grows past the current 342 rows.
--
-- Additive only, and deliberately the only statement in the file: the lane's migration check
-- (decide-policy.js analyzeMigrationSql) admits CREATE TABLE / CREATE INDEX / CREATE VIEW /
-- ALTER TABLE ... ADD COLUMN / INSERT and nothing else — not BEGIN/COMMIT, not COMMENT ON, not
-- REVOKE. So this file carries the index alone.
--
-- The companion 20261022e_agent_faq_count_fn.sql carries the count-bump RPC and the
-- promoted-row CHECK constraint; neither is additive (a function body can change what an existing
-- object does), so they travel the owner-approved path instead.
--
-- Idempotent. Same content as setup/db/schema/082_agent_faq_hot_cache_idx.sql.
-- Rollback: 20261022d_agent_faq_hot_cache_idx_rollback.sql

CREATE INDEX IF NOT EXISTS agent_faq_hot_cache_idx ON public.agent_faq (count DESC, last_asked_at DESC) WHERE live;