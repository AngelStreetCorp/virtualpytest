# Agent Reference

## Project Snapshot
VirtualPyTest: multi-device automation/monitoring platform (TVs, set-top boxes, mobile phones).
Three services: Frontend (React/TS :3000), Backend Server (Flask :5109), Backend Host (Flask :6109), plus shared Python library.

## Which Rule Wins

The dated owner decisions in this file win over older task docs, handovers and session briefs where they differ. A task
doc from before 2026-10-14 that says "no push / no merge / no deploy", "the owner merges" or "the orchestrator deploys"
is superseded: merge your own tested work, push, and deploy by the normal procedure on a free lease yourself. Never hand
the owner commands to run; run them yourself, or ask only about a hard-floor item (deleting data, credentials or
secrets (the auto-sign test token is not one: see Browser / E2E Testing), money, customers, sudoers or units on hosts,
customer database migrations, force-push or history rewrites). Migrations on our own lab databases (node1, rpitest,
vpt-pi4) are routine: apply them yourself and report it (owner, 2026-10-18). A yes/no question whose answer can only
be "yes" is not a question: do it and say so in `STATUS: done`.

## Codebase Documentation (Read These)

Dedicated agent docs in `docs/agent/` — self-sufficient, no prior knowledge needed:

1. **[docs/agent/README.md](docs/agent/README.md)** — Start here. What the project is, domain vocabulary, how to install/run/test, folder structure.
2. **[docs/agent/navigation/MAP.md](docs/agent/navigation/MAP.md)** — Task-oriented file lookup. "I need to change X" → exact files.
3. **[docs/agent/validation/CONTRACTS.md](docs/agent/validation/CONTRACTS.md)** — Hidden rules that cause bugs if violated. Read before writing code.
4. **[docs/agent/navigation/PATTERNS.md](docs/agent/navigation/PATTERNS.md)** — Canonical files to copy when adding routes, DB modules, hooks, etc.
5. **[docs/agent/validation/TESTING.md](docs/agent/validation/TESTING.md)** — How to test: auto-sign bypass, agent-browser, Playwright E2E, CI/CD reports.
6. **`docs/agent/infra/CICD.md` _(internal-only — not in the public snapshot)_** — CI/CD pipeline: job graph, runners, report storage, email notifications, improvements.
7. **`docs/agent/infra/DEPLOY.md` _(internal-only — not in the public snapshot)_** — Exact deploy workflow (main only) via proxmox `update_core.sh`, including frontend-only deploys and post-deploy verification.
8. **`docs/agent/infra/PARALLEL_AGENTS.md` _(internal-only — not in the public snapshot)_** — Splitting one task across several agents: worktrees, which files may never be owned by two slices, the merge order, and what "shipped" means. Read before fanning work out.
9. **Internet bandwidth at the home site** _(the vpt-pi4 proxy path)_ — the status-page Uplink tile (`frontend/src/pages/Status.tsx`) and its measurement (`backend_server/src/lib/utils/uplink_utils.py`). The runbook itself is still unwritten: the `docs/agent/infra/UPLINK.md` pointer came with the item on 2026-10-19 and the file never landed, so the `vnstat` history, the nginx bytes log and the 1G vs 5G/8G upgrade rule are not written down yet.

### Finding a doc fast

`docs/agent/INDEX.md` is a generated routing table of every agent doc (summary + keywords). Read it first when you don't know which doc holds the answer. Docs flagged ⚠ are large — grep or target a section (outlines in `docs/agent/INDEX.json`), never read them whole.

### Who calls what: `code_refs`

Docs say where to start and which rules apply; `code_refs` says what connects to what. For "who calls / imports /
hits X" or "what breaks if I change X" (a Python function, `Class.method`, a module or a `/server/...` URL), call the
`code_refs` MCP tool, or `python3 features/code-graph/scripts/gen_code_index.py --query X [--depth 2]`, **before** grep.
Its answer is complete (AST; the grep hits that are not calls are listed as text-only mentions): do not re-grep to
confirm it. Frontend URL literals are indexed: for a route, query its URL. Grep stays for TypeScript function names
and plain text. Details: `docs/agent/Graphify.md`.

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
- **`git push` needs `node` on `PATH`, or the pre-push review gate fails spuriously.** `.githooks/pre-push`
  runs `scripts/review/review_gate.sh`, which shells out to `frontend/node_modules/.bin/tsc` and `eslint`;
  both have a `#!/usr/bin/env node` shebang. A non-interactive shell does not source nvm, so the gate reports
  `✗ frontend: eslint errors` / `env: node: No such file or directory` — which is **not** a lint failure.
  Export it on the same line: `export PATH="$HOME/.nvm/versions/node/$(ls $HOME/.nvm/versions/node | tail -1)/bin:$PATH" && git push origin main`.
  Do **not** reach for `REVIEW_GATE_SKIP=1` to get past it; that bypasses the real type/lint gate.
  Anything functional goes through a worktree.
