# CodeQL Dismissal Table — 2026-09-24

Generated after the sweep that landed in commits `9797a72`, `0b05a3e7`,
`15350d2c`, `40e4108a`, `ebd972cb`, plus the in-progress admin-token
gate. Use this when triaging the open CodeQL alerts in the GitHub
Security tab.

**How to use:** for each row, open the alert, click **Dismiss alert**,
pick "Won't fix / triage accepted" or "False positive", and paste the
**Dismissal reason** verbatim. The reason includes the commit hash so
the audit trail points at the patch that closed the taint path.

---

## A. Closed by commit (CodeQL should auto-close on next scan)

If a CodeQL alert reopens after the next scan cycle, dismiss manually
with the reason below.

| Alert category | File:line(s) | Dismissal reason |
|---|---|---|
| `read_journal_logs` — Uncontrolled command line | `shared/src/lib/utils/system_utils.py:338` | Closed by `15350d2c` and `40e4108a`. `validate_systemd_unit_name`, `validate_journalctl_level`, `normalize_journal_since` all run at function entry; the route-layer allowlist remains the primary defense. |
| `_restart_systemd_unit`, `_control_systemd_unit`, `_unit_is_active` | `backend_host/src/routes/host_system_routes.py:548`, `:565`, `:605` | Closed by `40e4108a`. `validate_systemd_unit_name` + `validate_systemctl_action` now run at function entry. |
| `bash -c` form in `BashDesktopController` | `backend_host/src/controllers/desktop/bash.py:77` | Closed by `ebd972cb`. Replaced with `shlex.split(bash_command)` + argv form; the endpoint is also admin-gated by the in-progress commit (see section D). |
| `shell=True` in `AndroidCrawler._get_foreground_package` | `features/ai-test/backend_host/app_crawler.py:651` | Closed by `15350d2c`. Switched to argv form; redundant `| grep` removed. |
| `bash -lc` foot-gun in `rollbackCoreLocal` | `backend_server/src/routes/server_system_routes.py:2431` | Closed by `40e4108a`. Replaced with a probe + `['sudo','systemctl','restart', unit]` argv form. |

---

## B. Admin-gated + allowlist-validated — dismissal reason by file

These alerts trace taint from `request.get_json()` to a subprocess call,
but the value is gated by an admin-only route AND validated against a
closed allowlist before reaching the call. The CodeQL rule can't trace
through the validation logic cleanly, so it surfaces the taint path
anyway.

