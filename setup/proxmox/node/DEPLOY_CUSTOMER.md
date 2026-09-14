# deploy_customer.sh — layered customer deploy

Companion of the canonical `~/update_core.sh` on proxmox (which deploys one git branch
of one checkout to a fixed host list). This script deploys **public core @ PIN, minus
disabled features, plus (optionally) a customer overlay** to the targets it is given.
Model: `docs/tasks/TASK-01-repo-strategy-open-core-overlay.md`; features:
`docs/technical/FEATURES.md`.

```
deploy_customer.sh [overlay_dir] [--pin <ref>] [--disabled-features a,b]
                   [--targets role:alias[:target_dir[:service]],...] [--dry-run]
                   [--stage-only] [--no-checkout] [--restart [service]] [--keep-stage]
```

Two modes, same staging, same push, same safety rules:

| Mode | Command | `PIN` / `DISABLED_FEATURES` / `TARGETS` come from |
|---|---|---|
| **Customer** (overlay) | `deploy_customer.sh ~/vpt-customer-<codename>` | `<overlay_dir>/customer.conf`, overridden key by key by `<overlay_dir>/customer.local.conf` (git-ignored), overridden by the CLI flags |
| **Platform** (no overlay) | `deploy_customer.sh --pin <ref>` | CLI flags, else `~/deploy.local.conf` on the deploy host (`DEPLOY_LOCAL_CONF=` to relocate) |

| Input | Meaning |
|---|---|
| `PIN` | public ref to deploy. Resolved as `origin/<PIN>` (branch), then tag, then sha; checked out **detached** in `REPO_DIR` (default `~/virtualpytest`, override with `REPO_DIR=`). |
| `DISABLED_FEATURES` | comma list; `scripts/disabled_features_excludes.sh` of the pinned tree turns it into `--exclude=/features/<name>/` for the staging rsync. Default empty = every feature. |
| `TARGETS` | `role:alias[:target_dir[:service]],...`, role ∈ `server` (vpt-server.service), `frontend` (vpt-frontend-prod.service), `host` (vpt-host.service), `windows` (scheduled task); bare alias = host. `target_dir` / `service` are optional per target (section "Target syntax" — one VM, two instances). **Empty = refuse to run** (whatever the mode). No built-in host list. |

The banner prints where each value came from (`(from customer.local.conf)`,
`(from --pin)`, `(from ~/deploy.local.conf)`, `(from (unset))`).

## The overlays

One overlay per environment, never shared between environments:

| Overlay | Repo | Branch | Environment | Ships |
|---|---|---|---|---|
| `vpt-customer-demo` | `AngelStreetCorp/vpt-customer-demo` — **public reference example**; its `README.md` is the onboarding guide | `demo` | `virtualpytest-demo.angelstreet.io` | `frontend/.env.production` ("Demo Customer" branding), `frontend/public/brand/logo.svg`, `customer.conf` (`PIN`, no disabled feature), `customer.local.conf.example` |
| `vpt-customer-<codename>` | private | `prod` | the customer's environments | `frontend/.env.production`, `frontend/vite.config.local.json`, customer scripts, dashboards, identity maps, nginx confs, private runbooks, 5 declared overrides (`OVERRIDES.md`) |

The platform showcase (`virtualpytest.angelstreet.io`, VirtualPyTest branding, every
feature) **needs no overlay**: it is the platform mode below. Its internal targets live in
`~/deploy.local.conf` on the deploy host, not in any repo.

## Platform without overlay

```bash
# on proxmox — pure platform @ preprod to the showcase environment
bash ~/deploy_customer.sh --pin preprod --dry-run     # itemized changes, nothing copied
bash ~/deploy_customer.sh --pin preprod               # explicit go-ahead required
```

`~/deploy.local.conf` on the deploy host (same `KEY=VALUE` syntax as `customer.conf`,
never in git; internal addresses stay on the deploy host):

```
# ~/deploy.local.conf — platform showcase targets (placeholder addresses)
PIN=preprod
DISABLED_FEATURES=
TARGETS=server:10.0.0.3,frontend:10.0.0.5,host:host-1
# a 2nd frontend instance on the same VM (own folder + unit, section "Target syntax"):
# TARGETS=server:10.0.0.3,frontend:10.0.0.5,frontend:10.0.0.5:/opt/virtualpytest-demo:vpt-frontend-demo,host:host-1
```

Precedence in this mode: `--pin` / `--disabled-features` / `--targets` > `~/deploy.local.conf`.
With neither a target flag nor a `TARGETS=` line the script refuses to run. What differs
from the customer mode: no overlay rsync, `frontend config from overlay: (no overlay)`,
and the version identity is the **core value alone** (`current:main-2026.09.02-8549`,
`core_ref:` line, no `overlay_ref:`). Everything else is identical — canonical excludes
on the push (backend `.env` files never touched, `frontend/.env` never pushed), feature
units reconciled on hosts, `frontend/.env.local` generated.

