# BUG-0502 — Every page load showed a stripped-down "loading screen", and the e2e harness could not authenticate at all

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0502                                                     |
| Reported  | 2026-10-13                                                   |
| Status    | Closed                                                       |
| Severity  | Medium                                                       |
| Area      | frontend (auth boot, AgentChat splash) · tests/e2e/playwright |
| Fixed in  | build 90145 |
| Commit    | `4c005c48d`, `89036e65d`, `89f4b8b18`, `d76e5164c`                   |

---

## Symptom

Opening `https://virtualpytest.angelstreet.io/ai-agent` always showed a loading screen before the
page appeared. The first fix (below) did not remove it, because a **different** component was
responsible — and while chasing it, the Playwright e2e harness turned out to be unable to
authenticate on any deployment.

## Two separate loading screens, not one

`/ai-agent` has four distinct loaders, and they must be told apart before fixing anything:

| # | What you see | Source |
|---|--------------|--------|
| 1 | Full-screen `AI Agent` + sparkle, page takeover | `pages/AgentChat.tsx` portal, gated on `agentchat_visited` |
| 2 | `Loading...` + spinner, centred | the generic `<Suspense>` fallback in `App.tsx` |
| 3 | `Loading agents...`, centred in the chat area | `components/agent-chat/ChatMessages.tsx`, while `/server/agents/` is in flight |
| 4 | Bare header + footer, **empty body, no text** | `App.tsx` forcing the minimal logo-only header while `isLoading` |

#2 was a red herring: the AgentChat chunk is 64 KB brotli and downloads in ~35 ms.
#3 is a ~100 ms transient (`/server/agents/` returns 200 at ~685 ms), present before and after the fix.

## Root cause 1 — the splash flag was per-tab and written only on success

`AgentChat.tsx` gated its splash on `sessionStorage.getItem('agentchat_visited')`, and wrote it
inside the `try` of the `/server/agents/` loader. Two defects:

- **`sessionStorage` is scoped to a single tab.** It survives an F5 in that tab but is empty in
  every new tab, every bookmark open and every browser restart. The code comment already said
  "first visit only" — the intent was right, the storage scope was wrong, so the comment misled
  the next reader.
- **Writing it only on success** meant one transient backend failure left the flag unset forever and
  brought the full-screen overlay back on every subsequent load.

Fixed by reading and writing `localStorage` (per-origin, shared by all tabs) and moving the write
into a `finally`. Verified live: the served bundle contains
`useState(()=>localStorage.getItem(qa)==="true")` and `finally{localStorage.setItem(qa,"true")}`.

## Root cause 2 — the app shell was withheld for the whole auth wait

`AppHeader` did `if (isAuthPage || isLoading)`, returning a **minimal** header (logo + theme toggle,
no nav bar, no server picker, no workspace switcher) while auth resolved. Combined with
`ProtectedRoute` returning `null`, every cold load rendered a header + footer with a blank middle —
which reads as a broken page rather than a page that is still arriving.

`AuthContext` only clears `isLoading` after `getSession()` **plus a profile round trip**
(`AuthContext.tsx:195`), so the wait is irreducible: rendering protected content earlier would leak
it. But the chrome does not need to wait for it.

Measured, headless, same probe before and after (1280×720):

| Scenario | Before | After |
|----------|--------|-------|
| Cold profile, first ever load | bare frame 532 → 788 ms (256 ms) | full chrome 684 → 917 ms (233 ms) |
| New tab, page already visited | bare frame 361 → 637 ms (276 ms) | full chrome 385 → 640 ms (255 ms) |
| F5 / hard reload | bare frame 161 → 332 ms (171 ms) | full chrome 181 → 311 ms (130 ms) |

The duration barely moved — **what is on screen changed**. The first paint is now the real app frame
(logo, server picker, workspace switcher, full nav) with only the content area waiting, instead of a
bare logo+footer page with no navigation.

`ProtectedRoute`'s `Checking authentication...` delay was also raised from 500 ms to 1500 ms: at
500 ms it fired just before real content landed on a remote load, replacing one loading screen with
another.

## Root cause 3 — the e2e harness could never authenticate

`frontend/src/lib/autoSign.ts` → `tryActivateAutoSign()` restores the session from
**`sessionStorage` only** (deliberate, BUG-0392). Playwright's `storageState` captures
`localStorage` and **never** `sessionStorage`. So the state `global-setup.js` saved was precisely
what the next page load fell through to `clearAutoSignSession()` and wiped. The harness looked
green while every spec silently landed on `/login`. The checked-in
`playwright/.auth/user.json` is dated 2026-09-16 and bounces to `/login`.

Proven headlessly:

```
PATH 1 — global-setup.js pattern
  after activation      : {ls_flag:"true", ls_tok:"present", ss_flag:"true", ss_tok:"present"} | /
  replayed storageState : {ls_flag:null,  ls_tok:null,      ss_flag:null,   ss_tok:null}      | /login   FAILS
PATH 2 — ?auto_signed= on the page under test (same tab)
  after load                                                                        | /ai-agent  WORKS
PATH 3 — reload of that same tab                                                     | /ai-agent  WORKS
```

Fixed in `global-setup.js`: it now **verifies** the token by loading `/dashboard` in a fresh context
and throws if it lands on `/login`, instead of implying the saved state authenticates anything.

## Contributing trap: an unreadable `.env` looks like an unset variable

`/opt/virtualpytest/.env` on the server VM is `-rw-r----- vpt_user:vpt_user`. A plain `grep` as
`<operator>` fails with `Permission denied`, and a `grep -q` in an `if` turns that failure into a clean
`false` — indistinguishable from "the variable is not set". This produced a wrong conclusion
(auto-sign reported as disabled) before being re-checked with `sudo`, which showed
`AUTO_SIGN_ENABLED=true` and a token present.

**Never conclude a variable is absent from a command that was allowed to fail.**

## Regression checks

- Unauthenticated deep links still redirect: `/ai-agent`, `/dashboard`, `/device-control` → `/login`.
- The top-right icon overlap seen in the new first paint is **pre-existing** — present in the
  pre-fix build too (footer `main-2026.10.13-10945`), unrelated to this change.

## The content area — now a skeleton, not a void

`ProtectedRoute` returned `null` while auth/permissions resolved, so the first ~130–300 ms of every
cold load showed the app frame over an empty body. It now renders `PageSkeleton`
(`components/common/PageSkeleton.tsx`): a neutral, generic page shape — title row with actions, four
stat tiles, a body block — with **no text, no spinner and no "loading" wording**, so the arrival of
real content is grey blocks → content rather than void → content (UI_STYLE §S6: a loading state is
the size of the content it replaces, so it fills the viewport rather than a guessed card).

Scoped to the **first** resolution via an `awaitingFirstContent` ref: `permissionsLoading` can flip
back to true on a later navigation when `useRoles` refetches role defaults, and a skeleton then
would erase content the user is already reading. Later waits render nothing instead.

It is deliberately generic — it mounts above the route, before any page's data is known, so it must
not pretend to know the layout.

## Not changed

- The wait itself is irreducible: `AuthContext` clears `isLoading` only after a profile round trip,
  and rendering protected content earlier would flash content the user must not see.
- The two `E2E_AUTO_SIGN_*` runtime fallbacks in `autoSign.ts` remain dead code (Vite replaces
  `import.meta.env` with `{}`). Documented in `docs/agent/validation/TESTING.md`.