- **A commit made on a feature branch is stamped with the branch name, and `main` refuses it.**
  `.githooks/pre-commit` runs `scripts/bump_version.sh` on every non-merge commit and stages the
  result, so a commit made in `docs/whatever` writes `current:docs/whatever-<date>-<build>` into
  `VERSION.txt` — even when the work is only ever destined for `main`. `.githooks/pre-push` then
  rejects `git push origin HEAD:main`, because whatever becomes the tip of `main` is what
  `update_core.sh` deploys and what every host shows as its build label. So commit work destined for
  `main` with the branch spelled out: `VPT_VERSION_BRANCH=main git commit …`. It is skipped during a
  merge, which is why the merge itself never needs it. If a push is already refused, the hook prints
  the fix — run it: `VPT_VERSION_BRANCH=main git commit --allow-empty -m 'chore(version): stamp main
  build'`. **Do not hand-edit `VERSION.txt` to satisfy the check**: on a merge conflict the correct
  resolution is to take `main`'s side (`git checkout --theirs VERSION.txt`) and then restamp, which
  keeps the build numbers monotonic — writing a value yourself is how a bad label reaches production.
- **A refused push is not a race: read the message before looping.** Only
  `! [rejected] … (non-fast-forward)` means `main` moved and another fetch/merge is the fix. A hook
  refusal is a policy verdict — re-running the identical push returns the identical verdict, so a
  retry loop just burns its attempts. When a hook prints the command that fixes it, run it.
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

- **Get the token with `T=$(scripts/agent/auto_sign_token.sh)`** (reads the main backend server's `.env` over the
  `server` ssh alias and checks it live). The same token works on every backend, the vpt-pi1 server (`rpitest`)
  included: no sudo on a Pi is needed. API: `-H "X-Auto-Sign: $T"` or `?auto_signed=$T`; browser: `?auto_signed=$T`
  on every navigation. Never print it, paste it in chat or a log, or commit it.
- Owner rule (2026-10-15): fetching and using the auto-sign test token is routine agent work, not a credentials
  question for the owner or the manager. Do the live check yourself.
- Works for both the **backend API** (bypasses `API_KEY` check) and the **frontend** (bypasses `ProtectedRoute`).
- `AUTO_SIGN_ROLE=admin` is required for admin-protected pages (set in `.env`).
- For full testing guide see **[docs/agent/validation/TESTING.md](docs/agent/validation/TESTING.md)**.

## Deploying

- Use the deploy skill (central lease service) and `docs/agent/infra/DEPLOY.md` for the full procedure.
- Only `main` is ever deployed. Never push to the `debug` branch and never deploy a feature branch: merge your worktree branch into `main` first.
- Frontend only: `ssh proxmox "bash update_core.sh main --frontend"`; server only: `... main --server`; full: `ssh proxmox "bash update_core.sh main"`.
- **Order of work:** work in your worktree, merge to `main`, push `main`, then deploy `main` — the lease is the only gate.
- **Deploy on the lease, not on CI:** once your work is merged to `main` and pushed, deploy as soon as `vpt-lease check` says FREE — never wait for the CI run to finish (each push to `main` cancels the run still in progress, so waiting for green stalls deploys).
- After deploy, verify with browser testing using `?auto_signed=<token>` or the existing E2E auto-sign flow before declaring success.

## Integration lane (round 13, 2026-10-18)

When the integration lane is configured for this repo, do not merge into `main`, push `main` or run `update_core.sh` yourself.
Commit on your worktree branch, push the branch, then `integrate request <branch> [--deploy frontend|server|host]`
(prints the request id) and end the turn with `STATUS: waiting: integration <id>`. The lane merges, tests, pushes with a
compare-and-swap, waits for CI, deploys through the lease queue and tells you the result; a returned request is fixed on
your branch and requested again. Lane not configured for this repo or down: the old path below stands. `update_core.sh`
started by hand on a busy env now queues (`vpt-lease claim --wait`) instead of exiting 3.

