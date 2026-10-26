# BUG-0608: project page in-scope `+ add` and `×` buttons were no-op stubs

**Date:** 2026-10-18
**Discovered on:** the project detail page after BUG-0606 shipped the in-scope section. The buttons were rendered but their click handlers were comment-stubs.
**Severity:** medium — the API surface was complete (BUG-0579: `POST /link`, `POST/DELETE /tags/names`; existing `PUT /server/device-flags`), but the user couldn't trigger any of it. The project page promised a manual linking flow and didn't deliver.
**Status:** fixed on branch `fix/project-page-v2-add-remove`.

## Symptom

The BUG-0606 in-scope section rendered `+ add device`, `+ add script / testcase / virtual`, and `+ add campaign` buttons. Clicking any of them did nothing. The `×` button on a device row was also a no-op (the comment said "this is a stub"). The only working action was `×` on executables (script / testcase / virtual / campaign), which had the `DELETE /link` mutation already wired.

The tag chips in the project header were also missing entirely — the page showed owner / viewer chips but no scope / user-tag chips, so the user couldn't see or edit the project's tag list.

## Root cause

The BUG-0606 slice was scoped to "render the section". The 3 dialog components and the device `×` handler were deferred with `/* future: ... */` comments because the slice was already long. The right move was to land them in the same commit — they're a single UX unit, not separable.

## Fix

Three new components and one handler update, all small:

### New components

