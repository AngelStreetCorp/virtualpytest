# BUG-0532 — "View target report" / "View Debug Report" links return 401 Unauthorized

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0532                                                     |
| Reported  | 2026-10-14                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | frontend / navigation                                        |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

After a failed navigation, clicking "View target report" or "View Debug Report" opens
`/host/<name>/stream/<capture>/reports/verification_failure_*.html` in a new tab and shows 401 Unauthorized.

## Root cause

The proxy gates `/host/<name>/stream/...` behind a short-lived host-session cookie. A plain
`<a href target="_blank">` never mints it; only `openHostUrl()` does.

## Fix

`Navigation_NodeGotoPanel.tsx` (target/sibling report and Debug Report links) and
`Navigation_NodeEditDialog.tsx` (verification report link) keep their `href` (right-click copy) but
click through `openHostUrl()`, which mints the session cookie and then opens the tab.

## Verification

`tsc --noEmit` and the i18n check pass. Not clicked on a live host yet.
