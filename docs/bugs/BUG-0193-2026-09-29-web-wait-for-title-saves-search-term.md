# BUG-0193 — Web "wait For Title To Appear" saved the title under the wrong param and always failed

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0193                                                     |
| Reported  | 2026-09-29                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium (every web page-title verification fails)             |
| Area      | frontend (verification editor)                               |
| Fixed in  | Unreleased                                                   |
| Commit    | `cf6705f30`                                                  |

---

## Symptom

On `/builder/quick-test` (target `host-clone-1`, interface `youtube-web`), a Verification step of
type WEB **wait For Title To Appear** shows one field labelled **Element Criteria** (placeholder
`text=Button`). Typing `Never Gonna Give You Up` there saves it as `search_term`; the run fails
at that step with

```
waitForTitleToAppear(check_interval='1', timeout='10000 ms', title='', search_term='Never Gonna Give You Up')
→ No title specified for waitForTitleToAppear
```

Report: script result "Rickroll x2", 2026-09-29T18:48:20Z. The Navigation editor's node/edge
verification rows use the same component and had the same problem.

## Root cause

`frontend/src/components/verification/VerificationControls.tsx` (shared by QuickTest, the
TestCase builder and the Navigation editor's node/edge dialogs) rendered a single hardcoded
`search_term` text field for **every** `adb` / `web` verification. The web controller's schema
(`backend_host/src/controllers/web/playwright_verifications.py`) gives `waitForTitleToAppear` a
`title` param and no `search_term`, so the typed value landed in a key the host never reads and
`title` stayed at its schema default `''`. `getMenuInfo` (adb and web), which only takes an
area, also showed the useless field. The pre-run check in `useVerification.ts` did not validate
web verifications at all, so the empty title reached the host.

## Fix

- `VerificationControls.tsx`: the free-text field is chosen per command — **Title** (`title`)
  for `waitForTitleToAppear`, none for `getMenuInfo`, **Element Criteria** (`search_term`) for
  the element commands.
- `useVerification.ts`: a web verification with an empty `title` / `search_term` is rejected
  before the run.
- `Verification_Types.ts`: `WebVerificationParams` declares `title`.

The backend does not accept `search_term` as a fallback for the title (no backward-compat
shims). Steps saved before the fix still hold the text under `search_term`: open the step,
retype it in the **Title** field and save.

## Verification

- `tsc --noEmit` (only the pre-existing missing-`vitest` test-file errors) and `eslint
  --max-warnings 0` on the changed files pass.
- The branch frontend was deployed to prod (`update_core.sh fix/wait-for-title-form --frontend`)
  and `https://virtualpytest.angelstreet.io/src/components/verification/VerificationControls.tsx`
  serves the per-command field.
- Still to do by hand: QuickTest → `host-clone-1` / `youtube-web` → Verification step WEB
  **wait For Title To Appear** shows **Title**; type `Never Gonna Give You Up`, save, run — the
  step log shows `title='Never Gonna Give You Up'` and no `search_term`.