## What it does

1. `git fetch && git checkout --detach <PIN>` in `REPO_DIR` (skipped with `--no-checkout`).
2. Stage a merged tree in a temp dir (`STAGE_DIR=` to choose it, `--keep-stage` to keep it):
   `rsync core → stage` with the canonical exclude list **+** feature excludes, then — with
   an overlay — `rsync overlay → stage` on top (overlay housekeeping skipped: `.git`,
   `.gitignore`, `.githooks`, `scripts/bump_version.sh`, `customer.conf`,
   `customer.local.conf`, `customer.local.conf.example`, `README.md`, `OVERRIDES.md`,
   `VERSION.txt`; same canonical + feature excludes, **except the customer frontend
   configuration**, which is re-included — section below). A file present in both is
   overridden by the overlay copy (see the overlay's `OVERRIDES.md`).
   **Before anything is staged the overlay is refused if it contains any `.env` file**
   (`frontend/.env` → "rename it to `frontend/.env.production`"; any other → "remove it").
   Staging also aborts if any `.env` ends up in the stage (belt and braces: both rsyncs
   exclude `.env`).
3. Write `frontend/.env.local` = `VITE_DISABLED_FEATURES=<list>` into the stage and
   export `DISABLED_FEATURES` / `VITE_DISABLED_FEATURES`. The frontend is built **on the
   frontend VM** by `vpt-frontend-prod.service` (`ExecStartPre=npm run build`);
   `frontend/vite.config.ts` reads that file via `loadEnv`. No host `.env` is touched.
   The disabled folder is absent from the stage anyway, so the vite plugin cannot
   bundle it — the variable is belt and braces. Staging aborts if a disabled
   `features/<name>` is still present.
   Then rewrite the staged `VERSION.txt` as the combined `<platform>/<config>` identity
   (section "Version identity"); the stage step prints `version: main-…/prod-…`, and so
   does the `DEPLOY SUMMARY` (also with `--dry-run` / `--stage-only`).
4. Per target: `rsync -az --delete` stage → the target's directory (`/opt/virtualpytest`
   unless the target names its own, section "Target syntax") with the canonical
   excludes (so backend `.env`, `frontend/.env`, `venv`, `node_modules`, `frontend/dist`
   on the receiver survive `--delete`, while a previously deployed and now-disabled
   `features/<name>/` **is deleted**) preceded by one `--include` per frontend-config
   path the stage carries (section below; the filter list is computed at run time and
   printed at the top of step 4), chown to `vpt_user`, **host role: reconcile the
   feature systemd units (section below)**, restart the target's service, wait for
   active/running, host role: restart the re-rendered feature units, `--restart`
   optionally restarts the aux services that were already active (vpt-stream,
   vpt-monitor, vpt-subtitle, vpt-transcript, vpt-archiver, vpt-kpi + every enabled
   feature unit, e.g. vpt-avq). Server/host = best-effort, frontend = critical (same as
   canonical).
5. `--dry-run`: step 4 becomes `rsync -n -i` per target — the itemized change list is
   printed (with a count and the number of `*deleting` entries), nothing is copied, no
   service is restarted. It still needs ssh + `sudo rsync` on each target.

## customer.local.conf

`<overlay_dir>/customer.local.conf` sits next to `customer.conf`, is **git-ignored** by
the overlay repo, uses the same parser, and **a key present in it overrides the same key
of `customer.conf`** (even with an empty value). Its purpose is `TARGETS`: the internal
addresses of the customer's machines stay on the deploy host and out of a publishable
overlay. `customer.conf` keeps `PIN` + `DISABLED_FEATURES` (and `TARGETS=` empty). The
reference overlay ships a `customer.local.conf.example` to copy. `--targets` overrides
both; the banner says which one supplied the targets:

```
Conf:     customer.conf + customer.local.conf (overrides)
Targets:  server=… frontend=… host=… windows= (from customer.local.conf)
```

Neither file is ever staged or pushed (`OVERLAY_EXCLUDES`).

## Customer frontend configuration

The customer overlay is the source of truth for the **non-secret** frontend
configuration (every `VITE_*` value is baked into the public bundle anyway, see
`docs/get-started/branding.md`). `FRONTEND_CONFIG_PATHS` in the script:

