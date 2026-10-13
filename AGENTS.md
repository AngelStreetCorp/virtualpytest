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
6. **`docs/agent/infra/CICD.md` _(internal-only — not in the public snapshot)_** — CI/CD pipeline: job graph, runners, report storage, email notifications, improvements.
7. **`docs/agent/infra/DEPLOY.md` _(internal-only — not in the public snapshot)_** — Exact deploy workflow for debug VMs via proxmox `update_core.sh`, including frontend-only deploys and post-deploy verification.
8. **`docs/agent/infra/PARALLEL_AGENTS.md` _(internal-only — not in the public snapshot)_** — Splitting one task across several agents: worktrees, which files may never be owned by two slices, the merge order, and what "shipped" means. Read before fanning work out.

### Finding a doc fast

`docs/agent/INDEX.md` is a generated routing table of every agent doc (summary + keywords). Read it first when you don't know which doc holds the answer. Docs flagged ⚠ are large — grep or target a section (outlines in `docs/agent/INDEX.json`), never read them whole.

### Docs self-improvement rule (do this in the same session)

If you hit **doc friction** — wrong routing, a stale fact, a missing keyword, a summary that misled you — fix it immediately:
1. Edit the doc's content or its YAML frontmatter (`title`/`summary`/`tags`/`keywords`) — frontmatter is the single source of truth.
2. Regenerate: `python3 scripts/gen_docs_index.py` (never hand-edit `INDEX.md`/folder READMEs).
3. Verify: `python3 scripts/gen_docs_index.py --check` must pass.

Retrieval quality is measured by `docs/agent/DOCS_BENCHMARK.md` — rerun it after structural doc changes and compare against its baseline.

## One Worktree Per Agent, Then Merge To Main
`~/virtualpytest` is a **shared** checkout: several agents work on this repo at the same time. Two agents
editing it directly is what produces conflicting files, half-staged commits and lost work. The rule is
**one agent = one worktree + one branch, and `main` only ever receives work by merge.**

- Create the worktree from `~/virtualpytest`, branched off `main`:
  `git worktree add ~/virtualpytest-<slug> -b <type>/<slug> main`
  Reuse the same worktree for the whole task — never a new one per commit. `git worktree list` shows who is
  working where; take an idle existing worktree instead of adding another.
- Every edit, test and build happens inside the worktree. The shared checkout stays on `main`, clean, apart
  from the merge itself.
- Merge back from `~/virtualpytest` with `git merge --no-ff <your-branch> -m "merge: <branch-slug> — <one-line summary>"`.
  The `--no-ff` keeps the feature's commits visible in `main`'s history; the merge subject is the
  the operator sees in `git log --oneline`, so write it as a sentence. Never cherry-pick a shared
  branch, never rebase it, never `git reset --hard` away another agent's commit. Resolve conflicts
  yourself and keep the merge a single topic.
- **After the merge lands locally, finish the loop in this exact order from `~/virtualpytest`:**
  1. `git push origin main` — push the merge commit to `main`. The shared checkout is the only
     place that can push `main`; a worktree on the same branch cannot.
  2. `git push origin --delete <branch>` then `git branch -d <branch>` — kill the feature branch
     on the remote and locally. `-d` (not `-D`) refuses if the branch has unmerged work, which is
     the guardrail you want.
  3. `git worktree remove ~/virtualpytest-<slug> --force` then `rm -rf ~/virtualpytest-<slug>` if
     the worktree dir is still there. The directory is gitignored; this stops the next session from
     finding a stale, half-checked-out tree.
  Skipping any of those three leaves debris the next session has to clean up: an unpushed `main`
  diverges from origin on the next fetch, a feature branch doubles up the bug tracker entry in
  `git branch -a`, and a leftover worktree shows up as "in use by someone" in `git worktree list`.
- When `main` moved on, take the update with `git merge main` **inside your worktree**, finish the work
  there, then merge to `main` once. Catching up is not a reason to work in the shared checkout.
- Stage explicit paths only — `git add <file>` per file, never `git add -A`, `git add .` or `git commit -a`:
  a shared index may already hold another agent's staged files. Read `git diff --cached` before committing.
- One file has one owner per branch. Structurally shared files — route/menu/permission registries, shared
  types, `VERSION.txt`, migration numbering, lockfiles, CI config — belong to a single integrator; another
  agent asks the owner, or waits for the merge, instead of editing the same file.
- Exception: a tiny docs or typo fix may be committed straight on `main` when no other agent is mid-task.
  Anything functional goes through a worktree.
- Splitting one task across many agents (per-slice ownership, merge order, the final gate) is in
  **`docs/agent/infra/PARALLEL_AGENTS.md` _(internal-only — not in the public snapshot)_**.

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

- Use **`docs/agent/infra/DEPLOY.md` _(internal-only — not in the public snapshot)_** for the canonical deploy process.
- Standard frontend-only deploy to debug:
  - `git push origin debug`
  - `ssh proxmox "bash update_core.sh debug --frontend"`