**A returned request that needs a manager decision is the manager's to approve (manager, 2026-10-20).** Never pass
`--approved-by manager` yourself — the flag skips the infra-path floor for a request the lane would have handed to the
manager. Fix the branch, push it, and end the turn with `STATUS: needs-manager: <branch> <sha> <what to check>`; the
manager approves and requests it. Only a request the lane returns for a reason you can fix yourself (a conflict, a
failing test) is fixed and requested again on your own.

**Deploy the smallest scope that carries the change (manager, 2026-10-22).** Always request `--deploy server` or
`--deploy frontend` — never `--deploy full`. A full deploy redeploys and restarts every server and every host on the
platform, which a one-side change does not need and which interrupts the running work the deploy rules below try to
spare. Pick the scope from what the branch touches: frontend files → `--deploy frontend`, backend files → `--deploy
server`; a docs, test or config-only branch needs no scope at all.

**Ask the manager before requesting a branch that changes risky logic (manager, 2026-10-22).** Risky logic means a
change the platform's behaviour depends on and whose failure is silent or expensive: permissions and roles, auth and
sessions, money and billing, schema migrations, configuration the platform reads at start-up, and the deploy scripts
themselves. Show the manager the branch (`STATUS: needs-manager: <branch> <sha> <what to check>`) and let it request the
branch after the gate. A fix, a copy, a style change, a test or a doc needs no gate.

**The lane's secret-path floor is not the manager's to lift (2026-10-22).** `--approved-by manager` skips only the
*infra-path* floor. A branch that touches a path the lane reads as a secret path — in practice any `.env` path,
`*.example` templates included — cannot be requested by a session at all: the floor applies whatever the approval says.
Put such a change on its own branch and route it through the manager with the file and what it adds; the manager can
carry it in another branch (a worker who already had the same change did exactly that) or have the lane taught the
rule.

