# BUG-0051 — Live credentials and hard-coded auth defaults committed in the tree

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0051                                                     |
| Reported  | 2026-09-07                                                   |
| Status    | Fixed (pending deploy) — key rotation still open, see TASK-08 §4 |
| Severity  | Critical                                                     |
| Area      | security / backend_server / setup / docs                     |
| Fixed in  | build 8713                                                   |
| Commit    | `969a714a5` `997499a06`                                      |

---

## Symptom

A pre-public secrets audit (`gitleaks git` over every ref, 2026-09-07 — tracked in
`docs/tasks/TASK-08-flip-repo-public.md` §4) found real credentials in the `main` tree, not
just in history:

- the **live production `MCP_SECRET_KEY`** hard-coded in a fixture helper
  (`features/avq/backend_host/localize/fixtures/traces/agent_baseline_stb4_2026-07-16/mcp.py`) —
  it matched every local `.env`;
- the **real Supabase JWT secret** of the production database baked in as the *default* of
  `SUPABASE_JWT_SECRET` in `setup/local/linux/database/install_supabase.sh` (three heredoc
  templates) — enough to mint a `service_role` token;
- a **hard-coded default MCP bearer** in `backend_server/src/routes/mcp_routes.py`
  (`os.getenv('MCP_SECRET_KEY', 'vpt_mcp_secret_key_…')`) that any server without the env var
  silently accepted, and which the MCP docs printed verbatim;
- the production Supabase **anon key** in `docs/agent/*` and in the two
  `setup/proxmox/vm/backend-server/.env.server*.example` files (the server writes as anon and
  core RLS is permissive, so this is effectively full DB access);
- two **Google API keys** embedded in code snippets of the stale July Snyk SARIF reports
  (`docs/security/snyk-*-report.json` and the tracked copies under `security_report/`), long
  after the code itself had been cleaned.

Bandit also flagged one HIGH: `backend_server/src/mcp/tools/screenshot_tools.py` fetched
screenshots with `verify=False` even when the URL was an absolute, possibly remote, address.

None of this was exploitable from the internet as long as the repo stayed private, but every
item would have become public the moment the repo flipped (TASK-08).

## Root cause

- Fixtures and installer templates were written by pasting working values instead of reading
  them from the environment; nothing in the pipeline scanned for secrets.
- The MCP route grew a "convenient" default so local runs worked without a `.env`, and the docs
  copied that default as the example.
- SARIF reports embed source snippets, so a scan taken while a key was still in the code kept
  that key alive in `docs/security/` after the code was fixed. `security_report/` was
  gitignored *after* two copies had already been tracked.

## Fix

`969a714a5` — remove live credentials and hard-coded defaults from the tree:

- fixture `mcp.py`: `KEY = os.environ["MCP_SECRET_KEY"]`;
- `install_supabase.sh`: `SUPABASE_JWT_SECRET` default is now the placeholder
  `your_supabase_jwt_secret_here`, like its sibling keys;
- `mcp_routes.py`: `MCP_SECRET_KEY = os.getenv('MCP_SECRET_KEY')` with **no default**; when it
  is unset every `/server/mcp` request is refused with `503 MCP disabled` instead of matching a
  well-known value (fail closed);
- `docs/mcp/mcp_core.md` (+ public mirror), `docs/agent/REFERENCE.md`,
  `docs/agent/navigation/HANDOVER_variant_edge_create.md`, `.env.server*.example`: real keys
  replaced by `<your-mcp-secret-key>` / `<SUPABASE_ANON_KEY>` placeholders;
- `docs/security/snyk-host-report.json` and `snyk-server-report.json` deleted;
  `docs/security/README.md` states Snyk SARIF is no longer committed;
- `screenshot_tools.py`: `verify_tls = not url.startswith('https://localhost')` — TLS
  verification is only skipped for the local self-signed nginx.

`997499a06` — untrack the five files under `security_report/` (same stale SARIF copies).

**Not part of this fix (tracked in TASK-08 §4):** rotating the exposed values — MCP secret on
every server and `.env`, the Supabase JWT secret and the keys derived from it, the two Google
keys, and the provider keys that lived on the now-deleted `debug` branch history.

## Verification

- `git grep` on `origin/main` for each exposed value returns nothing outside `docs/tasks/`
  descriptions (checked 2026-09-07 after push).
- `gitleaks git .` on `main` reports only documented defaults (VNC `admin1234`, Grafana
  `admin:admin`, stock `grafana.ini` `secret_key`).
- After deploy: `curl -H 'Authorization: Bearer anything' https://<server>/server/mcp` on a
  server **without** `MCP_SECRET_KEY` answers `503`, not `403`/`200`; servers with the key
  behave as before.
- Bandit re-run (`scripts/generate-security-docs.sh`): no HIGH findings in `backend_server`.
