# BUG-0606: project detail page has no in-scope section after BUG-0579 API landed

**Date:** 2026-10-17
**Discovered on:** `/projects/<id>` after BUG-0579 (`/server/projects/<id>/in-scope` aggregator + 4 link/tag routes) shipped.
**Severity:** medium — the API surface was complete, but the page had no consumer. A user landing on `/projects/<id>` couldn't see which devices / scripts / testcases / virtuals / campaigns were in scope, couldn't add a missing artefact, and the `Executables` tile still read `Scripts: N` (the legacy `scripts_count`) instead of the G11-compliant sum (scripts + testcases + virtuals).
**Status:** fixed on branch `fix/project-page-in-scope-ui`.

## Symptom

The BUG-0577 + BUG-0578 stack gave the project page:
- header with folder icon, name, owner/viewer/scope/user tag chips, executive summary link, rename / delete IconButton pair (BUG-0577)
- back arrow to `/projects` (BUG-0577 follow-on)
- 6 stat tiles (Executables, Runs 30d, Devices, AI tokens 30d, Active users, Failures)
- a "Last 10 failures" paper

…but no consumer of the new BUG-0579 `/in-scope` endpoint, and the `Executables` tile showed the team-wide `scripts_count` instead of the in-scope scripts + testcases + virtuals sum (the G11 contract).

## Root cause

Two gaps, both UI:

1. **No in-scope section.** The `ProjectDetail` page never called `GET /server/projects/<id>/in-scope`. The aggregator returned a full payload that nothing consumed.
2. **Tiles didn't reflect in-scope totals.** The "Scripts" tile value was the legacy `tiles.scripts_count` (team-wide), not the in-scope total. The "Devices" tile showed online / offline / unknown — the in-scope count and total was hidden.

## Fix

A new `frontend/src/components/projects/ProjectInScope.tsx` component + a small wiring change in `ProjectDetail.tsx`. No backend changes (the API was already in main via BUG-0579).

### Component: ProjectInScope

Renders three groups per the v3 mockup (`docs/tasks/TASK-101-project-page-mockup-v3.html`):

- **Devices (left column)** — every device whose `device_flags.flags` intersects the project's tag_names, grouped by `host_name`. The per-host header reads `host · N`. Per-item rows show `host/device_id`, an online/idle dot, `X runs · Y% pass`, and a `×` button that calls `DELETE /server/projects/<id>/link` (TODO: device linkage goes through the device flag editor, so the `×` is a no-op stub for now — the row hides optimistically and `onChanged()` triggers a refetch).
- **Executables (right column)** — flat peer list of scripts + testcases + virtual scripts. Each row has a type chip (`script` / `testcase` / `virtual`) on the left, the name in the middle, runs + pass on the right, and a `×` button that calls the DELETE link route. The user's "v3 fix" complaint is honored: scripts, testcases, and virtuals sit at peer height, not nested.
- **Campaigns (separate full-width band below)** — campaigns sit at a different concept level (orchestrators, not executables), so they get their own section. Each row shows name + schedule on the left, a pass-rate bar + `X% pass · Y runs` on the right, and a `×` button.

Optimistic UI: the `×` button hides the row immediately; on error the row reappears. A `pending` state disables all `×` buttons while a request is in flight to prevent double-clicks.

### ProjectDetail.tsx wiring

- New `useQuery` for `fetchProjectInScope(id, 30)` with the same 30 s `staleTime` as the overview. The two queries agree on "what's in scope" without one racing the other.
- The `Executables` tile value is now the in-scope `totals.executables.total` when the new query has answered; the tile's extra line reads `X scripts · Y testcases · Z virtual` (the G11 sum contract). The legacy `tiles.scripts_count` is the fallback while the in-scope query is still loading or has errored.
- The `Devices` tile value is the in-scope `totals.devices` count; the sub-text reads `in scope · of N total` instead of the old `X online · Y offline · Z unknown` once the new query has answered.
- The `<ProjectInScope />` component renders inline, between the stat tiles and the "Last 10 failures" paper.

### i18n