- Standard full deploy to debug:
  - `git push origin debug`
  - `ssh proxmox "bash update_core.sh"`
- Deploying a feature branch: the branch name is the first argument, otherwise proxmox deploys whatever branch it is currently on.
  - `git push -u origin feat/<name>`
  - `ssh proxmox "bash update_core.sh feat/<name> --server"` (drop `--server` for a full deploy)
- **Order of work:** work in your worktree, merge to `main`, push `main`, then deploy `main` — the lease is the only gate.
- **Deploy on the lease, not on CI:** once your work is merged to `main` and pushed, deploy as soon as `vpt-lease check` says FREE — never wait for the CI run to finish (each push to `main` cancels the run still in progress, so waiting for green stalls deploys).
- After deploy, verify with browser testing using `?auto_signed=<token>` or the existing debug/E2E auto-sign flow before declaring success.

## Guardrails
- Prefer `scripts/` and `setup/` helpers over ad-hoc commands
- No backward compatibility code — no legacy fallbacks
- All database queries must filter by `team_id`
- Never access device controllers directly from routes — use executors
- Server-to-Host calls must use `call_host()` from `shared/src/lib/utils/build_url_utils.py`
- For frontend verification during normal AI work, use `cd frontend && ./node_modules/.bin/tsc --noEmit`
  (types only, fastest) or `./node_modules/.bin/vite build` (full bundle). There is no `build:dev`
  and no `validate` script — `frontend/package.json` has only `dev`, `prebuild`, `build`, `start`,
  `preview`, `lint`
- Use `cd frontend && npm run build` only when the docs/security prebuild pipeline is actually required or for release-style verification (it runs `prebuild` first)
- Use `cd frontend && npm run lint` for a quick frontend sanity check

## Task Docs Start With Goals
Every `docs/tasks/TASK-NN-*.md` (handovers excepted) opens with a `## Goal` section: one paragraph on the outcome,
then a table `# | Goal | Done when | State`. "Done when" is checkable (a number, a test, a page that shows X), not
"works well". Update the State column as work lands. A task doc without it gets one before any new work on that task.
Token cost is a goal on every task: say which agent does the coding (MiniMax-first with a review gate where it fits).

