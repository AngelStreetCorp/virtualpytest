-- 060 — Report snapshots (TASK-49).
-- TASK-49 — share one test report as a snapshot link (Grafana-style). One row per
-- snapshot created by POST /server/report-snapshots. Holds the URL-safe key hash
-- (the random key itself is never stored; it lives in the share link only), the
-- delete-key hash (Grafana-style revoke link shown once at creation), an optional
-- password hash, and the storage prefix under which the frozen HTML + assets live.
--
-- server_name pins the snapshot to the backend server that built it: only that
-- server's storage holds the objects, so only it can serve them. Several servers
-- share the database; the column keeps a single server from serving another's
-- objects.
--
-- RLS: service_role only. Idempotent; the seed never overwrites edited rows.
-- Same content as migration 20261004b_report_snapshots.sql.

BEGIN;

CREATE TABLE IF NOT EXISTS public.report_snapshots (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    team_id          UUID NOT NULL REFERENCES public.teams(id) ON DELETE CASCADE,
    script_result_id UUID NOT NULL,
    server_name      TEXT NOT NULL,
    created_by       UUID,
    key_hash         TEXT NOT NULL UNIQUE,
    delete_key_hash  TEXT NOT NULL UNIQUE,
    password_hash    TEXT,
    storage_prefix   TEXT NOT NULL,
    include_video    BOOLEAN NOT NULL DEFAULT true,
    size_bytes       BIGINT NOT NULL DEFAULT 0,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at       TIMESTAMPTZ NOT NULL,
    revoked_at       TIMESTAMPTZ,
    purged_at        TIMESTAMPTZ,
    view_count       INTEGER NOT NULL DEFAULT 0,
    last_viewed_at   TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS report_snapshots_team_script_created_idx
    ON public.report_snapshots (team_id, script_result_id, created_at DESC);
CREATE INDEX IF NOT EXISTS report_snapshots_server_active_idx
    ON public.report_snapshots (server_name)
    WHERE purged_at IS NULL;

COMMENT ON TABLE public.report_snapshots IS
    'TASK-49 shareable frozen copies of a single test report. key_hash is the '
    'SHA-256 of the 128-bit random URL key; only the hash is stored, the key '
    'itself lives in the share link. delete_key_hash is for the Grafana-style '
    'revoke link. Every read except get_snapshot_by_*_key_hash filters by '
    'team_id.';
COMMENT ON COLUMN public.report_snapshots.server_name IS
    'SERVER_NAME of the backend server that built this snapshot; only that '
    'server serves it, because only it holds the storage objects.';
COMMENT ON COLUMN public.report_snapshots.storage_prefix IS
    'Bucket prefix holding the frozen HTML and assets (shared-snapshots/<id>/).';
COMMENT ON COLUMN public.report_snapshots.password_hash IS
    'Argon2/bcrypt of an optional password; NULL = no password.';
COMMENT ON COLUMN public.report_snapshots.revoked_at IS
    'Set when the link is revoked (creator/manager/admin path or delete-key '
    'path). Once set, list_snapshots with active_only=True hides the row.';
COMMENT ON COLUMN public.report_snapshots.purged_at IS
    'Set by the expiry sweeper after the storage objects are deleted.';

ALTER TABLE public.report_snapshots ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "service_role_all_report_snapshots" ON public.report_snapshots;
CREATE POLICY "service_role_all_report_snapshots" ON public.report_snapshots
    FOR ALL TO service_role USING (true) WITH CHECK (true);
REVOKE ALL ON public.report_snapshots FROM anon, authenticated;

-- TASK-49 §0 Q5: testers, developers and managers can share a test report
-- (admins hold every permission; viewers never). Idempotent — appends only
-- when the value is not already present.
UPDATE public.role_permissions rp
SET permissions = (
    SELECT COALESCE(jsonb_agg(DISTINCT v.value ORDER BY v.value), '[]'::jsonb)
    FROM jsonb_array_elements(rp.permissions || '["reports.tests:share"]'::jsonb) AS v(value)
)
WHERE rp.role IN ('tester', 'developer', 'manager')
  AND NOT (rp.permissions ? 'reports.tests:share');

COMMIT;