## Deploys That Spare Running Work (TASK-129, 2026-10-18)
What `update_core.sh` (proxmox) now does by itself; no flag needed. Details: `docs/tasks/TASK-129-preprod-per-server.md`, `docs/agent/infra/DEPLOY.md`.
- **Down or unreachable hosts are skipped, not failed.** `~/.vpt-down-hosts` (on proxmox) lists hosts switched off on purpose; any other host that does not answer ssh in 6 s is skipped too. The deploy ends `done`, the note says `skipped (down|unreachable)`, no catch-up deploy is queued. A host you name with `--hosts` ignores the down list.
- **Services restart only when their code changed.** `vpt-host` (on hosts) and `vpt-server` (node server and Pi servers) are restarted only if the git trees they run from changed since their last healthy restart (marker file in the ssh user's home). A frontend- or docs-only push no longer restarts hosts under a long run. Force with `VPT_FORCE_HOST_RESTART=1`.
- **Pinned hosts** (`~/.vpt-pinned-hosts`, now `host-clone-1`) are left alone by push-driven deploys; update one deliberately with `update_core.sh main --hosts host-clone-1` in an idle gap.
- **A leased Pi's server is skipped** in `--server` deploys (`vpt-pi1`, `vpt-pi4`); the catch-up host deploy restarts it later.
- Measure waits with `python3 scripts/agent/lease_wait_report.py`.
- **Preprod does not exist yet.** It is only a plan (phase 3 in the task doc): nothing is deployed, no port, no database. Do not write "test on preprod" in a task until the task doc says it is live.

## Test In Proportion To The Change (owner, 2026-10-18)
"We test too much on small commits." The pre-push gate already runs tsc, eslint, ui-check, i18n-check and ruff on the
files a push changes, and CI runs the full suites after the push to `main`. On a shared 16 GB Mac or codebox, a session
that runs them again by hand only takes RAM from the other sessions.

- **Small change** (a fix, a copy or style tweak, config, docs, roughly ≤ 3 files / ≤ 150 lines): run **no** tests by
  hand: no `tsc`, no `vitest`, no `pytest`, no `vite build`. Commit, push, and let the gate and CI check it. After a
  deploy, check the one thing you changed (one page load or one API call), not the whole flow.
- **Feature** (new page, route, controller, DB module, or a change across many files): run only the tests for the area
  you touched (`scripts/run-vitest.sh <filter>`, `pytest <path>`), once, when the work is done. Browser-test it after deploy.
- Never run the whole vitest or pytest suite locally; CI does that. Never use bare `timeout N vitest` (see TESTING.md).
- A red gate or red CI on your push is yours to fix: that is the test.

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
- **`tsc` is the heaviest routine check — run it once, not per edit.** A cold full run is ~50 s and ~1 GB; `frontend/tsconfig.json`
  is incremental (`frontend/.tsbuildinfo`, gitignored), so a repeat run is ~6 s. On codebox (6 cores / 16 GB, shared by ~25 agent
  sessions) run it as `vpt-tsc ./node_modules/.bin/tsc --noEmit`: a `flock` wrapper so only one runs at a time. Four parallel
  runs plus swap took the box to load 161 (2026-10-15). On a small change, leave the typecheck to the pre-push gate (see
  "Test In Proportion To The Change"); on a feature, typecheck once when it is done, not after every edit; never start a second one while another of yours is running, and don't run it on a
  docs-only or Python-only change.
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
STATUS: needs-manager: <one-line question> [options, recommendation first]
STATUS: blocked: <what blocks you>
STATUS: handoff: <resource> -> <session> by <HH:MM>
STATUS: waiting: deploy <id>
```
`<useful info>` is one short line on the outcome: what now works or exists, the commit, what is left, a deploy request id.
Do **not** list the checks you ran ("tsc+lint+i18n pass") or what you did not do ("not deployed, browser not checked"):
the owner finds that noise. Do **not** write tokens or elapsed
time: you cannot measure them; ghosty measures each turn and shows `STATUS: done · 4m 01s · 1.3M tok · <your info>`.
ghosty reads this line first: `done` is never shown to the owner as a question (so don't end a done turn on "?"),
`needs-owner` is the only line that asks the owner, and `needs-manager` is the only line that asks the manager.
Use `needs-manager` for every technical or orchestration question (merge, push, deploy, lease, migration,
app-generated secret, test/CI, design choice); reserve `needs-owner` for the five-topic owner list below.
A turn without the line is sent back once by a Stop hook — reply with the same text plus the line, do not redo work.

## When to ask the owner
- Decide yourself and say what you chose when the choice is reversible, cheap, inside your task's scope, and you have a recommendation (which plan to build, go now or wait, page sizes, naming, order of steps). Do not stop to ask "should I go with this?".
- A defect you find in your own feature or change (readability, contrast, a broken edge case) is part of the task: fix it, ship it, then report it. Never end on "fix X now?"; the answer is always yes.
- **Never stop to ask these (owner, 2026-10-14: "yes merge, yes push, yes deploy, yes do the recommended one — corrections can come at the end, because when you wait for me we stop developing"):** start building a plan you already wrote; pick your own recommended option; merge your own work to main once its tests pass; push; deploy main by the normal procedure on a free lease (busy lease: wait and retry, do not ask); rerun a test. Do it, then report it in `STATUS: done`. For UI work, post the mockup and keep building; the owner reviews at the end.
- **Waiting on your own job is not "blocked" (owner, 2026-10-14: a session sat idle 1 h after its run finished).** Start long runs (score runs, test suites, builds, deploys) as a harness-tracked background command (`run_in_background`, or a Monitor on its log), never a detached `nohup`/`&` the harness cannot see, so you are woken when it ends; keep doing other work meanwhile. Do not end a turn with `STATUS: blocked` on your own job; `blocked` is only for something outside your control.
- **Never hold a lease while you wait (owner, 2026-10-14: "you are blocking dev with a lease when you just wait").** Hold a device or host lease only for the minutes you actively control it (keys, channel, deploy, restart). Recording windows, waiting on a run, and copying archived chunks read-only need no lease: release first, re-claim when you act. If you need a device to stay as it is, say so in your STATUS line instead of holding it.
- Owner rule (2026-10-18): the owner is asked only about money/payments, customers, deleting shared data, credentials only the owner holds (third-party logins, keys to rotate), and physical actions on a device.
- Anything else (technical choices, merges, pushes, deploys, leases, DB migrations from a runbook, app-generated secrets, tests/CI, infra config) is decided by the session itself when reversible and in scope, or asked with `STATUS: needs-manager:` otherwise.
- When you do ask, give numbered options with your recommendation first, so it can be answered with one tap.

## Navigation Tree (Userinterface) Naming (owner, 2026-10-26)
One operator = one family of trees, named **`<platform>-<operator>`**, lowercase, hyphen, no `ui`, no underscore.
- `<platform>` is one of `web`, `stb`, `androidtv`, `androidmobile`, `androidtablet`, `firetv`, `appletv`, `ios`.
- `<operator>` is the operator's codename (the codenames are in the internal task doc `docs/tasks/TASK-176-tree-naming.md`; never the real brand).
- Examples: `web-<operator>`, `stb-<operator>`, `androidmobile-<operator>`; a new operator gets the same set (`stb-<operator>`, `web-<operator>`, …).
- Named variants (firmware, profile) stay inside the tree, never a new interface. Experiments and builder runs use a `tmp-` prefix and are folded or deleted, never published.
- The same stem names the knowledge-base row, the skill (`<platform>-<operator>`) and the doc (`docs/agent/devices/` file). Publish to prod (`POST /server/userinterface/publish/<id>`) only a validated tree.
- **Dev vs prod is the validation signal (owner, 2026-10-26).** A tree that is built and validated is published to prod in the same turn (`POST /server/userinterface/publish/<id>`), and republished after every later validated change; a tree that only exists as `dev` is not validated yet. Never publish an unvalidated tree.
- The codename, never the real brand, is used in **every identifier**: `.env` keys (`<CODENAME>_<WHAT>_*`, e.g. `<CODENAME>_HGW_LOGIN`, `<CODENAME>_APP_PASSWORD`), script and file names, skills, profiles, branches. Real brands appear only in external facts (a vendor URL, a Wi-Fi name, a firmware string).
- **Every tree has a `settings` node and an `info` node that reads the software version (owner, 2026-10-26).** A tree without them is not finished: the version under test must be readable from the tree. Web: the settings page and its version row (read it with a page script); STB, Android: Settings, then About / app info. Example: an operator's UI inventory task doc, §2b.
- The existing generic names were renamed under TASK-176 (2026-10-26): `web-<operator>`, `stb-<operator>`, `androidtv-<operator>`, `androidmobile-<operator>`.

## UI Style (pages, bars, dialogs, popups)
- One look everywhere: **[docs/agent/platform/UI_STYLE.md](docs/agent/platform/UI_STYLE.md)** (contract #28). Read it before building or restyling UI.
- Colours only from the **active theme** (`useAgentChatPalette()` in `frontend/src/constants/agentChatTheme.ts`) or the MUI theme (`primary` = the theme accent; gold is only the default — users switch themes live). No hex, no blue in a page.
- Pages: `<Box sx={pageSurfaceSx(P)}>` + `PageTitle` + `StatTiles` + `segmentedSx` switches from `frontend/src/components/common/PageChrome.tsx`. Buttons take a role (`primaryButtonSx` once per view, `toggleSx`/`selectedSx`, `neutralButtonSx`, `dangerButtonSx`); icons from `<AppIcon>` / `<StatusText>`, never emoji; running is never green.
- **Dashboard cards** (contract #40, UI_STYLE §16): content is one block centred vertically; a single-stat / KPI tile (one label, one number) is centred **horizontally too**, never flush left.
- Check every UI change in dark **and** light, dialogs included, and with a non-gold theme. Run the four local style checks before merging (not in CI): `cd frontend && node scripts/theme_colour_check.mjs && node scripts/button_role_check.mjs && node scripts/icon_check.mjs && node scripts/status_check.mjs`.

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

## Release notes (docs/release_note/README.md)
- Every bullet has one **kind**, under its own heading, each once per build: `### Features`, `### Improvements`, `### Bug fixes`, `### Security`, `### Internal`, `### Upgrade`.
- Features and Improvements end with ` · area: <slug>`; the seven slugs are `device-control`, `monitoring`, `testing`, `ai`, `integrations`, `platform`, `entertainment`. A new area needs an owner go.
- **One feature = one entry.** A later round on a feature updates that entry (and keeps its TASK / BUG / migration references); do not add another line. Polish on an existing feature is an Improvement.
- **Internal** (libraries, payload fields, ops agents) is never shown to customers and is left out of the delivery note.
- Rules and examples: `docs/release_note/AUTHORING.md`. Run `python3 scripts/release/check_release_notes.py` before merging (CI and the pre-push gate run it too).

## Script Test + AI Analyzer
- CLI script examples: `docs/user-guide/running-tests.md`
- Script execution API contract: `docs/api/specs/server-script-management.yaml`
- Script triage (discard worker, cost rules, verdicts): `docs/agent/ai/SCRIPT_TRIAGE.md`
- Typical end-to-end check:
  - `POST /server/script/execute`
  - `GET /server/script/status/{task_id}`
  - `GET /server/script-results/getAllScriptResults?team_id=<TEAM_ID>`
  - `GET /server/script-results/getVerificationReviewMarkdown/<SCRIPT_RESULT_ID>?team_id=<TEAM_ID>`
