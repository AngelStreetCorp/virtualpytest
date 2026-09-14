# Optional features (`features/<name>/`)

An optional feature is code a customer may not get at all. It lives entirely in one
folder and is discovered at startup / build time; a name listed in `DISABLED_FEATURES`
is **not deployed, not registered, not bundled**. With no `features/` folder or an empty
list, every app behaves exactly as before. Context: `docs/tasks/TASK-01-*.md`.

## Layout

```
features/<name>/
  manifest.json                 required: {"name","description","parts":[...]}
  backend_server/__init__.py    optional: exposes register(app) -> registers Flask blueprints
  backend_host/__init__.py      optional: same for the host app
  backend_host/*.py             optional: standalone scripts run by units below
  backend_host/services/*.service  optional: systemd unit templates (%PROJECT_ROOT%), installed as vpt-<unit>.service
  frontend/routes.tsx           optional: default-exports a FeatureDefinition (routes / nav / deviceLinks)
  frontend/**                   pages, components, hooks of the feature
  grafana/*.json                optional: dashboards (push with infra/monitoring/grafana/dashboards/_push_dashboard.py)
  lib/                          optional: python shared by the feature's server + host parts (features.<name>.lib)
  skills/<skill>/SKILL.md       optional: agent skills, loaded next to backend_server/src/agent/skills/definitions/
  backend_server/mcp_tools/*_tools.py  optional: MCP tool classes, discovered like backend_server/src/mcp/tools/
```

`manifest.json` example: `{"name": "avq", "description": "Audio/Video quality monitor",
"parts": ["backend_server", "backend_host", "frontend", "grafana"]}`.

## Discovery (deny-list `DISABLED_FEATURES=a,b`)

| Where | Mechanism |
|---|---|
| deploy | `scripts/disabled_features_excludes.sh` prints `--exclude=/features/<name>/` per listed name; the deploy script feeds it to rsync and passes `DISABLED_FEATURES` to the runtime env and `VITE_DISABLED_FEATURES` to the frontend build |
| backend_server | `shared/src/lib/utils/features.py` → `register_feature_blueprints(app, 'backend_server')` after the core blueprints: imports `features.<name>.backend_server` and calls `register(app)` |
| backend_host | same helper with `'backend_host'`, called from `register_host_routes` |
| host installer | `install_host.sh` adds every `features/*/backend_host/services/*.service` to the service list; `install_service.sh` finds the template there; `redirect_stream_to_data.sh` restarts them too |
| deploy (host units) | `deploy_customer.sh` reconciles the feature units on every host deploy: re-renders + enables + restarts a unit whose rendered content changed or is missing, `disable --now` + removes the units of disabled/removed features (see below). The classic `update_core.sh` (and the offline bundle path) does the same by running `setup/proxmox/node/reconcile_feature_units.sh` on the host; both share `setup/proxmox/node/lib/feature_units.sh` |
| frontend | `vpt-features` plugin in `frontend/vite.config.ts` generates `virtual:vpt-features` with one static import per enabled `features/*/frontend/routes.tsx`; `src/config/features.ts` exposes `featureRoutes()`, `featureNavItems(section)`, `featureDeviceLinks()`, `isFeatureEnabled()` used by `App.tsx`, `config/navItems.tsx`, `pages/Dashboard.tsx` |
| agent skills | `SkillLoader.load_all_skills()` also scans `enabled_feature_dirs('skills')` → every `features/<name>/skills/<skill>/SKILL.md` (same format as core). An agent template may list a feature skill in `available_skills`; when the feature is absent the name is simply not loadable (router skips it, `load_skill` logs "not found") |
| MCP tools | `build_definitions._discover_tool_classes()` also scans `enabled_feature_dirs('backend_server/mcp_tools')` for `*_tools.py` (one `*Tools` class, category = file stem, imported as `features.<name>.backend_server.mcp_tools.<stem>`); `mcp_server` instantiates unknown categories via its fallback (`api_client` first) |
| tests | **Not automatic — a feature must add its own.** Every `routes[].path` in `features/<name>/frontend/routes.tsx` goes into the `PAGES` array of `tests/e2e/playwright/specs/ui.pages.spec.js` *and* the route inventory in `docs/agent/validation/TESTING.md` (in-repo); a feature with `backend_server` routes adds `tests/backend_server/test_<name>.py`. Nothing discovers these — an untested feature ships silently green. See **Testing a feature** below |

