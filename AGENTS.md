# Agent Reference

## Project Snapshot
VirtualPyTest: multi-device automation/monitoring platform (TVs, set-top boxes, mobile phones).
Three services: Frontend (React/TS :3000), Backend Server (Flask :5109), Backend Host (Flask :6109), plus shared Python library.

## Codebase Documentation (Read These)

Dedicated agent docs in `docs/agent/` — self-sufficient, no prior knowledge needed:

1. **[docs/agent/README.md](docs/agent/README.md)** — Start here. What the project is, domain vocabulary, how to install/run/test, folder structure.
2. **[docs/agent/navigation/MAP.md](docs/agent/navigation/MAP.md)** — Task-oriented file lookup. "I need to change X" → exact files.
3. **[docs/agent/validation/CONTRACTS.md](docs/agent/validation/CONTRACTS.md)** — Hidden rules that cause bugs if violated. Read before writing code.
4. **[docs/agent/navigation/PATTERNS.md](docs/agent/navigation/PATTERNS.md)** — Canonical files to copy when adding routes, DB modules, hooks, etc.
5. **[docs/agent/validation/TESTING.md](docs/agent/validation/TESTING.md)** — How to test: auto-sign bypass, agent-browser, Playwright E2E, CI/CD reports.
6. **[docs/agent/infra/CICD.md](docs/agent/infra/CICD.md)** — CI/CD pipeline: job graph, runners, report storage, email notifications, improvements.
7. **[docs/agent/infra/DEPLOY.md](docs/agent/infra/DEPLOY.md)** — Exact deploy workflow for debug VMs via proxmox `update_core.sh`, including frontend-only deploys and post-deploy verification.

### Finding a doc fast

`docs/agent/INDEX.md` is a generated routing table of every agent doc (summary + keywords). Read it first when you don't know which doc holds the answer. Docs flagged ⚠ are large — grep or target a section (outlines in `docs/agent/INDEX.json`), never read them whole.

### Docs self-improvement rule (do this in the same session)

If you hit **doc friction** — wrong routing, a stale fact, a missing keyword, a summary that misled you — fix it immediately:
1. Edit the doc's content or its YAML frontmatter (`title`/`summary`/`tags`/`keywords`) — frontmatter is the single source of truth.
2. Regenerate: `python3 scripts/gen_docs_index.py` (never hand-edit `INDEX.md`/folder READMEs).
3. Verify: `python3 scripts/gen_docs_index.py --check` must pass.

Retrieval quality is measured by `docs/agent/DOCS_BENCHMARK.md` — rerun it after structural doc changes and compare against its baseline.

## Key Areas
- `backend_server/` — API orchestration, AI agents, MCP server
- `backend_host/` — Hardware interface, device control, executors
- `shared/` — Common models, database modules, utilities
- `frontend/` — React TypeScript web UI
- `setup/` — Installation and launch scripts
- `scripts/` — Utility scripts

## Browser / E2E Testing (Agent-Friendly)

To test any page — including admin-protected routes — without a Supabase session, append `?auto_signed=<token>` to any URL.
The token is stored in `sessionStorage` so subsequent navigations within the same session remain authenticated.

```
https://virtualpytest.angelstreet.io/?auto_signed=<AUTO_SIGN_TOKEN>
```

- `AUTO_SIGN_TOKEN` lives in `.env` (backend server) — see `.env.example` for reference.
- Works for both the **backend API** (bypasses `API_KEY` check) and the **frontend** (bypasses `ProtectedRoute`).
- `AUTO_SIGN_ROLE=admin` is required for admin-protected pages (set in `.env`).
- For full testing guide see **[docs/agent/validation/TESTING.md](docs/agent/validation/TESTING.md)**.

## Deploying To Debug

- Use **[docs/agent/infra/DEPLOY.md](docs/agent/infra/DEPLOY.md)** for the canonical deploy process.
- Standard frontend-only deploy to debug:
  - `git push origin debug`
  - `ssh proxmox "bash update_core.sh debug --frontend"`
- Standard full deploy to debug:
  - `git push origin debug`
  - `ssh proxmox "bash update_core.sh"`
- Deploying a feature branch: the branch name is the first argument, otherwise proxmox deploys whatever branch it is currently on.
  - `git push -u origin feat/<name>`
  - `ssh proxmox "bash update_core.sh feat/<name> --server"` (drop `--server` for a full deploy)
- After deploy, verify with browser testing using `?auto_signed=<token>` or the existing debug/E2E auto-sign flow before declaring success.

## Guardrails
- Prefer `scripts/` and `setup/` helpers over ad-hoc commands
- No backward compatibility code — no legacy fallbacks
- All database queries must filter by `team_id`
- Never access device controllers directly from routes — use executors
- Server-to-Host calls must use `call_host()` from `shared/src/lib/utils/build_url_utils.py`
- For frontend verification during normal AI work, prefer `cd frontend && npm run build:dev`
- Use `cd frontend && npm run build` only when the docs/security prebuild pipeline is actually required or for release-style verification
- Use `cd frontend && npm run validate` for a quick frontend sanity check

## Script Test + AI Analyzer
- CLI script examples: `docs/user-guide/running-tests.md`
- Script execution API contract: `docs/api/specs/server-script-management.yaml`
- Direct analyzer policy/test strategy: `docs/technical/AI_ANALYZER_DIRECT_TEST_STRATEGY.md`
- Typical end-to-end check:
  - `POST /server/script/execute`
  - `GET /server/script/status/{task_id}`
  - `GET /server/script-results/getAllScriptResults?team_id=<TEAM_ID>`
  - `GET /server/script-results/getVerificationReviewMarkdown/<SCRIPT_RESULT_ID>?team_id=<TEAM_ID>`