| Path (repo-relative) | What |
|---|---|
| `frontend/.env.production` | `VITE_PROJECT_NAME/TAGLINE/TITLE/LOGO_URL`, `VITE_SHOW_FOOTER`, `VITE_NAV_HIDDEN/DISABLED/COMING_SOON`, customer-facing URLs — **`VITE_*` only, never a token** |
| `frontend/vite.config.local.json` | `allowedHosts`, `cspFrameAncestors`, `corsOrigin` |
| `frontend/public/branding.json`, `frontend/public/brand/**`, `frontend/public/favicon.ico`, `frontend/public/logo.png` | branding assets (optional — a customer using a logo **URL** in `VITE_PROJECT_LOGO_URL` ships none of these; the demo ships `brand/logo.svg`) |
| `frontend/public/data/script_identity_map.json`, `frontend/public/data/campaign_identity_map.json` | **identity maps read by the browser** (script display names + `TCnnn` prefixes on Run Tests, reports, campaign tables — `identityMapCache.ts` fetches only these static files). Customer-owned since BUG-0066; the platform ships an empty `{"scripts": {}}` |
| `test_scripts/script_identity_map.json`, `test_scripts/campaign_identity_map.json` | the same maps for the **server** side (`/server/script/identity-map`, report naming). Keep the two copies identical in the overlay (`cp test_scripts/script_identity_map.json frontend/public/data/`) |

**`frontend/.env` is never in an overlay.** It is the VM's own file — environment URLs
(`VITE_SERVER_URL`, `VITE_GRAFANA_URL`, …) and tokens (`VITE_AUTO_SIGN_TOKEN`), hand-placed
at VM setup, never in git. The overlay ships `frontend/.env.production`, which Vite layers
**over** the VM's `frontend/.env` at build time (precedence below). Incident 2026-09-02:
an overlay that carried `frontend/.env` replaced the demo VM's hand-placed env (rebuilt
from the server-side values); the script now refuses any overlay containing a `.env`.

Any other customer image under `frontend/public/` (e.g. `eos_remote.png`) is not in any
exclude list and has always been deployed like a normal file.

How the rsync filters treat them (rules are first-match; an anchored
`--include='/frontend/.env.production'` placed before the excludes lets exactly that path
through). `--exclude='.env'` has no `/` and no wildcard, so rsync matches the exact
basename only: `.env.production` and the generated `.env.local` are **not** matched by
it, which is why `frontend/.env.production` has its own `--exclude` entry (the one
addition of this script to the canonical list):

- **core → stage**: canonical excludes only → none of them come from the public checkout
  (a dev checkout's own `frontend/.env` / `.env.production` never leaks).
- **overlay → stage**: `--include` for each path the **overlay** has, then the canonical
  excludes → overlay copies land in the stage. Directories get a second `/<path>/**`
  rule. `.env` is never re-included.
- **stage → target (every role, `--delete`)**: `--include` for each path the **stage**
  has, then the canonical excludes. Present in the stage → the target gets the overlay
  copy (for `brand/` the whole directory is mirrored: stale files in the target's
  `brand/` are deleted). Absent from the stage → still excluded, so the target's
  hand-placed copy is neither overwritten nor deleted (platform mode: nothing
  frontend-config related changes on the targets).
- Every `.env` (root, `backend_server/src`, `backend_host/src`, `frontend`, …) is never in
  git, is never included by any of the three rsyncs, and survives `--delete` on the
  targets. The overlay is refused if it carries one; staging aborts if one shows up in
  the stage.

### Vite precedence on the frontend VM

`frontend/.env.local` (`VITE_DISABLED_FEATURES=…`) is generated into the stage on every
run. Vite 6 `loadEnv(mode)` reads, in order, `.env` → `.env.local` → `.env.<mode>` →
`.env.<mode>.local`, and **a later file wins** for a key defined twice
(`Object.fromEntries` over the concatenated entries; variables already in the process
environment win over all files). Hence:

- **client bundle** (`vite build`, mode `production`):
  `frontend/.env` (VM) **<** `frontend/.env.local` (generated) **<** `frontend/.env.production` (overlay).
  `.env.production.local` is not used by any overlay.
- **`vite.config.ts` itself** calls `loadEnv('development', …)` for its own values (server
  URL, HTTPS, `VITE_DISABLED_FEATURES` — read **only** there, by the features plugin), so
  `.env.production` plays no part in feature gating: `.env` < `.env.local` wins.

Do not put a `VITE_DISABLED_FEATURES` line in an overlay `frontend/.env.production`
(feature removal is `DISABLED_FEATURES` in `customer.conf`). Everything the overlay wants
to override in the VM's `.env` (name, logo, nav) simply appears in `.env.production`;
everything it does not mention (URLs, tokens) keeps the VM's value.

The stage step prints one line per run:
`frontend config from overlay: .env.production yes, vite.config.local.json no, branding.json no, brand/ yes, favicon no, logo no`
(or `(no overlay)`).

### Pre-switch checklist (first overlay deploy to a machine)

The deploy replaces the frontend config on the target with the overlay's copy for every
path the overlay carries, so anything hand-placed on the VM that the customer wants to
keep must be in the overlay first:

1. On the frontend VM, copy `frontend/vite.config.local.json` and, if present,
   `frontend/public/branding.json`, `frontend/public/brand/`,
   `frontend/public/favicon.ico`, `frontend/public/logo.png` from `/opt/virtualpytest/`
   into the overlay at the same relative paths and commit them.
2. Move the **branding / navigation** lines of the VM's `frontend/.env`
   (`VITE_PROJECT_*`, `VITE_SHOW_FOOTER`, `VITE_NAV_*`) into the overlay's
   `frontend/.env.production`. Leave the VM's `frontend/.env` where it is — with its URLs
   and tokens — and **never copy it into the overlay** (the script refuses it).
3. Run `--dry-run`: the `>f` lines for those paths must be the only frontend-config
   changes; `frontend/.env` must not appear at all; a `*deleting` line for anything under
   `frontend/public/brand/` means the overlay's `brand/` is incomplete.
4. Paths the overlay does not carry keep the VM's copy (public defaults never replace a
   favicon/logo the overlay does not ship; they are excluded, not synced), so an empty
   overlay is safe — but a *partial* one is not: an overlay `.env.production` without
   the VM's `VITE_NAV_*` lines silently un-hides the nav entries at the next build.

