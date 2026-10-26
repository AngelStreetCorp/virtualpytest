# BUG-0783 — The live server reports ENVIRONMENT=development in Settings

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0783                                                     |
| Reported  | 2026-10-22                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | configuration                                                |
| Fixed in  | build 90145 |
| Commit    | —                                                             |

---

## Symptom

Found by the QA sweep of 2026-10-22 (finding OPS-03, in `docs/tasks/QA-OPS-findings.md`); reproduced against the live app.

- **Page / route:** /configuration/settings (tab Server)
- **Viewport / theme:** 1440 px, dark

Steps to reproduce:

1. Open Settings, tab Server.
2. Scroll to "Other settings" and read `ENVIRONMENT`.

**Expected:** `production` on the public platform.

**Actual:** `development`. `GET /server/settings/config` returns the same value. The repo template ships it (`setup/proxmox/vm/backend-server/.env.server.example:60`) and the production deploy does not override it, while the VM runner installer uses `production` (`install_runner.sh:176`). Everyone reading Settings sees the platform labelled "development", and the value may later gate behaviour.

Evidence:

- [ops-03-settings-environment-development.png](../tasks/qa-evidence/ops/ops-03-settings-environment-development.png)

## Root cause

Three things, and none of them was a bug in the app:

1. **The template.** `setup/proxmox/vm/backend-server/.env.server.example` is the template a production install starts from, and line 60 shipped `ENVIRONMENT=development` — the local-development value. The local template (`.env.server.local.example`) also says `development`, which is right there, but the production one said the same. The runner installer already said `production` (`setup/proxmox/vm/runner/install_runner.sh:176`), so the two installers disagreed.

2. **Nothing overrode it later.** `update_core.sh` excludes `.env` from what it syncs (the live `.env` is kept, by design — it holds secrets), so a fresh install kept the template's value forever.

3. **The same file's `DEBUG=1`.** The server reads that key only as the string `true`, so `1` was inert — but it was shown to the operator in Settings as "1", which reads as "on". Same class of defect, same page, same file: a label that does not say what it means.

Where the value comes from: the Settings page renders every key of the server's `.env` that has no dedicated field (`frontend/src/pages/Settings.tsx`, `ExtraEnvFields`), and `GET /server/settings/config` parses that file on every request (`backend_server/src/routes/server_settings_routes.py:246`) — so the page shows the file, not a computed value.

Worth knowing: `ENVIRONMENT` is a **label**. No code reads it (`grep` for `os.environ['ENVIRONMENT']` finds nothing) — the switch the code actually uses is `VPT_ENVIRONMENT` with the values `dev` / `test` / `prod` (`shared/src/lib/executors/script_executor.py:133`). So the wrong value mislabelled the platform for every reader without changing its behaviour — and it would start gating behaviour the day something reads it.

## Fix

**On the live platform — done.** The server was corrected through the app's own admin endpoint (`POST /server/settings/config` with `{"server": {"ENVIRONMENT": "production"}}`), which writes that one key and keeps every other line of the file (`merge_env_text` preserves comments, order and untouched keys, and the endpoint keeps a timestamped backup of the file). No restart was needed: the Settings page reads the `.env` file on every request, and nothing in the code reads the key at start-up.

**In the install template — one line, on its own branch** (`fix-qa-status-env-template`, not merged here).** `setup/proxmox/vm/backend-server/.env.server.example` ships `ENVIRONMENT=development`, so a fresh production install starts mislabelled again. The fix is one line (`ENVIRONMENT=production`, with a comment saying which template is which; the local template `.env.server.local.example` keeps `ENVIRONMENT=development` and the runner installer keeps `ENVIRONMENT=production`), with a test that pins the two templates and the installer.

It ships on its own branch (`fix-qa-status-env-template`) because the integration lane treats **any** `.env` path as a credential path and returns a branch that touches one — the change adds no secret and removes none, but the floor is the manager's to lift, not the session's (`--approved-by manager` is never passed by hand).

**Found in the same pass, in the same file: `DEBUG=1`.** The same template shipped `DEBUG=1` next to `ENVIRONMENT=development`, and the live server read `DEBUG=1`. The server honours that key only as the string `true` (`backend_server/src/app.py:610` and `backend_server/src/lib/server/gunicorn_app.py:106` — `os.getenv('DEBUG', 'false').lower() == 'true'`), so `1` never turned debug mode on: the platform was, and still is, in normal mode. But the Settings page shows the file, so the operator read `DEBUG = 1` — a value that says "on" to anybody who has not read the code. The same defect as `ENVIRONMENT`: a label that lies.

Corrected on the live platform the same way, through the app's own admin endpoint (`{"server": {"DEBUG": "false"}}`), one line, with the endpoint's own backup: the file changed by exactly one line again (`45c45 < DEBUG=1 --- > DEBUG=false`). Nothing restarted, nothing else touched — and no behaviour changed, because the value was inert before and after.

The install template gets the same line on the same branch (`DEBUG=false`, with a comment that says why `1` never meant "on"), and a fourth test pins it.

## Verification

Live platform, before and after (`GET /server/settings/config`):

| | before | after |
|---|---|---|
| `server.ENVIRONMENT` | `development` | **`production`** |
| `server.DEBUG` | `1` | **`false`** |

The file on the server changed by exactly one line each time — the endpoint's own backup, diffed against the live file:

```
44c44
< ENVIRONMENT=development
---
> ENVIRONMENT=production
```

```
45c45
< DEBUG=1
---
> DEBUG=false
```

**In the browser**, on the live platform (build main-2026.10.22-89640): the Settings page's `ENVIRONMENT` field reads **`production`**. The page an operator actually reads, not only the API behind it.

Screenshot: [bug-0783-after-live.png](../../tasks/qa-evidence/fix/bug-0783-after-live.png).

Tests: `tests/backend/test_env_environment_template.py` — 4 cases: the production template says `ENVIRONMENT=production`, the local template says `development`, the runner installer says `production`, and the production template says `DEBUG=false`. Against the pre-fix template the first and the fourth fail. The tests ship with the template change, on `fix-qa-status-env-template`.

Checks: the live platform reports `production` and `false` (verified above) · no frontend or backend code changed.

Re-checked after the deploys that followed (the server restarted again at 19:37 on 2026-10-22 with a build that carries other work): `GET /server/settings/config` still reports **`server.ENVIRONMENT = production`** — the corrected line survives a later deploy, because the deploy keeps the server's own `.env` (it holds the secrets).

A console sweep of the pages this group owns found no regression from those deploys: `/status`, `/monitoring/system`, `/monitoring/analytics`, `/monitoring/incidents` and `/configuration/settings` all render, with no uncaught error and no blank page (`scripts/agent/page_console_sweep.py`).
