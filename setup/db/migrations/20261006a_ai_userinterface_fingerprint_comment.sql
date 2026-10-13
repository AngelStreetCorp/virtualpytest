-- 20261006a_ai_userinterface_fingerprint_comment.sql
-- TASK-67 step 4. Label ai_userinterface_fingerprints in place.
--
-- Two unrelated systems in this codebase are both called "fingerprint" and share
-- no data:
--   * THIS table — TEXT/GLOB identification patterns (software version globs,
--     foreground packages, url hosts). Answers "which UI family is this device
--     running?" -> a ui_id. Matches in Python (fnmatch + literal-char ranking),
--     before the screen is looked at. It never reads pixels.
--   * IMAGE fingerprints — navigation_nodes.data.fingerprint (dhash, regions,
--     crop, focus, title, text). Answers "which node is on screen right now?"
--     -> a node_id. Written by ImageHelpers.compute_fingerprint in
--     backend_host/src/controllers/verification/image_helpers.py.
--
-- Docs-only: no column, constraint, index or data change. The name is
-- deliberately NOT changed -- the fingerprint_type values are self-describing,
-- so the ambiguity never reaches the API surface. See
-- docs/agent/navigation/AI_USERINTERFACE.md and
-- docs/agent/navigation/FINGERPRINT.md.
--
-- Idempotent: safe to re-run. Inverse:
-- 20261006a_ai_userinterface_fingerprint_comment_rollback.sql.

BEGIN;

COMMENT ON TABLE public.ai_userinterface_fingerprints IS
    'TEXT/GLOB identification patterns only — software_version_glob (matched against the About -> SOFTWARE VERSION string), foreground_package (adb shell dumpsys window) and url_host (document.location.host). Answers "which UI family is this device running?" with a ui_id; matched in Python, never against pixels. NOT image fingerprints: the pixel fingerprints (dhash, regions, crop, focus, title, text) live in navigation_nodes.data.fingerprint. See docs/agent/navigation/AI_USERINTERFACE.md and docs/agent/navigation/FINGERPRINT.md.';

COMMIT;