- **`ProjectTagsEditor.tsx`** — the chip row that lives in the project header next to the owner / viewer chips. Renders the scope tag (locked, with a tooltip explaining it's auto from the project name), each user tag (with a `×` that calls `DELETE /server/projects/<id>/tags/names/<name>`), and a small `+` button that opens a Dialog with a comma- or space-separated input. The Dialog's submit POSTs `{names: [...]}` to the same `POST /tags/names` endpoint. The scope tag is read-only here — the backend returns 400 if you try to remove it, but the UI never offers the affordance. The editor owns the dialog state; the parent re-fetches the in-scope + overview queries on each change.

- **`AddDeviceDialog.tsx`** — a Dialog with a search box and a list of every device NOT already in scope. The data source is the existing `useDeviceFlags` hook (no new endpoint). Each row shows the device's current flags so the user can see what they're about to set. Picking a device fetches its current flags, unions with the project's tag names (case-insensitive dedup), and PUTs the new array back to `PUT /server/device-flags/<host>/<device>`. The PUT replaces the entire flags array, so the union logic is what preserves the device's existing tags.

- **`AddExecutableDialog.tsx`** — a Dialog that handles all four executable kinds (script / testcase / virtual / campaign) via a chip-row type filter at the top. Each kind fetches from a different endpoint (`/server/script/list`, `/server/testcase/list`, `/server/virtual-script/list`, `/server/campaigns/getAllCampaigns`) and normalises the response into `{id, name}`. Already-in-scope items are filtered out using the same `inScopeByKind` set the parent computes from the in-scope response. Picking an item POSTs `{type, id}` to `POST /server/projects/<id>/link`. The list is capped at 200 rows so the dialog stays snappy.

### Wiring updates

- **`ProjectInScope.tsx`** — owns the new `addOpen: 'device' | 'executable' | null` state. The two `onAdd` props on the three column components now flip `addOpen` to the right value. The previously-no-op `removeDevice` handler is no longer a stub: it reads the device's current flags from the existing `useDeviceFlags` data, filters out any tag that matches the project's `tag_names` (case-insensitive), and PUTs the new array back. The same optimistic-hide-then-rollback pattern that `removeLink` uses.
- **`ProjectDetail.tsx`** — renders `<ProjectTagsEditor>` in the header right-slot between the viewer chip and the executive-summary link. Adds `teamId` to the `<ProjectInScope>` props (the executable picker needs it for the list endpoints). The `onChanged` callback now invalidates both the in-scope AND the overview query (the tag list appears in both).

### Permission model

Same gate as the rest of the page: `canEdit` (admin OR project owner per `_can_edit_project` in the overview's `permissions.can_edit`). The `+ add` buttons and the `×` on user-tag chips and on-device rows only render when `canEdit` is true. The scope-tag chip has no `×` regardless.

## Files

- `frontend/src/components/projects/ProjectTagsEditor.tsx` (new, ~190 lines)
- `frontend/src/components/projects/AddDeviceDialog.tsx` (new, ~205 lines)
- `frontend/src/components/projects/AddExecutableDialog.tsx` (new, ~260 lines)
- `frontend/src/components/projects/ProjectInScope.tsx` (state + handlers + render)
- `frontend/src/pages/ProjectDetail.tsx` (ProjectTagsEditor mount + teamId passthrough)
- `frontend/src/i18n/locales/fr.json` + `de.json` (28 new keys × 2 locales)
- `docs/release_note/README.md` (1 new Features entry)

## Verification

- tsc clean (0 errors)
- i18n-check 0 errors (28 new keys × 2 locales — all unique)
- eslint clean
- ui-check clean
- A `+ add device` click in the picker fetches the existing `/server/device-flags/batch` payload, filters out in-scope devices, and on select PUTs the unioned flags array to the device's row. The `×` on a device row reads the row, filters out the project's tag_names, and PUTs back.
- A `+ add script / testcase / virtual / campaign` click opens the picker with the right endpoint for the active chip. On select, POST `/server/projects/<id>/link` is called with `{type, id}`.
- A `+ add user tag` in the header opens a Dialog with a single text input. The submit POSTs `/server/projects/<id>/tags/names` with `{names: [...]}` (comma- or space-separated). The scope tag is silently skipped if the user types its name in. The `×` on each user-tag chip DELETEs `/server/projects/<id>/tags/names/<name>`.

## What's not in this slice (v3)

- **Per-item token counts.** Still deferred to a real v2 with a schema decision (`ai_usage_stats` doesn't link to `script_name` / `virtual_script_id`).
- **The "add device" picker skips never-flagged devices.** `device_flags` is opt-in (created on host registration via `upsert_device_on_registration`). The dialog only shows devices that already have at least one flag, so the user can't bootstrap a brand-new device from the project page. A small "register this device" button on a never-flagged device would close this loop, but it needs a new endpoint (the current PUT returns 404 if the row doesn't exist).
- **Bulk add.** Picking one device at a time is fine for a 5-device project, tedious for a 50-device fleet. A "select all" checkbox per host group is a v3 enhancement.
## Renumber note (BUG-0609)

This slice was originally filed as `BUG-0607` on the feature branch. Between the
renumber commit (`09023cbde`) and the push of the feature branch
(`489a0f1f9`), a parallel pokemon agent merged
[`a8ac97f68 chore(pokemon): renumber BUG-0598 saffron-step fix to BUG-0607 (id collision)`](BUG-0607-2026-10-18-saffron-step-prefers-east-edge-toward-route7-gate.md)
onto `origin/main`, claiming `BUG-0607` for the saffron-step fix.

The renumber was applied as a separate commit on the feature branch:
`docs/bugs/BUG-0607-...md -> BUG-0608-...md`, plus a `sed` over the four files
that referenced the id (the release-note entry, `ProjectInScope.tsx`, and
`ProjectDetail.tsx`). The git pre-push review gate tripped on the
collision but accepted the renumbered version.

If you came to this doc via the original `BUG-0607` tag in a release note from
a June 2026 release, you actually mean
[BUG-0607 — saffron-step prefers east edge toward Route 7 gate](BUG-0607-2026-10-18-saffron-step-prefers-east-edge-toward-route7-gate.md);
this doc has always been about the projects slice.

## Visual reference

The final wireframe this slice was built from is documented as `TASK-101 v3`:
[`docs/tasks/TASK-101-project-page-mockup-v3.html`](../tasks/TASK-101-project-page-mockup-v3.html)
(stored alongside the v1 workflow + audit mockup and the v2 manual-in-scope
mockup). The implementation tracks the v3 layout: **Devices** grouped by host,
**Executables** as a flat peer list of scripts + testcases + virtuals (with the
v3 "different concept" fix), and **Campaigns** in a separate full-width band.

For the in-scope section shell that consumes these dialogs (the side-by-side
react component that the `+ add` buttons sit in), see
[BUG-0606 — project detail in-scope section](BUG-0606-2026-10-17-project-detail-in-scope-section.md).

## Update 2026-10-20

The two add dialogs and the inline tag chips described above were replaced by one `AddToProjectDialog` (all kinds, tick list, "Add N") and a tag dialog opened from the tag count in the header; the executive-summary link no longer exists (see TASK-65, "one project page").
