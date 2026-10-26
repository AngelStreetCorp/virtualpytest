# BUG-0776 — On a phone the Agent Chat removes every way to leave the page: no bottom navigation, no back or close control

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0776                                                     |
| Reported  | 2026-10-22                                                   |
| Status    | Fixed                                                        |
| Severity  | High                                                         |
| Area      | frontend / mobile                                            |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |
---

## Symptom

Found by the QA sweep of 2026-10-22 (finding DEVELOPER-05, in `docs/tasks/QA-DEVELOPER-findings.md`); reproduced against the live app.

- **Page / route:** /ai-agent
- **Viewport / theme:** 390 px phone, light and dark

Steps to reproduce:

1. Open the app at 390 px; the bottom bar shows Dashboard, Device, Run, Heatmap, More.
2. Tap More, then AI (the first entry).
3. Look for a way back.

**Expected:** A bottom bar, a back arrow or a close button.

**Actual:** The chat is full screen; the bottom navigation is hidden on this route, and the only controls on screen are `Details`, `Hide` (global run strip) and `send message`. In a browser the user can press Back; in the Capacitor native app (no browser chrome) it is a dead end.

Evidence:

- [developer-05-phone-ai-agent-no-nav.png](../tasks/qa-evidence/developer/developer-05-phone-ai-agent-no-nav.png)
- Fix evidence: [after EN dark](../tasks/qa-evidence/fix/bug-0776-after-en-dark.png) · [after FR light](../tasks/qa-evidence/fix/bug-0776-after-fr-light.png)

## Root cause

`frontend/src/components/mobile/MobileBottomNav.tsx:76` returns null on `/ai-agent`; `MobileMoreMenuItems.tsx:35` makes AI the first menu item; `components/ai/MobileAgentChat.tsx` renders one IconButton (send).

The bottom nav is hidden on that route on purpose (the chat is meant to be the whole screen on a
phone), so the page itself has to offer the way out — and it did not: `MobileAgentChat` rendered
the message list and the input bar and nothing else. There was no back arrow, no close button and
no title, so on a phone the only way out was the browser's own back gesture, which the Capacitor
native app does not have.

## Fix

`frontend/src/components/ai/MobileAgentChat.tsx` now opens with a small bar: a **back arrow** and
the page title.

- The arrow goes back to the page the chat was opened from (`navigate(-1)`). React Router keeps an
  `idx` counter in the history state, so the component can tell "there is a page behind me" from
  "the app was launched straight onto the chat"; in that case it lands on the **dashboard** instead
  of going nowhere.
- The arrow carries the translated accessible name (`Back` / `Retour` / `Zurück`), and the title is
  `AI Agent` (`Agent IA` / `KI-Agent`), both already in the catalogues.

The chat keeps the full screen (the bottom navigation is still hidden on `/ai-agent`); only a
40 px bar was added on top.

## Tests

`tests/frontend/MobileAgentChatBack.test.tsx` — 3 cases: the chat renders a control with the
accessible name "Back"; clicking it goes to the dashboard when the app was opened straight onto the
chat (`history.state.idx === 0`); clicking it goes back (`navigate(-1)`) when there is a page
behind it (`idx > 0`).

Verified against the pre-fix sources via `git stash`: **3 failed / 3 passed**; on the fixed sources
**3 passed**.

## Verification

Checked in a real browser at 390 × 844 (Vite dev + the live backend) in EN / FR / DE, dark and
light — six combinations, all with the arrow visible and named in the page's language:

| | EN | FR | DE |
|---|---|---|---|
| dark | `Back` | `Retour` | `Zurück` |
| light | `Back` | `Retour` | `Zurück` |

The bottom navigation stays hidden on `/ai-agent` (the chat is still full screen), and the only
other control on the page is still the send button. No new console error.

Deployed as `main-2026.10.22-89636` (integration `int-mvjsys09db00cb`), verified on the live site.