Local proof, no ssh (fake target + `rsync -n -i` with the exact push filter list):

```bash
DC=setup/proxmox/node/deploy_customer.sh
eval "$(sed -n '/^RSYNC_EXCLUDES=(/,/^)/p' $DC)"
eval "$(sed -n '/^# ---- Frontend config from the overlay/,/^# ---- End frontend config from the overlay/p' $DC)"
STAGE_DIR=/tmp/stage; push_filters            # after a --stage-only --no-checkout run
rsync -n -i -a --delete "${PUSH_FILTERS[@]}" /tmp/stage/ /tmp/fake-target/
# demo overlay: >f frontend/.env.production, frontend/public/brand/logo.svg, and NO line for
# frontend/.env, backend_host/src/.env, favicon.ico/logo.png the stage does not carry.
# platform (no overlay): nothing frontend-config related at all.
```

Verified 2026-09-02 with the demo overlay and a fake target holding an old
`frontend/.env`, `frontend/.env.production` and `favicon.ico`; a copy of the demo overlay
with a `frontend/.env` added is rejected at stage time.

## Version identity

The deployed tree identifies itself as **`<platform>/<config>`** — the public core version
at `PIN` plus the customer overlay's own version — e.g.
`main-2026.09.02-8549/prod-2026.09.02-8553`. `write_version_identity` rewrites the
staged `VERSION.txt` (which came from the public tree at `PIN`) as:

```
current:main-2026.09.02-8549/prod-2026.09.02-8553
previous:main-2026.09.01-8548-3d06902
overlay_previous:prod-2026.09.02-8552-000235211     # only when the overlay has one
core_ref:preprod f744d5450                          # PIN + core sha
overlay_ref:prod 77da78f                            # overlay branch + sha (overlay mode only)
```

- **Platform half** = `current:` of the staged (core) `VERSION.txt`. **Config half** =
  `current:` of `<overlay_dir>/VERSION.txt`: the overlay repo (`vpt-customer-<codename>`,
  branch `prod`; `demo` for the demo overlay) carries its own `VERSION.txt` in the same
  `<branch>-<YYYY.MM.DD>-<build>` scheme with its own counter, bumped by the same
  `.githooks/pre-commit` → `scripts/bump_version.sh` (see `docs/agent/release/RELEASING.md`,
  "Customer overlay versions"). The overlay's `VERSION.txt` itself is **never rsynced**
  over the staged one (`OVERLAY_EXCLUDES`). An overlay without `VERSION.txt`, and the
  platform mode (no overlay), keep the core value alone: `current:main-2026.09.02-8549`.
- `current:` stays the **first line**, so every existing reader shows/reports the
  combined string with **no code change**:
  - frontend footer — `frontend/scripts/prebuild.sh` copies `VERSION.txt` →
    `frontend/public/version.txt` at build time on the frontend VM; `vite.config.ts`
    embeds the `current:` value as `__APP_VERSION__`, and `Footer.tsx` falls back to
    fetching `/version.txt` and taking the `current:` line verbatim;
  - host ping / `GET /server/system/getAllHosts` — `deployed_version` =
    first line of `VERSION.txt` (`backend_host/src/lib/utils/host_utils.py`,
    `_read_local_deployed_version`; same for the server in
    `backend_server/src/routes/server_system_routes.py`); the Code Deployment page strips
    the `current:` prefix for display;
  - fleet health report — `scripts/fleet_health_report.py` prints
    `(v<deployed_version>, …)` per host from `getAllHosts`.
