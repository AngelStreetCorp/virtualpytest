-- 037_reference_versions.sql
-- Reference Versions Table
-- Stores version history for verification references (image + text), like
-- testcase_definitions_history but application-managed: the snapshot of an
-- image reference also lives in R2 (history/ prefix), so the copy is done in
-- Python (shared/database/verifications_references_db.py), not a DB trigger.
--
-- Each row is the PREVIOUS {image + area} captured the moment a reference was
-- overwritten (recapture / editor save). Retention: newest 10 per reference;
-- older rows (and their R2 objects) are pruned on every new snapshot.

CREATE TABLE IF NOT EXISTS verifications_reference_versions (
    id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    reference_id    uuid NOT NULL REFERENCES verifications_references(id) ON DELETE CASCADE,
    team_id         uuid NOT NULL REFERENCES teams(id) ON DELETE CASCADE,
    version_number  integer NOT NULL,                 -- sequential per reference (1, 2, 3...)
    reference_type  text NOT NULL CHECK (reference_type = ANY (ARRAY['reference_image'::text, 'reference_text'::text])),
    -- Snapshot of the PREVIOUS state at the moment it was overwritten.
    -- r2_path/r2_url are the history copy (e.g. reference-images/{ui}/history/{name}/{ts}.jpg);
    -- NULL for text references (text lives in `area`).
    r2_path         text,
    r2_url          text,
    area            jsonb,                             -- area (+ focus for image, +text for text) that went with this snapshot
    created_at      timestamp with time zone DEFAULT now(),

    CONSTRAINT unique_reference_version UNIQUE (reference_id, version_number)
);

CREATE INDEX idx_reference_versions_ref ON verifications_reference_versions (reference_id, created_at DESC);
CREATE INDEX idx_reference_versions_team_id ON verifications_reference_versions (team_id);

-- RLS (match verifications_references)
ALTER TABLE verifications_reference_versions ENABLE ROW LEVEL SECURITY;

CREATE POLICY "verifications_reference_versions_access_policy" ON verifications_reference_versions
  FOR ALL
  TO public
  USING (true);

COMMENT ON TABLE verifications_reference_versions IS 'Version history for verification references; newest 10 kept per reference, image bytes snapshotted under the R2 history/ prefix.';
COMMENT ON COLUMN verifications_reference_versions.version_number IS 'Sequential version number for this reference (1, 2, 3...)';
COMMENT ON COLUMN verifications_reference_versions.r2_path IS 'R2 key of the history image copy; NULL for text references.';
