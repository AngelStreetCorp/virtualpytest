# BUG-0774 — The navigation editor opens a blank, fully enabled editor for a tree name that does not exist, with no error

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0774                                                     |
| Reported  | 2026-10-22                                                   |
| Status    | Fixed                                                       |
| Severity  | High                                                       |
| Area      | frontend                                      |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

Found by the QA sweep of 2026-10-22 (finding DEVELOPER-01, in `docs/tasks/QA-DEVELOPER-findings.md`); reproduced against the live app.

- **Page / route:** /navigation-editor/<treeName>
- **Viewport / theme:** 1440 px dark; same in light and at 390 px

Steps to reproduce:

1. Open `/navigation-editor/does-not-exist-xyz` (or `/navigation-editor/stb`, or `/navigation-editor/web_tv?mode=prod` for a tree that only exists in dev).
2. Wait about 5 seconds.

**Expected:** A clear "User interface <name> not found" message with a way back to the interface list, as `/navigation-editor` with no name already does ("Invalid URL: Missing tree name").

**Actual:** The editor renders as if the tree were empty: counter `0/0 nodes`, blank canvas, `Add Node`, `Validate`, `Build Map`, `Publish`, `Reset` enabled, no banner or toast. The only trace is a console 404 on `getUserInterfaceByName/<name>?mode=dev`. A stale bookmark or a typo lands on a working-looking editor and the developer may add nodes to the wrong place.

Evidence:

- [developer-01-nav-editor-not-found.png](../tasks/qa-evidence/developer/developer-01-nav-editor-not-found.png)
- [developer-01b-nav-editor-prod-mode.png](../tasks/qa-evidence/developer/developer-01b-nav-editor-prod-mode.png)

Related: Same defect class: BUG-0795 (the Unknown screens page reports an all-clear for an interface that does not exist).

## Root cause

`frontend/src/pages/NavigationEditor.tsx:1294` (before the fix): the `catch` of the interface lookup only wrote to the
console and reset `lastResolvedTreeName`; no error state was set. The page therefore kept rendering its normal editor —
a blank canvas, the counter `0/0 nodes` and a fully enabled toolbar — for an interface that does not exist.

The lookup itself was correct: `useUserInterface.getUserInterfaceByName` answers a 404 with a `UserInterfaceNotFoundError`
whose message already says what is wrong (`User interface "x" not found`, or `No prod snapshot published for "x" — it
exists in dev only`). Nothing carried that message to the screen.

A second, quieter cause sat behind the first one and made the first fix invisible in the browser: the new resolution
hook cancelled its own lookup. The page re-renders for many unrelated reasons, and the callback the page hands to the
hook (`setUserInterfaceFromProps`) is rebuilt whenever the navigation context is rebuilt, so the effect re-ran while the
request was still in flight. Its cleanup dropped the answer, the error state was never set, and the page went on
showing the empty editor. The request itself was correct all along — the browser showed
`404 /server/userinterface/getUserInterfaceByName/does-not-exist-xyz?mode=dev` and then, silently, nothing.

## Fix

- New hook `frontend/src/hooks/navigation/useUserInterfaceResolution.ts`: it resolves the interface for the name and
  mode in the URL and returns the reason when there is none. One lookup per tree+mode (a key keeps a failing lookup from
  being retried on every render), and `retry()` looks it up again.
  The answer of a running lookup is never dropped: a newer attempt (another tree, mode or `retry()`) supersedes the
  older one through an attempt key, and a re-render of the page does not cancel anything.
- New component `frontend/src/components/navigation/Navigation_InterfaceNotFound.tsx`: the screen the editor shows instead
  of itself — the reason, and a **Back to Interfaces** button.
- `frontend/src/pages/NavigationEditor.tsx`: the page uses the hook and renders that screen when it reports a failure.
  The editor (canvas, toolbar, **Add Node**, **Publish**) is not rendered at all, so there is nothing live to click.

## Verification

- `tests/frontend/UserInterfaceResolution.test.tsx` (new): a missing interface, a dev-only interface asked for in prod, a
  failed load that is not a missing interface, the interface handed over when it is found, one lookup per tree+mode (no
  retry storm) and `retry()`. Plus the screen itself: the reason and the way back to the interface list.
  Run: `scripts/run-vitest.sh UserInterfaceResolution` — 9 passed.
  Two of them are the regression tests for the race above: the failure survives a re-render while the lookup is running,
  and the interface is handed to the callback the page holds *after* that re-render. Both fail against the hook without
  the fix (2 failed | 7 passed).
- In the browser: `/navigation-editor/does-not-exist-xyz` shows "This tree cannot be opened" with
  `User interface "does-not-exist-xyz" not found` and a **Back to Interfaces** button; no canvas, no toolbar.
  Screenshots: `../tasks/qa-evidence/fix/bug-0774-nav-editor-not-found.png` (light) and
  `../tasks/qa-evidence/fix/bug-0774-nav-editor-not-found-dark.png` (dark).
  The network log of that run shows the lookup answered `404` and the page turned it into the message above.

Before the fix the same URL showed the empty editor with `0/0 nodes` and an enabled toolbar
(`../tasks/qa-evidence/developer/developer-01-nav-editor-not-found.png`).

On the deployed build (`main-2026.10.22-89628`) the same page shows the message and no toolbar
(`../tasks/qa-evidence/fix/deployed/deployed-bug-0774-nav-editor-not-found.png`).
