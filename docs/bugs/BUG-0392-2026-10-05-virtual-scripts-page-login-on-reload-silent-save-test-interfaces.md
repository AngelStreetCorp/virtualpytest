# BUG-0392 — Virtual Scripts page: reload lands on login after a server switch, Save sometimes silent, test interfaces in the list

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0392                                                     |
| Reported  | 2026-10-05                                                   |
| Status    | Open — (a) fixed (auto-sign verified live), (b) fixed, (c) owner decision |
| Severity  | Low                                                          |
| Area      | frontend                                                     |
| Fixed in  | Unreleased                                                   |
| Commit    | TBD                                                          |

---

## Symptom

Three things seen on the Virtual Scripts page:

- **(a)** After switching the header Server selector to a second server, reloading the page lands on
  `/login`.
- **(b)** Save sometimes does not register: the "Unsaved" mark stays and a second click is needed.
- **(c)** The Interface dropdown lists many `acceptance-stb4-tv-*` interfaces left over from test
  runs.

## Root cause

**(b) — found.** `saveScript` (`features/virtual-scripts/frontend/hooks/useVirtualScripts.ts`) used
`api.post`, which throws on any non-2xx answer. The save route answers a rejected save with a
JSON reason and 400 (syntax error, with the line), 404 or 409 (name already used), and
`handleSave` (`VirtualScripts.tsx`) had `try/finally` with no `catch`. A rejected or failed save
therefore showed nothing at all: no toast, the syntax-error line was never shown, and "Unsaved"
stayed, so it looked like the click had not registered. Why a second click then succeeded was not
reproduced (a transient failure such as an expired session token being refreshed would fit); with
the fix the first failure now says why.

**(a) — found (2026-10-05).** Two paths, one per kind of sign-in:

- **Auto-signed tab (reproduced live).** `tryActivateAutoSign()` (`frontend/src/lib/autoSign.ts`)
  runs on every page load. `?auto_signed=<token>` stores the token and strips it from the URL; on
  a reload the URL has no token, and the "already activated" branch also required the build-time
  `VITE_AUTO_SIGN_ENABLED`, which production builds leave off — so it fell through to
  `clearAutoSignSession()`, wiped the stored token and returned false. AuthContext then looked
  for a Supabase session, found none, and ProtectedRoute sent the reload to `/login`. Client-side
  navigation never re-ran it, which is why the token appeared to "survive navigation".
- **Real login (not reproduced live; consistent with the code).** AuthContext's 3 s safety
  timeout ended loading with no user while `supabase.auth.getSession()` was still running.
  `setUser` happens as soon as `getSession()` returns (the profile fetch is after it), so only a
  slow `getSession()` triggers it: on a reload with an expired access token it refreshes over the
  network, and it holds supabase-js's storage lock, which every request started on page load also
  takes (`getAccessTokenForRequest`, the server picker's `getServerAuthState` per selected
  server). With a second server selected there are more of those, so the 3 s were exceeded more
  easily — the "after switching server" pattern. LoginPage then sent the user to `/`, not back to
  the page, once the session did resolve; if the refresh stalled they stayed on `/login`.

**(c) — documented for the owner, nothing deleted.** The interfaces are created by the STB
acceptance pipeline (outside this repository), which builds its own copy of the STB tree on every
run, named `acceptance-stb4-tv-<YYYYMMDD-HHMM>-stb`, and is meant to delete it afterwards. On
2026-10-05 the lab database held **13** of them (`userinterfaces.name LIKE 'acceptance-%'`, created
2026-10-01 to 2026-10-04), so that cleanup is not running. Before deleting them: AI-dataset samples
were captured on these trees and are filed under `stb_tv` by
`features/ai-dataset/scripts/fold_temp_trees.py`; run it first (TASK-27), or the samples lose their
screen list. Owner decision: delete the leftovers and fix the pipeline's cleanup, or hide the
`acceptance-*` / `qa-*` pattern in the selector.

## Fix

(b): `saveScript` now reads the JSON body whatever the status, so the existing handling shows the
syntax error with its line or the server's reason; `handleSave` catches network/auth failures and
shows "Save failed: …". (c): no change.

(a):
- `autoSign.ts`: a tab whose sessionStorage holds the flag and a URL-supplied token stays
  auto-signed on reload, whatever the build flag. Tab-scoped on purpose (sessionStorage only, not
  the localStorage copy), so a new tab or browser restart still needs the URL token; the backend
  still validates the token on every call.
- `AuthContext.tsx`: the fallback that gives up on session restore is 35 s (past supabase-js's
  refresh retry window), not 3 s.
- `LoginPage.tsx`: once authenticated, it returns to the page ProtectedRoute came from
  (`state.from`), not `/`.

## Verification

- `cd frontend && ./node_modules/.bin/tsc --noEmit` passes.
- On the deployed build: save a script with a syntax error → "Syntax error on line N"; save a second
  script under an existing name → the "already exists" message; "Unsaved" stays only in those cases.

### Live check of (b) (2026-10-05, node1, frontend main-2026.10.05-10033)

Save of a virtual script with a syntax error: `POST /server/virtual-script/save` → 400 and a toast "Syntax error on line 9: expected '('"; "Unsaved" stays. (b) is fixed; the bug stays Open for (a) and (c).

### Verification of (a) (2026-10-05, local)

- `cd frontend && ./node_modules/.bin/tsc --noEmit` passes.
- New Playwright test `reload keeps an auto-signed session (BUG-0392)` in
  `tests/e2e/playwright/specs/task42-run-management.spec.ts` (mocked API, `scripts/task42/run_playwright.sh`),
  on a build with `VITE_SUPABASE_URL`/`VITE_SUPABASE_ANON_KEY` set (any value; without them the login
  gate is off): passes with the fix, fails on the previous `autoSign.ts` (the page is gone after reload).
- Pending deploy: reload an auto-signed page on node1; for a real login, reload after an hour idle
  with two servers selected and check the `[@AuthContext]` console lines.



## Live check of (a) on node1 (2026-10-05, frontend main-2026.10.05-10043)

A headless browser opened `/scripts/virtual?auto_signed=…`, reloaded, then went to another page and reloaded again: it stayed signed in each time (top bar shown, no `/login`). The real-login path (35 s session-restore fallback) is not reproduced yet. (c) is left as is: the owner decided the leftover interfaces do no harm and need not be deleted now.
