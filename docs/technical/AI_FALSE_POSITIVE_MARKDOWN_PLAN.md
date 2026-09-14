# AI False-Positive Markdown Artifact Plan

## Goal
Create one AI-only markdown artifact per script execution (same upload path pattern as `.log`), store its URL in DB, and let AI fetch it for false-positive classification. This artifact must not appear inside human-facing script HTML reports.

## Before
- Script execution generates:
  - HTML report URL (`html_report_r2_url`)
  - Logs URL (`logs_r2_url` / `logs_url` usage varies by reader)
- False-positive guidance exists only as inline prompt/report parsing logic.
- No dedicated `.md` artifact URL persisted as first-class field for every script result.
- Human report can include logs link, but there is no separate AI review file contract.

## After
- Script execution generates and uploads a dedicated `verification_review.md` artifact.
- Storage key pattern mirrors logs process (same uploader/provider, same timestamp/script_result_id strategy).
- DB stores dedicated markdown URL/path for each script result.
- Queue task payload includes markdown URL so Sherlock can fetch markdown directly.
- AI uses markdown as primary triage input, then report/logs as secondary evidence.
- HTML report remains unchanged for humans (no new AI section shown).

## Target Data Contract
For each `script_results` row:
- `html_report_r2_url` (existing)
- `logs_r2_url` (existing)
- `verification_review_r2_url` (new)
- `verification_review_r2_path` (new)

If schema migration is delayed:
- Temporary fallback in `metadata`:
  - `metadata.verification_review_r2_url`
  - `metadata.verification_review_r2_path`

## File Changes (Planned)
1. `shared/src/lib/executors/script_executor.py`
- Keep markdown content generation in executor.
- Stop embedding markdown body directly in DB metadata as primary transport.
- Instead pass markdown string to upload utility and only persist returned URL/path.

2. `shared/src/lib/utils/report_generation_utils.py`
- Add `upload_verification_review_markdown(...)` orchestration using same provider flow as logs upload.
- Return `verification_review_url/path` alongside report/log URLs.
- Do not inject this markdown into HTML report template.

3. `shared/src/lib/utils/cloudflare_utils.py` (or upload utility module actually used by logs)
- Add uploader helper for markdown text content.
- Naming convention:
  - `.../<script_result_id>/verification_review.md`
  - or same folder as logs with `.md` extension.

4. `shared/src/lib/database/script_results_db.py`
- Persist `verification_review_r2_url/path` on update.
- Include markdown URL in queue payload (`add_script_to_queue`).

5. `backend_server/src/agent/core/sherlock_handler.py`
- Fetch markdown from URL first.
- Use markdown content as primary analysis context.
- Fallback to report/log fetch if markdown unavailable.

6. `backend_server/src/mcp/tools/analysis_tools.py`
- Surface markdown URL in execution result output for AI tooling.

7. `backend_server/src/routes/server_script_results_routes.py`
- Keep lightweight endpoint to fetch markdown URL (or resolved markdown content) for one script result.
- No changes required to expose markdown in human report screens.

## Execution Flow (After)
1. Script finishes.
2. Executor builds markdown review content.
3. Upload markdown with same storage process as logs.
4. Save returned markdown URL/path in `script_results`.
5. Queue item includes markdown URL.
6. Sherlock fetches markdown, classifies false positive, writes discard decision + reason.

## Rollout Steps
1. Add uploader helper + report utility plumbing.
2. Add DB columns (or temporary metadata fallback).
3. Wire executor to upload `.md` artifact and persist URL/path.
4. Update queue payload and Sherlock consumption.
5. Backfill/fallback for old rows (no markdown URL).
6. Validate on `test_scripts/web/youtube_video_check.py`.

## Validation Checklist
- A completed script result has non-empty markdown URL/path.
- URL points to `.md` object in same storage provider as logs.
- Sherlock prompt includes fetched markdown content.
- `discard` and `discard_comment` are produced from markdown-driven analysis.
- HTML report does not include AI markdown sections.

## Notes
- `backend_host/scripts/incident_manager.py` is not part of this script-result artifact pipeline.
- Main touchpoints are executor, report/upload utilities, script_results DB, and analyzer ingestion.