`shared/src/lib/utils/features.py::enabled_feature_dirs(subpath)` is the generic hook behind the
last two rows: `[(name, abs_dir)]` for every enabled feature that has that sub-folder. Use it
when a core loader scans a fixed folder and a feature must be able to contribute to it.

A feature is enabled when its folder holds a `manifest.json` and its name is not in the
list. Python skips a feature whose `register()` raises (logged, server keeps starting).
The frontend honours `VITE_DISABLED_FEATURES` at **build** time: a disabled feature is
never imported, so `grep <identifier> dist/` finds nothing.

## `frontend/routes.tsx` contract

```tsx
import React from 'react';
import type { FeatureDefinition } from '../../../frontend/src/config/features';
const Page = React.lazy(() => import('./MyPage'));
const feature: FeatureDefinition = {
  routes: [{ path: '/monitoring/my/:deviceId', element: <Page /> }],   // rendered under the auth guard
  // route flags: fullWidth (no Container, like /ai-agent), hideFloatingAiButton (page has its own AI mode)
  nav: [{ section: 'monitoring', label: 'My page', path: '/monitoring/my' }], // sections: ai|test-build|test-execute|test-report|monitoring|docs|settings
  deviceLinks: [{ label: 'My page', icon: <Icon />, path: (host, device) => `/monitoring/my/${host}/${device}` }],
};
export default feature;
```

Slots offered by core (all append-only, order = feature folder name):

| Slot | Where it lands |
|---|---|
| `nav.section: 'ai' \| 'monitoring' \| 'docs' \| 'settings'` | end of that navbar dropdown |
| `nav.section: 'test-build'` | end of the **Build** group of the Test dropdown (Test Builder, Campaign Builder, …) — used by `quicktest`, `virtual-scripts` |
| `nav.section: 'test-execute'` | end of the **Execute** group of the Test dropdown (Run Tests, Monitor Tests, …) — used by `cicd` |
| `nav.section: 'test-report'` | end of the **Report** group of the Test dropdown (Test Reports, Model Reports, …) — used by `cicd` |
| `routes[].fullWidth: true` | the page renders without the `Container` width limit (like `/ai-agent`) — `App.tsx` checks `matchesFeatureRoute(pathname, 'fullWidth')` |
| `routes[].hideFloatingAiButton: true` | the floating Ask-AI button (`AIOmniOverlay`) is hidden while the location matches that route (`matchesFeatureRoute(pathname, 'hideFloatingAiButton')`) — for builder pages that carry their own AI/device chrome |
| `deviceLinks` | per-device shortcut on the Dashboard |

Nav items go through the same page-visibility layers as core ones (the path is the key).

## Testing a feature

Nothing in the discovery machinery tests a feature. A feature that registers cleanly, builds,
and deploys is still completely untested unless someone writes the tests — which is why the
`Tests` column below reads `none` for most of them.

Tests split by **where they execute**, and the split matters more than the test count:

| Tier | Executes on | Covers | Merge gate |
|---|---|---|---|
| **A — runner-local** | the CI runner itself (`vpt-163-*`, `vpt-164-*`) | pure logic (vitest), page render (`tests/frontend/`), server API CRUD (`tests/backend_server/`), scripts via `--local-debug` | yes |
| **B — device black-box** | **`host-clone-1`**, through the real server → host → device path | anything that must actually run on a device | yes |
| **C — real STB** | `vpt-pi1` devices — `stb3` (IR), `stb4` (BLE), `S21x`, `mi` | the **same tier-B tests**, retargeted | no — nightly / manual dispatch |

Tier C is not a separate suite. The tier-B tests take their target from three env vars, so
the identical test drives Chromium on `host-clone-1` or an IR remote on a real set-top box
(`virtualpytest_web` and `stb_tv` both expose a `home` node, so the graph is unchanged):

```bash
SERVER_URL=https://rpitest.angelstreet.io \
DEVICE_HOST=vpt-pi1 DEVICE_ID=device3 DEVICE_USERINTERFACE=stb_tv \
pytest tests/backend_server/test_quicktest.py -m device
```

