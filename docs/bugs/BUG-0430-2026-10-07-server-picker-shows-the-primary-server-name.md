# BUG-0430 — Every server in the picker showed the primary server's name

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0430                                                     |
| Reported  | 2026-10-07                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                         |
| Area      | frontend                                                     |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

On a deployment with several servers configured, the Server picker listed the **same name
on every row** — the primary server's. With four configured servers, all four rows read
identically, and the closed select showed the primary's name too. Servers you are not
signed into still showed their own (correct) names behind a padlock.

Picking a different server and browsing any page kept answering from the primary server:
its devices, workspaces and reports were returned while a secondary server was selected.

## Root cause

`frontend/src/utils/buildUrlUtils.ts` — `buildServerUrl` and `buildServerUrlForServer`.

Both rebuilt their result as:

```ts
const u = new URL(url);
u.searchParams.delete('team_id');
url = u.pathname + (u.search ? u.search : '') + u.hash;   // ← no origin
```

`pathname + search + hash` keeps everything **except the origin**. A path-only URL is
resolved by the browser against the page's own host, so every "per-server" URL silently
became a request to whichever server was serving the page. The line was added in
`17eb89cd8` ("make buildServerUrl idempotent for team_id", TASK-66) — the intent was to
strip a duplicate `team_id`; the origin loss was collateral.

The picker is where it became visible. `ServerManagerProvider` fetches `getAllHosts` once
per configured server through `buildServerUrlForServer`, and stamps each entry with **its
own** `server_url` but the `server_name` **from the response** — so N servers produced N
identically-named entries. Servers in the `needs-auth` state are skipped by that fetch and
fall back to `/server/auth/check`, which `probeServerIdentity` builds by string
concatenation and was never affected; that is why the padlocked rows still read correctly.

Blast radius: 434 `buildServerUrl` call sites and 8 `buildServerUrlForServer`. Because
`getServerBaseUrl()` returns the *selected* server, the selection was effectively ignored
across the whole app, not just in the picker.

Why it was not caught earlier: every local, preview and validation setup serves the
frontend **from** the target server (`VITE_SERVER_URL` points at it), so a path-only URL
resolves correctly there. The defect only shows when one frontend serves several servers.

## Fix

`url = u.toString()` in both functions, so the origin survives. `team_id` is still deleted
before the single append, so TASK-66 stays fixed; a relative URL still throws inside `new
URL()` and is left untouched by the `catch`.

## Verification

- `tests/frontend/buildUrlUtils.test.ts` — 9 tests covering origin preservation per server,
  distinct origins for distinct servers, `team_id` idempotency (one `team_id`, not two),
  `/server` suffix stripping, protocol guessing, the empty-URL rejection, and the
  configured-server list. **6 of the 9 fail against the pre-fix code**, all 9 pass after it.
- Full frontend component suite passes.
- After deploy, on a multi-server deployment: open the picker — each row shows its own
  server name. In the network tab, one `getAllHosts` per server, each to its own host
  (before: every request to the primary).
- Select a secondary server, reload a data page, and confirm the request goes to that
  server rather than the primary.
- After deploy, clear the browser's `serverHostsData_cache` localStorage entry once: the
  cached `server_name` of the affected rows is wrong until the first successful fetch round
  replaces it.
