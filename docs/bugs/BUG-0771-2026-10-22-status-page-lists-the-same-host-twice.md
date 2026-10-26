# BUG-0771 — The Status page lists host-clone-1 and host-clone-2 twice, so its "services healthy" count double-counts them

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0771                                                     |
| Reported  | 2026-10-22                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                         |
| Area      | frontend                                      |
| Fixed in  | build 90145 |
| Commit    | —                                                             |

---

## Symptom

Found by the QA sweep of 2026-10-22 (finding OPS-01, OPS-13, in `docs/tasks/QA-OPS-findings.md`); reproduced against the live app.

- **Page / route:** /status
- **Viewport / theme:** 1440 px, dark and light

Steps to reproduce:

1. Open the Status page as admin.
2. Scroll the "VM summary" table to the "Host:" rows.
3. Read the "Services healthy" tile at the top.

**Expected:** One row per physical host and a tile that counts each service once.

**Actual:** host-clone-1 and host-clone-2 each appear twice with identical numbers. The tile reads "55/57 Services healthy"; 57 includes the duplicated hosts. The Dashboard > System tab shows a tile with the same words and the figure "29 / 29" (VM services only), so two pages show different totals under one label (OPS-13).

Evidence:

- [ops-01-status-duplicate-hosts.png](../tasks/qa-evidence/ops/ops-01-status-duplicate-hosts.png)

## Root cause

`frontend/src/pages/Status.tsx:1068` flat-maps the hosts of every server with no de-duplication by `host_name`; the two hosts are registered on both the primary and the QualiAI server. Related display problem on the Run page: see BUG-0791 (the same duplicate on the Run page).

Which servers report the same machine, measured on the live deployment (2026-10-22, `GET /server/system/getAllHosts` with the auto-sign token):

| Backend | Hosts it reports |
|---|---|
| `virtualpytest.angelstreet.io` (primary) | host-clone-1, labox-backend, labox-mobile, host-clone-2 |
| `virtualpytest.qualiai.io` | host-clone-2, host-clone-3, host-android-mobile, host-android-tv, **host-clone-1** |
| `<pi-server-host>` (first Pi server) | vpt-pi1, vpt-mf1 |
| `<pi-server-host>` (second Pi server) | vpt-pi4, vpt-nipogi, vpt-lenovo1/4/5/6, lenovo-local-low, lenovo-local-hd |

host-clone-1 and host-clone-2 are the **same two machines** on both servers: same `host_name` and same `host_api_url` (the same two private addresses on the lab network). The Status page builds one accordion section and one "Host: …" summary row per *catalog entry*, so each of them was drawn twice, and every service of a duplicated host was added to `allServices` twice — which is what the "Services healthy" tile counts.

The Dashboard > System card (OPS-13) counts something else on purpose: `GET /server/dashboard/system` returns `services` from the collector's own rows (`service_status_current` for this server, 29 of them), i.e. the **platform's** own units, with no host services in it. Same words, different scope.

## Fix

One physical host, one row, one set of services.

- New helper `frontend/src/components/status/hostCatalog.ts` — `dedupeHostsByName(serverHostsData)` flattens every server's catalog and keeps **one** record per `host_name`. The servers arrive in configuration order, so the primary server's record wins; a later catalog may still fill in the `system_stats` the winner did not carry (a catalog polled without `system_stats` has none).
- `frontend/src/pages/Status.tsx` builds its host sections and its summary rows from that de-duplicated list (`useMemo` on `serverHostsData`), so the duplicate is gone from the "VM summary" table, from the accordion sections and from the "Services healthy" count at once.
- The Dashboard > System card now says **"Platform services healthy"** (new i18n key, FR + DE) instead of the same "Services healthy" the Status page uses, so the two tiles no longer look like the same number under two pages. Its number is unchanged: the platform's own 29 units. The full picture (platform **and** hosts) stays on /status.

## Verification

Same worktree, same two live backends, one minute apart (`scripts/agent/status_host_rows.py`, a Playwright probe that reads the "Host:" rows and the tile of /status):

| | before the fix | after the fix |
|---|---|---|
| host-clone-1 rows | **2** | 1 |
| host-clone-2 rows | **2** | 1 |
| labox-backend / labox-mobile / host-clone-3 / host-android-* | 1 each | 1 each |
| "Services healthy" tile | **37/37** | **33/33** |

The four services that disappear are exactly the two duplicated hosts' two services each — the tile counts each service once.

On the live deployment (4 servers, 17 host rows) the same page read **53/57** with host-clone-1 and host-clone-2 twice before the fix. **After the deploy** (build main-2026.10.22-89636) the same live page reads **51/53** with every host listed once — the four duplicated services are gone — and the 17 host rows are the 17 distinct machines.

Re-checked after the deploys that followed (the server restarted again at 19:37 on 2026-10-22 with a build that carries other work): the live page still lists **9 host sections, every host exactly once, no duplicate** (`scripts/agent/status_host_rows.py`). The services tile reads 35/37 now instead of 51/53 because the platform registers 9 hosts instead of 17 — the fleet shrank, the de-duplication did not change.

Screenshots: [before (live)](../../tasks/qa-evidence/fix/bug-0771-before-live.png) · [before (worktree)](../../tasks/qa-evidence/fix/bug-0771-before-worktree.png) · [after (worktree)](../../tasks/qa-evidence/fix/bug-0771-after-worktree.png) · [after (live, deployed)](../../tasks/qa-evidence/fix/bug-0771-after-live.png).

Tests:

- `tests/frontend/Status.test.tsx` — renders the page with two servers that both register `host-clone-1` and asserts one accordion section per host. Against the pre-fix sources it fails with `expected [ …, … ] to have a length of 1 but got 2`.
- `tests/frontend/hostCatalog.test.ts` — the rule itself: one row per host across servers, the order kept, a later catalog filling in missing stats, a server with no hosts.

Checks: `tsc --noEmit` 0 errors · eslint clean on the changed files · `node scripts/i18n-check.mjs` 0 errors (new key present in `fr.json` and `de.json`) · the Status and hostCatalog suites 7/7 passing.
