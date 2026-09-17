# BUG-0123 — Every frontend restart rebuilds from scratch with the site down, because the doc cache can never be written

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                                       |
|-----------|-----------------------------------------------------------------------------|
| ID        | BUG-0123                                                                    |
| Reported  | 2026-09-15 (`vpt-frontend-prod` on the frontend VM, after `update_core.sh`)  |
| Status    | Fixed (deployed 2026-09-15)                                                 |
| Severity  | Medium (4–5 min of hard frontend downtime on every deploy *and* on every plain `systemctl restart`; the doc cache built for exactly this never hit once) |
| Area      | `frontend/config/services/linux/frontend_prod.service`, `frontend/scripts/prebuild.sh`, `frontend/scripts/ensure_dist.sh`, `frontend/scripts/lib/build_hashes.sh`, `setup/proxmox/node/update_core.sh` |
| Fixed in  | build 9151                                                                  |
| Commit    | 039d903e9e, 7c8e861fc5                                                      |

---

## Symptom

`systemctl restart vpt-frontend-prod` took **4 min 20 s**, and the site was down for all of it.
Not once — every time. Nine restarts on 2026-09-15 between 14:25 and 19:15, each 4:00–4:30:

```
19:11:18  systemd stops serve                     ← site DOWN
19:11:19  ExecStartPre=npm run build
          └─ prebuild.sh (docs)          2m34s
             ├─ [2/5] API docs           1m13s    13 specs × ~5.5s
             ├─ [3/5] MCP docs             <1s
             ├─ [4/5] security scan        47s    KILLED at the shared 120s budget
             └─ [5/5] copy-docs            34s    201 markdown files
19:13:53  vite build                     1m44s    13322 modules, 4 vCPU / 3.9 GB
19:15:38  serve is up                             ← 4m20s of downtime
```

Every one of those runs logged `Doc sources changed (or no cache) — running full pipeline` followed
by `Pre-build finished WITH DOC WARNINGS`.

## Root cause

Two independent defects that compounded.

**1. The build ran with the service stopped.** The unit had

```ini
ExecStartPre=/usr/bin/npm run build
```

so `systemctl restart` meant *stop `serve`, regenerate every document, run a full Vite production
build, then start serving*. The entire build was downtime by construction. `TimeoutStartSec=1800`
was there to stop systemd killing it — the unit's own comments acknowledged builds of 10–20 minutes
on a cold tree, with the site down for the duration.

**2. The doc cache could never be populated, so the slow path was the only path.**
`prebuild.sh` had a cache gate meant to skip steps 2–5 when the doc sources were unchanged. It never
hit, and could not have:

- Steps 2–4 shared **one 120 s budget** (`DOC_TIMEOUT`), consumed in order. The API-doc step spent
  73 s of it (`redoc-cli` is deliberately not a devDependency since b37bd2f85, so each of the 13
  specs paid a fresh `npx --yes redoc-cli@0.13.21` resolve), leaving the security scan ~47 s for a
  job that needs ~90 s. `bandit` on `backend_host` alone took 40 s; the `backend_server` scan was
  killed mid-flight at exactly `19:11:19 + 120 s = 19:13:19`.
- A timeout in **any** step set `DOC_OK=0`, and the snapshot at the end of the script was gated on
  `DOC_OK=1`. So the least important step in the pipeline — a security report the script itself
  documents as non-critical — vetoed caching for all four.
- With no snapshot written, `docs.hash` never advanced. It sat at `e30db31a…` from `10:44`, so the
  gate compared every later run against a hash from hours earlier and always missed.

The cache was therefore self-defeating: it could only be written by a run in which nothing failed,
and one step failed in every run.

**3. (Contributing) The hash was far too broad.** A single hash spanned `docs/`, both backend `src/`
trees, both `requirements.txt`, `package-lock.json` and `VERSION.txt`. One line changed in
`backend_host/src` invalidated the 73 s API-doc generation, which reads nothing but
`docs/api/specs/*.yaml`.

## Fix

**Build off the critical path.** New `frontend/scripts/ensure_dist.sh` is the single entry point for
making `dist/` current. It builds into `dist.new` and swaps, so the live bundle is never touched by a
running build, and it stamps the result with `dist/.build-stamp` — the hash of everything Vite read
to produce it.

- `update_core.sh` calls it **after the rsync and before the restart**, while the previous `serve` is
  still answering requests.
- The unit's `ExecStartPre` calls the same script. After a deploy build the stamp matches and it
  returns in about a second; on a tree nobody built it still builds, so a restart can never serve a
  stale bundle. A failed build leaves the previous `dist/` in place and the site up, and the deploy
  reports the host as failed rather than restarting into nothing.

**Per-step caching in `prebuild.sh`.** Each of the four steps now owns its own input hash
(`frontend/scripts/lib/build_hashes.sh`) and its own budget:

| step | inputs it is keyed on | budget |
|---|---|---|
| API docs | `docs/api/specs`, `scripts/generate_api_docs.py` | 300 s |
| MCP docs | `backend_server/src/mcp/tool_definitions`, `scripts/generate_mcp_docs.py` | 60 s |
| Security | `backend_{host,server}/src`, `shared/src`, both `requirements.txt`, `frontend/package-lock.json`, `bandit.yaml`, both generator scripts | 240 s |
| copy-docs | the whole `docs/` tree **including generated output**, hashed after steps 2–4 | 90 s |

A step is skipped when its inputs are unchanged **and** its output is actually present (the probe
matters: a hash match must not be read as "the file is there"). A step that fails or times out
invalidates only itself — the other three keep their cache. The security scan in particular now has
a budget nobody upstream can spend, so it completes instead of being killed at 47 s every time.

Keying the copy step on the docs tree *after* generation is what makes cause 3 stop mattering at the
bundle level too: a backend change re-runs bandit, but if the rendered report comes out identical the
copy is skipped, the published tree is unchanged, and `ensure_dist.sh` skips the Vite build as well.

## What the build still costs

Moving the build off the critical path does not make it free, and it was worth asking why a cold
build is minutes rather than seconds. Measured on the frontend VM (4 vCPU / 3.9 GB) against a
laptop, the VM is ~5.5x slower at the same work, so the numbers below are dominated by the box:

| | before | after |
|---|---|---|
| doc pipeline (cold) | 2m34s, every single restart | 2m34s once, then ~1s while sources are unchanged |
| Vite build | 1m44s (13322 modules) | unchanged — it is genuine work |
| downtime per restart | **4m20s** | **~1s** |

The Vite half was checked for a pathology and does not have one. The obvious suspect was
`@mui/icons-material`: 150 files import from its barrel, which re-exports ~5300 icons. Converting
them all to deep per-icon imports and measuring properly (same tree, only the imports differing)
made it slightly **worse** — 13322 modules / 19.6s became 13715 / 20.8s — because the package ships
`sideEffects: false`, so Rollup already drops the unused re-exports, and deep imports only add one
module per icon on top. That change was reverted.

The remaining cold-build cost is the app itself: 589 source files / 178k lines of TypeScript, plus
hls.js and MUI, on a 4 vCPU / 3.9 GB VM that is ~5.5x slower than a laptop at the same build. It
simply no longer happens with the site down, and it is skipped entirely when nothing changed.

## The unit file is not deployed by the deploy

Worth knowing before anyone repeats this: `/etc/systemd/system/vpt-frontend-prod.service` is a
root-owned copy installed by hand. `update_core.sh` rsyncs the tree to `/opt/virtualpytest` and
never touches `/etc/systemd/system` — core units are deliberately excluded from reconciliation (the
host VMs' `reconcile_feature_units.sh` prints them under "core units (never touched)").

So the `ExecStartPre` change in `frontend/config/services/linux/frontend_prod.service` rode along in
the tree through a full deploy while systemd kept running the September copy, and the deploy reported
success. The deploy now diffs the live unit against the one the tree ships and says so, in the run
output and again in the DEPLOY SUMMARY, rather than letting the drift pass unseen. Adopting a new
core unit stays a deliberate, manual step:

```sh
sudo cp /opt/virtualpytest/frontend/config/services/linux/frontend_prod.service \
        /etc/systemd/system/vpt-frontend-prod.service
sudo systemctl daemon-reload
```

## Verification

Deployed 2026-09-15 19:41 to the frontend VM, with a 1 s poller on
`http://<frontend>:5073/` running throughout.

**Doc cache, first restart after the change** (19:31) — the whole pipeline in **1 second**:

```
[2/5]  ✓ Specs unchanged (3fd368d5ca88) — keeping the HTML already in docs/api/docs
[3/5]  ✓ Tool definitions unchanged (448ff7a6b4f5) — keeping mcp_tools_generated.md
[4/5]  ✓ Scanned sources unchanged (9e4d0a8a58f1) — keeping docs/security
[5/5]  ✓ Published docs already current (663140a79fec) — nothing to copy
  ran:     none
  cached:  api-docs mcp-docs security copy-docs
```

That is the step the old cache never once reached: 2m34s → 1s, and `security` is cached rather than
killed. All four hash files exist under `/opt/vpt-cache/docs/`; the legacy `docs.hash` was removed on
first run.

**Deploy** (`update_core.sh main --frontend`): the build ran for 1m46s with the site answering `200`
the whole time, then `dist is current (159da02bf876) — skipping vite build` in ExecStartPre.

| | before | after |
|---|---|---|
| unreachable during a deploy | 4m20s | **5s** (poller: 19:41:35–19:41:39) |
| unreachable during a plain `systemctl restart` | 4m20s | **5s** (`systemctl restart` returns in 3.0s) |
| service CPU at start | 6min 29s | 4.9s |

Served bundle checked afterwards: `index.html`, all four entry chunks, `/version.txt` and
`/docs/docs-manifest.json` all `200`, and the emitted `vendor-mui` hash matches a local build of the
same commit.