| File:line(s) | Route | Allowlist function | Dismissal reason |
|---|---|---|---|
| `backend_server/src/routes/server_system_routes.py:1035`, `:1046` | `source_git_remote` (`/server/system/source/git/remote`) | `_parse_allowed_git_remote` (must match `github.com/<org>/virtualpytest*` or `vpt-*`) | Admin-gated route (`@require_role('admin')`); `remote_url` allowlisted by `_parse_allowed_git_remote` (must match the approved org or repo pattern). Taint path closed at the route layer; no further fix needed. |
| `backend_server/src/routes/server_system_routes.py:1110` (and the `_run` closure at `:1108-1115`) | `source_git_prepare` (`/server/system/source/git/prepare`) | `storage_path` via `_resolve_storage_path` (realpath + `STORAGE_SOURCE_ROOTS` allowlist); `git_ref` checked against `available_refs` from `_list_git_branches` | Admin-gated route; `storage_path` realpath-validated under `STORAGE_SOURCE_ROOTS`; `git_ref` checked against `available_refs` from origin (`line 1139`). |
| `backend_server/src/routes/server_system_routes.py:1302` | `source_zip_apply` (`/server/system/source/zip/apply`) | `_safe_extract_zip` (zip-slip guard) + `_validate_expected_structure` + `upload_id` UUID + `_resolve_storage_path` | Admin-gated; zip structure and path are allowlisted before any subprocess call. |
| `backend_server/src/routes/server_system_routes.py:2387` | `rollback_core_local` (`/server/system/rollbackCoreLocal`) | `_resolve_backup_dir` + realpath + prefix-under-backup-root | Admin-gated; `selected_backup` realpath-validated under backup root. |
| `backend_server/src/routes/server_system_routes.py:398` | `_run_frontend_remote` (helper for `updateCoreLocal`/`rollbackCoreLocal`) | ssh command uses env-only values + `shlex.quote(command)` | All inputs are env vars (`FRONTEND_DEPLOY_SSH_*`); `command` shlex-quoted; called from admin-gated `updateCoreLocal`/`rollbackCoreLocal`. |
| `backend_server/src/routes/server_system_routes.py:591,600,661,712,742,749,878,1127,1128` | `_read_git_head_info`, `_read_git_origin_url`, `_list_git_branches`, `_read_git_diff_summary`, `_build_server_service_health` | `storage_path` allowlist + hardcoded service candidates + `before_commit`/`after_commit` derive from earlier validated git calls | Taint sources are `storage_path` (allowlisted), hardcoded service candidate list, and commit hashes from earlier validated `git rev-parse` outputs. |
| `backend_server/src/routes/server_system_routes.py:2206` | `update_core_local` (`/server/system/updateCoreLocal`) | `target_kind` whitelisted `{server, frontend}`; bools coerced; script path is hardcoded constant | Admin-gated; the only subprocess spawns a hardcoded path under `/opt/virtualpytest/scripts/`; `source_path` etc. flow into env vars, not argv. |
| `backend_server/src/routes/server_settings_routes.py:50` | `_run_frontend_bridge` | `ssh_host` from env; `action` is hardcoded `'read'/'write'`; `input_text` flows via stdin (no shell) | Admin-gated; `ssh_host` env-only, `action` hardcoded, input via stdin. |
| `backend_server/src/routes/logs_routes.py:207` | `list_services` (`/server/logs/services`) | Hardcoded `ALLOWED_SERVICES` module constant | Admin-gated; `service` only ever comes from the module-level `ALLOWED_SERVICES` allowlist. |
| `backend_server/src/mcp/tools/screenshot_tools.py:92` | `_ocr_advanced` | `tmp_path` is `tempfile.NamedTemporaryFile` (not user-controllable) | Taint source is a generated tempfile path. |
| `shared/src/lib/executors/script_executor.py:1184` | `ScriptExecutor._run` | `shlex.quote()` on every param; script name + params from validated per-script `params.json` | Admin-script endpoint; CLI args passed through `shlex.quote()` in `param_parts`; `bash -c` receives a single quoted argv so no shell expansion. |
| `shared/src/lib/utils/audio_transcription_utils.py:79,163,332,367` | ffmpeg invocations for audio analysis | `file_path` originates from device-capture flows, not HTTP request data | Internal path; called from device verification flows with no direct HTTP taint. |
| `shared/src/lib/executors/script_executor.py:161` | `_kill_process_tree` POSIX branch | `process.pid` from internal source | Internal PID. |

---

## C. Closed by the in-progress admin-token gate (commit pending)

After `<commit hash for the admin-token gate>` lands, the following
alerts should auto-close on the next CodeQL scan. If they reopen:

| Alert | File:line | Dismissal reason |
|---|---|---|
| `/host/desktop/bash/executeCommand` — `bash -c` shell-injection surface | `backend_host/src/controllers/desktop/bash.py:77` | Closed by `ebd972cb` (argv form, shlex.split) and the pending commit (admin-token gate). Defense-in-depth: (1) `shlex.split` rejects unquoted metacharacters; (2) `@require_admin_token` requires `Authorization: Admin <VPT_HOST_ADMIN_TOKEN>` on top of the global `/host/*` `X-API-Key`. |
| `/host/system/runCommand` — temp-file bash | `backend_host/src/routes/host_system_routes.py:716` (`run_command`) | Closed by `ebd972cb` (256 KB input cap) and the pending commit (admin-token gate). Two-factor auth: API key + admin token. The endpoint's docstring previously claimed "gated upstream by admin auth on backend_server" — that was a routing-layer claim, the gate now applies directly on the host too. |

---

## D. Optional follow-up: dependabot.yml entry

The remaining ~530 admin-only alerts CodeQL produces will fire every
commit. To suppress the noise at the source (after the dismissal pass),
consider adding to `.github/dependabot.yml`:

```yaml
codeql:
  queries:
    - name: "python/uncontrolled-command-line"
      severity: critical
      paths-ignore:
        - "**/route_handlers.py"
        - "backend_server/src/routes/server_system_routes.py"
```

Path-ignoring is repo-wide and lossy — prefer the dismissal pass with
specific reasons so the audit trail stays informative.

---

## Audit trail

For full context on each fix, see:

- The audit `Background tasks / Audit subprocess call sites` from
  2026-09-24 in this session.
- Commits: `9797a72`, `0b05a3e7`, `15350d2c`, `40e4108a`, `ebd972cb`,
  `<admin-token gate hash>`.
- `docs/release_note/README.md` — the `Unreleased` block carries the
  one-line summary per PR.
