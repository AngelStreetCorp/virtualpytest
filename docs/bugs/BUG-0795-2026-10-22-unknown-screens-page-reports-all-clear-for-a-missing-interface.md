# BUG-0795 — The Unknown screens page reports "every screen has a node in its tree" for an interface that does not exist

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0795                                                     |
| Reported  | 2026-10-22                                                   |
| Status    | Fixed                                                       |
| Severity  | Medium                                                       |
| Area      | frontend                                      |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

Found by the QA sweep of 2026-10-22 (finding DEVELOPER-03, in `docs/tasks/QA-DEVELOPER-findings.md`); reproduced against the live app.

- **Page / route:** /configuration/interface/<name>/unknown
- **Viewport / theme:** 1440 px, dark

Steps to reproduce:

1. Open `/configuration/interface/no-such-interface/unknown`.
2. Read the page.

**Expected:** "Interface no-such-interface not found", or at least no all-clear.

**Actual:** A complete healthy report: Needs a name 0, Filtered out 0, Captures 0, Last scan -, and "Every screen this device shows has a node in its tree." The real interface `stb_tv` shows 12 unnamed screens and 1,701 captures, so "no problems" and "no such interface" look the same, and a typo hides the real cause.

Evidence:

- [developer-03-interface-unknown-bogus.png](../tasks/qa-evidence/developer/developer-03-interface-unknown-bogus.png)
- [developer-03b-interface-unknown-real.png](../tasks/qa-evidence/developer/developer-03b-interface-unknown-real.png)

Related: Same defect class as the navigation editor blank-tree bug.

## Root cause

`backend_server/src/routes/server_userinterface_routes.py` — `getUnknownScreens` read the rows of
the unknown-screens table for the name it was given and answered 200, whatever that name was. An
interface that does not exist has no rows, so the answer was an empty report — the same answer it
gives for an interface whose screens all have a node.

The page then read the empty report as a healthy one: `frontend/src/pages/UserInterfaceUnknown.tsx`
renders the tiles and the "Every screen this device shows has a node in its tree." card whenever
`data.needsName` is empty, and the hook clears the data when a request fails. So "no such
interface" and "no unknown screens" looked identical on the page.

## Fix

- `backend_server/src/routes/server_userinterface_routes.py`: `getUnknownScreens` checks that the
  interface exists in the team (dev or prod row) and answers 404 `User interface "<name>" not
  found` when it does not. A request without an interface name is a 400.
- `frontend/src/pages/UserInterfaceUnknown.tsx`: when the load failed, the page shows the error
  instead of the report — no tiles, no "Every screen this device shows has a node in its tree."
  A failed load is not an empty report.

## Verification

- `tests/backend_server/test_userinterface_unknown_screens.py` (new): an interface that does not
  exist is a 404 with the reason, an interface that exists still reports, one that exists only in
  prod still reports, and the name is required.
- `tests/frontend/UserInterfaceUnknown.test.tsx` (new): the page shows the error and no healthy
  report, and still shows the healthy report when the load worked.

In the browser: `/configuration/interface/no-such-interface/unknown` shows
`User interface "no-such-interface" not found` and no all-clear
(`../tasks/qa-evidence/fix/bug-0795-unknown-screens-missing-interface.png`);
`/configuration/interface/stb_tv/unknown` still shows its 12 unnamed screens and 1,701 captures.

The 404 comes from the new server route, so the fixed state was first checked in a worktree build
with that one call answered with the 404 the new route returns
(`scripts/qa/shot_bug0795_missing_interface.py`). On the deployed build (`main-2026.10.22-89628`)
the live route answers 404 and the page shows the reason with no all-clear
(`../tasks/qa-evidence/fix/deployed/deployed-bug-0795-unknown-screens-missing-interface.png`); the
all-clear screenshot above is what the page showed while the route was not deployed yet
(`../tasks/qa-evidence/fix/bug-0795-before-all-clear-against-live-backend.png`).