Verified on stb3, 2026-09-07: navigated over IR, verified against the tree's reference
image, recorded success with a video, mosaic and HTML report. It is kept out of the merge
gate because IR timing, a sleeping box or a capture stall reddens CI for reasons unrelated
to the change under test — not because real devices cannot be tested.

**The execution status record is transient and host-local** — it can go empty *while a run is
still in progress* (seen on stb3: four polls of "running", then nothing, on a run that
succeeded). The durable verdict is the `script_results` row, matched on
`metadata.execution_id`; poll that, not just the status endpoint.


Rules that are easy to get wrong:

- **Tier B targets `host-clone-1`.** It is the only non-sample-app device host (`host_vnc`, device id
  `host`). The `sample-app-*` hosts (`sample-app-backend`, `sample-app-dongle`, `sample-app-mobile`, `sample-app-tablet`,
  `sample-app-web`) belong to the **sample-app product's** test fleet — pointing VirtualPyTest's own CI at
  them contends with sample-app testing and couples two products' pipelines.
- **CRUD is tier A, not tier B.** Creating, editing and deleting through `/server/*` needs no
  device. Only *executing* does. Keeping the device tier small is what makes a red tier B mean
  something.
- **Tier C stays out of the merge gate.** STB runs fail for reasons unrelated to the change under
  test (box asleep, IR timing, capture stalls). In a merge gate that trains everyone to ignore CI.
- A feature's **pure compile/transform code is the highest-value target** and needs no
  infrastructure at all — e.g. `quicktest`'s `compileStepsToGraph.ts` sits underneath every CRUD
  and execute path, so if it is wrong those all pass green while persisting a wrong graph.

### Delivering a feature — evidence, not assertion

A feature is **delivered** when its test list has actually run and each test has a report link.
"The code is merged" is not delivery; neither is "tests exist". Generate the evidence:

```bash
python3 scripts/feature_delivery_report.py quicktest          # one feature, latest CI run
python3 scripts/feature_delivery_report.py --all              # every feature
python3 scripts/feature_delivery_report.py cicd --run 201     # a specific run
```

It reads the feature's own folder for the tests it is supposed to have, joins them to the CI
jobs that execute them, and prints a markdown table — one row per test with its status and a
link to that job's published report:

