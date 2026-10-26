# BUG-0544 — Platform update opened with ?to=<build> shows "installed → —" instead of the chosen build

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                  |
|-----------|--------------------------------------------------------|
| ID        | BUG-0544                                               |
| Reported  | 2026-10-15                                             |
| Status    | Fixed (pending deploy)                                 |
| Severity  | Minor (the operator cannot see which build a roll-out targets) |
| Area      | frontend / platform update, release notes              |
| Fixed in  | build 90145 |
| Commit    | see branch fix/platform-update-to-param                |

---

## Symptom

Release Notes -> Compare -> "Roll out this update" opens `/configuration/platform-update?to=9364`. The page header read
`main-2026.10.15-88085 → —`: the target was empty.

## Root cause

1. `BundleBuilder` resolved `?to=` against the core release tags but loaded those tags only when step 2 was unlocked,
   i.e. after a run was started. Before that no tag matched and the header target stayed empty.
2. The core remote (public snapshot) only carries some builds as tags. A build with no tag (e.g. 9364) can never match,
   and Release Notes still offered Roll out for it.

## Fix

- `PlatformUpdate.tsx` loads the core candidates once on page load and shows the requested target at once
  (`→ build 9364`, or the matching tag such as `main-2026.09.27-9396` when it exists).
- No matching tag: a "not published" chip with the tooltip "Build N has no release tag on <remote>. Pick a published
  build or use a zip."; step 2 preselects nothing (no silent fallback to the newest tag).
- `ReleaseNotesView` (admin, compare view) reads the same list and disables "Roll out this update" with that tooltip
  when the target build has no tag.

## Verification

`?to=9396` shows the `main-2026.09.27-9396` tag; `?to=9364` shows `build 9364` with the "not published" chip and an
empty release-tag picker in step 2.
