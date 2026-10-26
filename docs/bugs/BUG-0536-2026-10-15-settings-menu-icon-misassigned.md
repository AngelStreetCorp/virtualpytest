# BUG-0536 — Settings dropdown: bug icon on Status, no icon on "Open a ticket"

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0536                                                     |
| Reported  | 2026-10-15                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Low                                                          |
| Area      | frontend / navigation                                        |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

In the **Settings** dropdown of the top nav, the **Status** row shows a bug/beetle icon
(MUI `BugReport`), and the **Open a ticket** row (zammad feature) shows no icon at all.
A bug icon means "report a defect" — which is *Open a ticket* — not "service health",
which is what the Status page (at `/status`, the service monitor) actually is. The icon
on Status was always a mismatch; Open a ticket being iconless left the row visually
incomplete next to its neighbours.

## Root cause

`Status` had been wired to `<TestingIcon />`, which is the MUI `BugReport` import
(`import { BugReport as TestingIcon }` in `frontend/src/config/navItems.tsx`). The
"Open a ticket" feature entry in `features/zammad/frontend/routes.tsx` never set its
`icon:` field, so the row rendered with the dropdown's default padding-only treatment.

## Fix

`frontend/src/config/navItems.tsx`
- Adds `Bolt as BoltIcon` to the existing @mui/icons-material import.
- Changes the `Status` row from `<TestingIcon />` to `<BoltIcon />` — the lightning
  bolt reads as "live service health", which is what the page shows. The same `BoltIcon`
  is already used in `components/rec/RecStreamModalHeader.tsx`, so the new glyph shares
  the project's existing icon language.

`features/zammad/frontend/routes.tsx`
- Adds `import { BugReport as BugIcon } from '@mui/icons-material';`.
- Adds `icon: <BugIcon fontSize="small" />,` to the `Open a ticket` `settings` nav entry.
  The icon now matches the row's meaning: filing a bug.

## Verification

`frontend/node_modules/.bin/tsc --noEmit` and
`frontend/node_modules/.bin/eslint src/config/navItems.tsx ../features/zammad/frontend/routes.tsx`
both pass clean on the worktree (same code passed once in the main checkout before the move).