| Test | Tier | CI job | Result | Evidence |
|---|---|---|---|---|
| component test for `/test-results/cicd-reports` (`CICDReportsPage`) | A | `frontend-component-tests` | ✅ pass | [report](https://virtualpytest.angelstreet.io/server/cicd/report/185/frontend-component-tests/) |
| `/test-execution/cicd` in ui.pages.spec.js | A | `e2e-pages` | ⛔ **missing** | _NOT in the PAGES array_ |

It exits non-zero while any gap remains, so a release check can gate on it. Run it from a LAN
host, or pass `--server https://virtualpytest.angelstreet.io` from a laptop.

**Paste that table into the feature's release-note entry.** A feature entry in
[../release_note/README.md](../release_note/README.md) is not complete until it carries the
delivery evidence — the same way a schema change must carry its `· 🗄 DB migration` marker.
Report links point at `/server/cicd/report/<run>/<job>/`, which is served from
`/opt/ci-reports/` on the server VM and stays browsable after the run.

Every feature currently reports gaps; the `Tests` column below is the summary of that.

## Features in this repo

| Feature | Parts | Tests | What it is |
|---|---|---|---|
| `avq` | backend_server, backend_host (+service), frontend, grafana, lib | none | Audio/Video quality KPIs + Localize/auto-build tooling; Localize runtime is core |
| `quicktest` | frontend | none | QuickTest Builder page (`/builder/quick-test`): linear step list compiled to the core testcase graph; runs via the core `/server/testcase` routes, no backend part |
| `ai-test` | backend_server, backend_host, frontend, lib, skills, mcp_tools | none | Test Prompt page/routes, `crawl_app` + `crawl-app`/`test-prompt-*` skills; the agent chat is core. No dependency on `virtual-scripts` in either direction |
| `virtual-scripts` | backend_server, frontend, lib | none | Virtual Scripts editor (`/builder/virtual-scripts`) + `/server/virtual-script/*` CRUD/validation/versions; the virtual-script *runtime* (`virtual_scripts_db`, `script_executor` `virtual_script_id`, executable listing, RunTests) is core |
| `cicd` | backend_server, frontend, grafana, lib, db | component (render-only) | CI/CD Reports (Test → Report) and Run CI/CD (Test → Execute) over the `cicd` schema + `/server/cicd/*`; GitHub `workflow_dispatch` with runner choice, `ci_projects` registry, *CI/CD Quality* dashboard. Deny-listed for the customer overlay. See [CICD_FEATURE.md](CICD_FEATURE.md) |

Feature files import core code by relative path (`../../../frontend/src/...`,
`shared.src.lib...`). Bare imports (`react`, `@mui/...`) resolve to `frontend/node_modules`
via the plugin's `resolveId` hook at build time and, for `tsc`, via the committed symlink
`features/node_modules -> ../frontend/node_modules` (`frontend/tsconfig.json` type-checks
`../features/*/frontend/**`). A tsconfig `paths` wildcard was tried first and rejected: a
path-mapped package ignores its `exports` map, which breaks packages such as
`@uiw/react-codemirror`. The symlink is rsync-excluded on deploy (`node_modules`) and
ignored by feature discovery (no `manifest.json`).

A feature folder name may contain a hyphen (`ai-test`): Python still imports it through
`importlib` / relative imports, but `from features.ai-test.lib import x` is a syntax error, so
**inside a feature use relative imports** (`from ..lib.foo import x`) for the feature's own
modules and absolute imports for core.

A feature may depend on another feature only one way and only through its `lib/` (relative
path `from ...<other>.lib.foo import x` is impossible with a hyphenated name — use
`importlib.import_module('features.<other>.lib.foo')` and document the direction in both
manifests). The dependent feature must then be disabled whenever the other is. If both
features need the same helper, put it in core `shared/` instead. Today no feature imports
another (`ai-test` and `virtual-scripts` are independent).

## Rules

- **Core never imports a feature.** Core may only offer generic extension points
  (routes, nav sections, device links, blueprint registration, service discovery).
- **Anything a feature needs in core must be inert by default** (a flag, a slot) and
  ships with the pin like any other core change — it cannot be excluded.
- **Schema is shared** (`setup/db/schema`, `setup/db/migrations`): migrations stay in
  core and additive; unused tables must be harmless.
- **Unit names are global**: `backend_host/services/<unit>.service` becomes
  `vpt-<unit>.service`; do not reuse a core unit name. `manifest.json` may declare them
  explicitly (`"units": ["avq"]`, flat string array); otherwise the file names are used.
- **Host units are reconciled at every deploy**, not only at install: `deploy_customer.sh`
  (over ssh) or `reconcile_feature_units.sh` (on the host, called by `update_core.sh`)
  renders each shipped template (`%PROJECT_ROOT%` → `/opt/virtualpytest`) and, when the
  result differs from the installed `/etc/systemd/system/vpt-<unit>.service`, rewrites,
  enables and restarts it after `vpt-host`; units of a feature that is disabled or gone
  are `disable --now`-ed and removed. A rendered unit starts with the marker comment
  `# vpt-feature: <name>` — that marker (or the feature's unit list) is the only thing
  that makes a unit eligible for removal, so core units are never touched. Never edit a
  rendered unit on the host: the next deploy overwrites it (`DEPLOY_CUSTOMER.md`,
  "Feature systemd units").
- Keep it to folders + `manifest.json`. No plugin framework, no registry file to edit.

## Adding a feature

1. `mkdir features/<name>` + `manifest.json`; put each part in its sub-folder.
2. Server part: `def register(app): app.register_blueprint(my_bp)`.
3. Host service: unit template with `ExecStart=%PROJECT_ROOT%/venv/bin/python %PROJECT_ROOT%/features/<name>/backend_host/x.py`.
4. Frontend: `frontend/routes.tsx` as above; pages lazy-loaded.
5. Verify: `VITE_DISABLED_FEATURES=<name> npx vite build && grep -rl <identifier> dist/assets/` → empty.