## End Every Turn With A STATUS Line
The last line of every turn you end (not mid-work narration) is exactly one of:
```
STATUS: done — <useful info>
STATUS: needs-owner: <one-line question> [options, e.g. 1 now / 2 after]
STATUS: blocked: <what blocks you>
STATUS: handoff: <resource> -> <session> by <HH:MM>
STATUS: waiting: deploy <id>
```
`<useful info>` is one short line on the outcome: what now works or exists, the commit, what is left, a deploy request id.
Do **not** list the checks you ran ("tsc+lint+i18n pass") or what you did not do ("not deployed, browser not checked"):
the owner finds that noise. Do **not** write tokens or elapsed
time: you cannot measure them; ghosty measures each turn and shows `STATUS: done · 4m 01s · 1.3M tok · <your info>`.
ghosty reads this line first: `done` is never shown to the owner as a question (so don't end a done turn on "?"), and
`needs-owner` is the only line that asks the owner. A turn without the line is sent back once by a Stop hook — reply
with the same text plus the line, do not redo work.

## When to ask the owner
- Decide yourself and say what you chose when the choice is reversible, cheap, inside your task's scope, and you have a recommendation (which plan to build, go now or wait, page sizes, naming, order of steps). Do not stop to ask "should I go with this?".
- Ask the owner only for: anything irreversible, money or cost beyond the task's plan, customers, credentials/secrets, deleting shared data, database migrations, merging other sessions' work to main, or a fact only the owner has (a link, a device in their hands, a physical action).
- When you do ask, give numbered options with your recommendation first, so it can be answered with one tap.

## UI Style (pages, bars, dialogs, popups)
- One look everywhere: **[docs/agent/platform/UI_STYLE.md](docs/agent/platform/UI_STYLE.md)** (contract #28). Read it before building or restyling UI.
- Colours only from the palette (`useAgentChatPalette()` in `frontend/src/constants/agentChatTheme.ts`) or the MUI theme (`primary` = gold). No hex, no blue in a page.
- Pages: `<Box sx={pageSurfaceSx(P)}>` + `PageTitle` + `StatTiles` + `segmentedSx` switches from `frontend/src/components/common/PageChrome.tsx`. One gold filled action per view; status = coloured icon + word.
- Check every UI change in dark **and** light, dialogs included.

### Remote status dot (Take Control panel header)

The small 10×10 green/red dot in the panel header next to the remote title (`RemotePanel.tsx:632-646`) is the operator's "is this remote actually working?" indicator. Every transport-capable remote should publish one — IR / FireTV eos (Vega) / BLE / Android TV do; the phone (Appium) and Nintendo Switch do not (no transport-level health to surface).

The pattern is the same four files every time. Mirror it instead of inventing a new one — the colour rules and the `bleDotColor` slot in `RemotePanel` are shared:

1. **Backend controller** (`backend_host/src/controllers/remote/<name>.py`)
   - Track per-send outcome: `_last_send_ok: Optional[bool] = None`, `_last_send_error`, `_last_send_ts`, `_health_cache`, `_health_cache_ts`. Helper: `_record_send(ok, error)` mirroring `vega.py:125-128`.
   - Call `_record_send(...)` on every transport send (success and failure, including the exception path).
   - Probe: `get_health()` — non-destructive 5-second-cached check (e.g. `adb devices` + `adb shell echo …` for Android TV, `ir-ctl --features` for IR, D-Bus for BLE). Return shape:
     `{<transport>_device, device_present, tx_probe_ok, last_send_ok, last_send_error, last_send_ts, healthy, detail}`. The `last_send_*` fields must be read live, not from the cache.
   - Wire in `execute_command`: `if command == 'get_pairing_status': return {'success': True, 'status': self.get_health()}`. Do **not** alias `get_status` to it — `get_status` is consumed by other callers that expect a different payload.
2. **Frontend hook** (`frontend/src/hooks/controller/use<Name>.ts`)
   - Export a `*Status` interface matching the backend shape. Add `status: *Status | null` state. `refreshStatus()` calls `executeRemoteCommand('get_pairing_status', {}, { remote_type: '<name>' }, { includeDeviceId: true })`. Fire once on mount, expose `status` in the return. Mirror `useInfraredRemote.ts:91-119`.
3. **Remote component** (`frontend/src/components/controller/remote/<Name>Remote.tsx`)
   - Declare `onStatusChange?: (color: string, tooltip: string) => void` prop. Call `useAgentChatPalette()`. Compute the dot from `status` with the standard rules: `null` → `P.textMuted` (grey), `!device_present || !tx_probe_ok || last_send_ok === false || !healthy` → `P.error` (red), else `P.success` (green). Publish via `useEffect`. Add `onStatusChange` to the memo comparator.
4. **`RemotePanel.tsx`** — in the `switch (finalRemoteType)` case for the remote, pass `onStatusChange={(color, tooltip) => { setBleDotColor(color); setBleDotTooltip(tooltip); }}` exactly like the IR / Vega / Bluetooth branches. (`bleDotColor` is a misnomer — it holds any remote's dot.)

The slot in the header is shared; do not add a per-remote dot.

## Report Languages (EN / FR / DE)
- Run and campaign reports switch English/French/German in the browser. Platform strings: `shared/src/lib/i18n/report/<code>.json` (one file per language).
- **A script can be multi-language**: put `<script>.i18n.json` next to it, or `main._i18n = {...}` in the source (virtual scripts: source only). English text = key, `{name}` placeholders. Rewording a string a script prints means updating its key. Testcase reports get the switcher too (platform `msg.*` templates).
- In report formatters: `t('key')` for labels (key in every language file), `tx(text)` for runtime/script text. Stored report links take `#lang=xx`, never `&lang=`.
- Rules, files, adding a language: **[docs/agent/execution/REPORT_I18N.md](docs/agent/execution/REPORT_I18N.md)** (contract #25 in CONTRACTS.md). Check: `python3 scripts/report_i18n_check.py`.

## App Languages (EN / FR / DE)
- The web app is translated with an in-house `t()` (no library): `const { t, tn } = useI18n()` from `frontend/src/i18n/useI18n.ts`. **The English text is the key**; French/German live in `frontend/src/i18n/locales/{fr,de}.json`. Never translate names, data, logs, code or API values.
- Language choice = localStorage `virtualpytest:language`, shared with the website and the reports; `openR2Url()` adds `#lang=` to stored report links.
- A file listed in `frontend/src/i18n/translated-files.txt` must not gain an English literal. Check: `cd frontend && node scripts/i18n-check.mjs` (runs in CI). Rules and files: **[docs/agent/platform/APP_I18N.md](docs/agent/platform/APP_I18N.md)** (contract #27 in CONTRACTS.md); plan and progress: [docs/tasks/TASK-53-app-i18n.md](docs/tasks/TASK-53-app-i18n.md).

## Script Test + AI Analyzer
- CLI script examples: `docs/user-guide/running-tests.md`
- Script execution API contract: `docs/api/specs/server-script-management.yaml`
- Script triage (discard worker, cost rules, verdicts): `docs/agent/ai/SCRIPT_TRIAGE.md`
- Typical end-to-end check:
  - `POST /server/script/execute`
  - `GET /server/script/status/{task_id}`
  - `GET /server/script-results/getAllScriptResults?team_id=<TEAM_ID>`
  - `GET /server/script-results/getVerificationReviewMarkdown/<SCRIPT_RESULT_ID>?team_id=<TEAM_ID>`