- The combined form exists **only in the staged/deployed tree, never in any repo**.
  `scripts/bump_version.sh` runs only from git pre-commit hooks (no git on a deployed
  tree) and would misparse the combined value if it ever met one (its branch group
  accepts `/`, so it would continue the core counter from the overlay's build number) —
  never copy a deployed `VERSION.txt` back into a checkout.

## Feature systemd units

`install_host.sh` renders `features/<name>/backend_host/services/<unit>.service` into
`/etc/systemd/system/vpt-<unit>.service` **only at install time**. A deploy that moves,
adds or removes a feature would leave a stale unit behind (first real demo deploy,
2026-09-02: `vpt-avq` kept running `backend_host/scripts/avq_monitor.py`, a path the
deploy had just deleted). So on every **host** target, after the rsync push and before
`vpt-host` is restarted, the script reconciles them (`reconcile_feature_units`):

1. **Enabled features** — for every `features/*/backend_host/services/*.service` in the
   *staged* tree: render it locally (`render_feature_unit`: marker header +
   `%PROJECT_ROOT%` → `TARGET_DIR`, default `/opt/virtualpytest`), `sudo cat` the
   installed file and `cmp`. Unchanged → nothing (`--restart` still restarts it like any
   aux service). Changed or missing → `sudo tee` + `systemctl daemon-reload` +
   `systemctl enable`, and the unit is queued for a restart that runs **after**
   `vpt-host` is back (`restart_feature_units`). `x@.service` templates are installed
   but neither enabled nor restarted (instances are per host).
2. **Disabled / removed features** — every installed `vpt-*.service` whose first lines
   carry the marker `# vpt-feature: <name>` and whose unit is no longer shipped by the
   stage, plus the units of `DISABLED_FEATURES` read from the *pinned* tree (units that
   `install_host.sh` rendered before the marker existed): `systemctl disable --now`,
   remove the file, `daemon-reload`.
3. Unit names come from the feature's `manifest.json` `"units": ["a", "b"]` when
   declared (flat string array; a listed unit without a template is a warning), else from
   the template file names. Names in `CORE_UNIT_NAMES` (host, server, frontend-*, stream,
   monitor, subtitle, transcript, archiver, kpi, vnc, websockify, ble-remote, hid-*) or
   with a core template in `backend_host/config/services/linux/` are **never** touched,
   even if a marker claims them.
4. Failures (install, disable, restart) are collected in `FEATURE UNIT PROBLEMS` at the
   end of the summary and do **not** fail the host deploy; only the push and the
   `vpt-host` restart can.
5. `--dry-run` prints per host `would render … / would disable --now …` with a unified
   diff of the changed unit, and changes nothing.

Rendered units start with two comment lines: `# vpt-feature: <name>` and a tool-neutral
"rendered by the VirtualPyTest deploy … do not edit on the host" note. The pure logic
(marker, core-unit rule, `list_feature_units`, `render_feature_unit`, marker parsing) lives
in **`lib/feature_units.sh`**, sourced by this script *and* by
**`reconcile_feature_units.sh`** — the standalone, on-host version of the same reconcile
(`sudo bash /opt/virtualpytest/setup/proxmox/node/reconcile_feature_units.sh
[--project-root /opt/virtualpytest] [--dry-run] [--remove-units a,b] [--no-restart]
[--systemd-dir <dir>]`), which the classic `update_core.sh` runs on every host after its
push (section "Deploying without GitHub access"). Both render byte-identical units, so a
host deployed alternately by the two never sees a spurious "changed" restart. Because the
lib is looked up next to the script first, then in `REPO_DIR/setup/proxmox/node/lib/`,
copy `lib/` along when copying `deploy_customer.sh` to `~` on the deploy host (or run it
from the checkout). Local check of the renderer, no ssh:

```bash
TARGET_DIR=/opt/virtualpytest FEATURE_UNITS_TREE=$PWD; source setup/proxmox/node/lib/feature_units.sh
render_feature_unit avq avq features/avq/backend_host/services/avq.service /tmp/vpt-avq.service
grep -n '^ExecStart\|^# vpt-feature' /tmp/vpt-avq.service     # no %PROJECT_ROOT% left
# the standalone script against a fake systemd dir (nothing touched, no root needed):
bash setup/proxmox/node/reconcile_feature_units.sh --dry-run --project-root $PWD --systemd-dir /tmp/fake-systemd
```

## Target syntax

Every target is `role:alias[:target_dir[:service]]` — the same in `customer.conf` /
`customer.local.conf` `TARGETS=`, `--targets` and `~/deploy.local.conf`:

| Field | Meaning | Default when missing |
|---|---|---|
| `role` | `server` / `frontend` / `host` / `windows`; a bare alias = `host` | — |
| `alias` | ssh alias, hostname, IPv4 or `user@host` (as before) | — |
| `target_dir` | absolute directory the stage is pushed to (`rsync --delete`), chown'ed to `vpt_user`, and that the host role's feature units are rendered against (`%PROJECT_ROOT%`) | `TARGET_DIR` (env), i.e. `/opt/virtualpytest` |
| `service` | unit restarted + waited for after the push; `.service` is appended when missing | the role's unit: `vpt-server`, `vpt-frontend-prod`, `vpt-host` |

`frontend:10.0.0.5` and `frontend:10.0.0.5:/opt/virtualpytest-demo:vpt-frontend-demo` in
the same list = two frontend instances on one VM, each with its own folder and unit.
An empty middle field keeps the default (`host:h::vpt-host-2`). `windows:` takes the
alias only (fixed `C:\virtualpytest\virtualpytest` + task). Relative directories, a 5th
field and unknown roles are refused before anything runs. The banner and the
`DEPLOY SUMMARY` show a target as `alias (dir, service)` whenever either differs from
the defaults, and step 4 prints the resolved tuple per target
(`==> [alias] frontend target: dir=... service=...`), with `--dry-run` too.

A target directory that does not exist yet needs **no preparation**: the receiver runs
as root (`--rsync-path="sudo rsync"`), so rsync creates it, and the post-push chown hands
it to `vpt_user`. The push then prints a one-line hint of what the new instance still
needs once (`frontend/.env`, `npm install`, the unit — recipe below); `--dry-run` prints
the same hint, since `rsync -n -i` itemizes the missing directory as `cd+++++++++ ./`.

### Two frontends on one VM

Example: the demo VM `10.0.0.5` keeps the platform frontend in `/opt/virtualpytest`
(`vpt-frontend-prod`, port 5073) and gets a second, overlay-branded instance in
`/opt/virtualpytest-demo` (`vpt-frontend-demo`, port 5074). The port is hardcoded in
`frontend/package.json` `start` (`serve -s dist -l 5073`), so the second unit runs
`serve` directly with its own port.

1. Push (from the deploy host): the folder is created by the push itself.
   ```bash
   bash ~/deploy_customer.sh ~/vpt-customer-demo \
     --targets frontend:10.0.0.5:/opt/virtualpytest-demo:vpt-frontend-demo --dry-run
   bash ~/deploy_customer.sh ~/vpt-customer-demo \
     --targets frontend:10.0.0.5:/opt/virtualpytest-demo:vpt-frontend-demo
   ```
   (the first restart fails until steps 2-3 are done — expected, the files are there.)
2. Once, on the VM, as `vpt_user`: the instance's own env + dependencies.
   ```bash
   sudo cp /opt/virtualpytest/frontend/.env /opt/virtualpytest-demo/frontend/.env   # then edit URLs
   sudo chown vpt_user:vpt_user /opt/virtualpytest-demo/frontend/.env
   sudo -u vpt_user bash -c 'cd /opt/virtualpytest-demo/frontend && npm install'
   ```
   `frontend/.env` is never deployed (`--exclude='.env'` on every push); the overlay's
   `frontend/.env.production` and the generated `frontend/.env.local` arrive with the push.
3. Once, on the VM: the unit = a copy of `vpt-frontend-prod.service` with the other
   folder, port and identifier.
   ```bash
   sudo sed -e 's|/opt/virtualpytest|/opt/virtualpytest-demo|g' \
            -e 's|^ExecStart=.*|ExecStart=/opt/virtualpytest-demo/frontend/node_modules/.bin/serve -s dist -l 5074 --no-clipboard -c /opt/virtualpytest-demo/frontend/serve.json|' \
            -e 's|^SyslogIdentifier=.*|SyslogIdentifier=vpt-frontend-demo|' \
            /etc/systemd/system/vpt-frontend-prod.service \
            | sudo tee /etc/systemd/system/vpt-frontend-demo.service >/dev/null
   sudo systemctl daemon-reload && sudo systemctl enable --now vpt-frontend-demo
   ```
   `ExecStartPre=npm run build` stays: each instance builds its own `dist` from its own
   `.env*` (the port-5073 kill in `vite.config.ts` only runs in dev mode, not on build).
4. Once, on the reverse proxy: a second upstream/server block pointing at the new port.
   ```nginx
   upstream vpt_frontend_demo { server 10.0.0.5:5074; }
   server {
     listen 443 ssl; server_name demo.example.com;   # the hostname in the overlay's VITE_* URLs
     location / { proxy_pass http://vpt_frontend_demo; proxy_set_header Host $host; }
   }
   ```
5. Every later deploy: add the tuple to `TARGETS` (customer.local.conf / ~/deploy.local.conf)
   next to the default one, e.g.
   `TARGETS=frontend:10.0.0.5,frontend:10.0.0.5:/opt/virtualpytest-demo:vpt-frontend-demo`.
   Each instance is pushed, chown'ed and restarted on its own; the summary lists both.

## Typical runs (on proxmox)

```bash
# platform showcase (no overlay): targets from ~/deploy.local.conf
bash ~/deploy_customer.sh --pin preprod --dry-run
bash ~/deploy_customer.sh --pin preprod                      # explicit go-ahead required

# demo environment: the public reference overlay, targets from its customer.local.conf
bash ~/deploy_customer.sh ~/vpt-customer-demo --dry-run
bash ~/deploy_customer.sh ~/vpt-customer-demo

# customer: private overlay, targets from its customer.local.conf (or --targets)
bash ~/deploy_customer.sh ~/vpt-customer-<codename> --dry-run
bash ~/deploy_customer.sh ~/vpt-customer-<codename> --targets server:10.0.0.3,frontend:10.0.0.5,host:host-1

# 2nd frontend instance on the demo VM (own folder + unit, section "Two frontends on one VM")
bash ~/deploy_customer.sh ~/vpt-customer-demo --targets frontend:10.0.0.5:/opt/virtualpytest-demo:vpt-frontend-demo --dry-run

# local proof, no ssh: build the stage from an existing checkout and inspect it
REPO_DIR=~/virtualpytest STAGE_DIR=/tmp/stage bash setup/proxmox/node/deploy_customer.sh \
  ~/vpt-customer-demo --stage-only --no-checkout
REPO_DIR=~/virtualpytest STAGE_DIR=/tmp/stage-plat bash setup/proxmox/node/deploy_customer.sh \
  --pin preprod --stage-only --no-checkout                    # platform, no overlay
```

## Notes / known quirks (inherited from the canonical excludes)

- Identity maps — ownership decided 2026-09-09 (BUG-0066): they are **customer config**,
  handled exactly like the frontend config above (`FRONTEND_CONFIG_PATHS`): excluded from a
  plain-checkout push (targets keep their copies), staged from the overlay and re-included on
  a bundle/overlay push. The legacy `test_campaign/campaign_identity_map.json` exclude stays
  for old trees; the backend actually reads `test_scripts/campaign_identity_map.json`.
- The exclude list is duplicated here from `~/update_core.sh` on purpose (that script
  is not in the repo); change both together. `frontend/.env.production` is the one entry
  this script adds on top of the canonical list.
- `frontend/.env.local` is generated on every run and pushed; do not edit it on a host.
- `--stage-only` ends with a machine-readable trailer (`stage.dir=`, `stage.version=`,
  `stage.pin=`, `stage.overlay=`, `stage.disabled_features=`, `stage.feature_units=`,
  `stage.disabled_feature_units=`) consumed by `build_customer_bundle.sh`; `STAGE_DIR=` is
  honoured as the stage path and never deleted.
- The classic `update_core.sh` (repo copy, `setup/proxmox/node/update_core.sh`) now also
  excludes `frontend/.env.production` on its push — from a plain git checkout (which has
  none) `--delete` would otherwise remove the target's overlay-deployed copy. It still
  excludes the branding paths, so a classic run after an overlay deploy leaves all of the
  customer frontend config as it is (excluded ≠ deleted). Only when its source tree is an
  extracted **bundle** (`BUNDLE_MANIFEST.txt`, no `.git`) does it re-include the frontend
  config the bundle carries, exactly like the push filters here. Still: do not mix a
  checkout-based classic run with an overlay deploy on the same environment.

## Deploying without GitHub access (bundle)

> Simple step-by-step for operators: `docs/agent/release/CUSTOMER_UPDATE_ZIP.md`. Add `--zip` to `build_customer_bundle.sh` when the customer expects a zip.


Some customers' machines cannot reach GitHub/GitLab. Today they receive a repo archive,
extract it on their storage VM and run their own copy of `update_core.sh` from there. With
the platform/overlay split the archive must be the **merged** tree, so it is built on a
machine that has both repos with:

```bash
# on the deploy host / your laptop (both clones present, no ssh needed)
bash setup/proxmox/node/build_customer_bundle.sh ~/vpt-customer-<codename> --out ~/bundles
bash setup/proxmox/node/build_customer_bundle.sh --pin main-2026.09.02-8549 --out ~/bundles   # pure platform
```

```
build_customer_bundle.sh [overlay_dir] [--pin <ref>] [--disabled-features a,b]
                         [--out <dir>] [--no-checkout] [--keep-stage]
```

It runs `deploy_customer.sh … --stage-only` (same staging, same refusals: an overlay
carrying a `.env` is rejected, disabled feature folders are absent, `VERSION.txt` carries
the `<platform>/<config>` identity, `frontend/.env.local` = `VITE_DISABLED_FEATURES`),
writes **`BUNDLE_MANIFEST.txt`** at the root of the stage (bundle name, combined version,
build date + builder host, `platform_ref` / `platform_sha` / `platform_version`,
`overlay` / `overlay_branch` / `overlay_sha` / `overlay_version`, `disabled_features`,
`enabled_features`, `feature_units`, `disabled_feature_units`) and packs the tree as
**`<out>/vpt-<overlay|platform>-<version>.tar.gz`** (`/` of the version → `_`, e.g.
`vpt-demo-main-2026.09.02-8549_demo-2026.09.02-1.tar.gz`; `<overlay>` = overlay folder
name without `vpt-customer-`). It prints the archive path, size and sha256 and writes a
`.sha256` file next to it. tar.gz keeps file modes and symlinks; if the customer insists
on a zip, `cd <stage> && zip -r -y …` works too but re-check `+x` on the shell scripts
after extraction (`reconcile_feature_units.sh`, `bluetooth/*.sh`).

**In the archive**: one top-level folder `virtualpytest/` = the merged tree (platform @
PIN minus disabled features + overlay files + `BUNDLE_MANIFEST.txt`, the rewritten
`VERSION.txt`, `frontend/.env.local`), including `setup/proxmox/node/update_core.sh`,
`reconcile_feature_units.sh` and `lib/feature_units.sh`. **Not in it**: `.git`,
`node_modules`, `venv`, `__pycache__`, `frontend/dist`, and **no `.env` of any kind** —
the only `.env*` files are the overlay's `frontend/.env.production`, the generated
`frontend/.env.local`, and the git-tracked `*.example` / `setup/docker/.env.docker`
templates (the build aborts on anything else). The customer's machines keep their own
backend `.env` and `frontend/.env`, `venv`, `node_modules` and build output, as with
every deploy.

Customer side (unchanged workflow):

```bash
sha256sum -c vpt-<name>-<version>.tar.gz.sha256          # optional
rm -rf ~/virtualpytest && tar -xzf vpt-<name>-<version>.tar.gz -C ~   # -> ~/virtualpytest/
cat ~/virtualpytest/BUNDLE_MANIFEST.txt
bash ~/update_core.sh                                     # their copy, same host list as before
```

`update_core.sh` detects the bundle (`BUNDLE_MANIFEST.txt` present, no `.git`), skips the
git pull (a `[branch]` argument is ignored with a warning), prints the manifest, re-includes
the frontend config the bundle carries (`frontend/.env.production`, `brand/`, …) ahead of
its excludes, rsyncs to every VM as always and, on each host, runs
`sudo bash /opt/virtualpytest/setup/proxmox/node/reconcile_feature_units.sh` after the
`vpt-host` restart and before the aux restart — the only new step, guarded so a target
whose tree predates the script is left as before. The customer's copy of `update_core.sh`
must be refreshed once from the bundle's `setup/proxmox/node/update_core.sh` (keep their
`SERVER_IP` / `FRONTEND_IP` / `HOST_IPS` lines); `REPO_DIR=<dir>` lets them run it from
any extraction path. Then verify: the footer shows `<platform>/<config>` (e.g.
`main-2026.09.02-8549/prod-2026.09.02-8553`), `getAllHosts` reports the same
`deployed_version`, and on a host `systemctl cat vpt-avq` starts with `# vpt-feature: avq`
and points at `/opt/virtualpytest/features/avq/…`.

Units of a feature that was **disabled** for this bundle are listed in the manifest
(`disabled_feature_units:`, read from the pinned tree while staging); the reconcile script
reads that line and removes them even when they predate the marker (`install_host.sh`
rendered them without it). Anything else can be passed with `--remove-units a,b`.

Local proof (no ssh): build from the demo overlay with `--no-checkout` against a clone,
list the archive, extract, then run the reconcile script in `--dry-run` against a fake
systemd dir holding a stale `vpt-avq.service` (old `ExecStart`), a marker unit
`vpt-gone.service` of a feature not in the tree, and core units — it prints
`would render vpt-avq.service (features/avq, changed)` with the diff, `would disable --now
vpt-gone.service`, `core units (never touched): vpt-host.service vpt-stream.service`.