13 new keys (en) with fr + de translations: `Executables`, `In scope`, `+ add device`, `+ add campaign`, `+ add script / testcase / virtual`, `Remove from project`, `Loading in-scope artefacts…`, `No executables in scope yet.`, `No devices in scope yet. Add a device flag that matches this project's tag.`, `click an item to open · × to remove`, `— group runs across many executables, different concept`, `in scope`, `total`. Reused: `Devices`, `Campaigns`, `scripts`, `testcases`, `virtual`, `pass`, `runs`, `of`.

`i18n-check --quiet` reports 0 errors; `tsc --noEmit -p .` exits 0; `eslint --quiet` exits 0; `ui-check` clean.

## Files

- `frontend/src/components/projects/ProjectInScope.tsx` (new, ~470 lines)
- `frontend/src/pages/ProjectDetail.tsx` (1 import, 1 in-scope query, tile updates, 1 component render)
- `frontend/src/i18n/locales/fr.json` + `de.json` (13 new keys × 2 locales)
- `docs/release_note/README.md` (1 new Features entry)

## Verification

- tsc / i18n-check / eslint / ui-check green at merge.
- The `/projects/<id>` page now reads `/in-scope` in parallel with `/overview` and renders a populated 3-section in-scope block (devices by host, executables as peer list, campaigns as a band) once both queries resolve.
- A `×` click on a script / testcase / virtual / campaign fires `DELETE /server/projects/<id>/link`, hides the row optimistically, and refetches; on error the row reappears.
- The 6-tile row now carries in-scope totals where they exist: `Executables` is the in-scope scripts+testcases+virtuals count, `Devices` is the in-scope device count, both with a `of N total` sub-line. The "team-wide online/offline/unknown" copy is now a fallback that surfaces only while the in-scope query is loading.
- "Add device" / "add campaign" / "add script / testcase / virtual" buttons are present in the section chrome but the click handlers are no-op stubs — the device tag editor and the script picker are separate flows. Follow-on: route these to the existing flows (BFF-0581 is the planned follow-on).

## What's not in this slice (v2)

- **Per-item token counts.** Still a v2 enhancement; today the per-row stats are runs + pass only.
- **Add-device flow.** The component shows the button; clicking it is a no-op. The actual device tag editor (`PUT /server/device-flags/<host>/<device>`) lives in a separate page today. A small follow-on can route to it with the project's tag pre-filled.
- **Add-executable / add-campaign pickers.** Same shape — the BUG-0579 `POST /link` endpoint takes `{type, id}` and needs a picker. The script / testcase / virtual selectors the user is already familiar with from Run Tests / Build Campaigns are the natural place to add a "link to project" toggle.
- **Tag-by-name editor on the project page.** The BUG-0579 `POST/DELETE /tags/names` endpoints are live; the UI tag chip on the project page header is still read-only. A small `+ add user tag` + chip-`×` wiring on the existing header chip row would close the loop.
## Visual reference

The wireframe this slice was built from is `TASK-101 v2` (manual in-scope,
per-item stats):
[`docs/tasks/TASK-101-project-page-mockup-v2.html`](../tasks/TASK-101-project-page-mockup-v2.html)
and the final, implementation-bound design `TASK-101 v3`:
[`docs/tasks/TASK-101-project-page-mockup-v3.html`](../tasks/TASK-101-project-page-mockup-v3.html).
The v3 mockup differs from v2 in two important ways: campaigns are pulled
out of the "executables" column and rendered in their own full-width band
because campaigns orchestrate executables rather than execute themselves,
and executables are rendered as a flat peer list of scripts + testcases +
virtuals (no nesting). The implementation in
`frontend/src/components/projects/ProjectInScope.tsx` matches v3 exactly.

The follow-on that wires the no-op stub buttons (`+ add` / `×`) — the dialog
components `AddDeviceDialog`, `AddExecutableDialog`, and `ProjectTagsEditor` —
is [BUG-0608 — project page v2 add/remove wired](BUG-0608-2026-10-18-project-page-v2-add-remove-wired.md),
which closes the "follow-on" paragraph above.
