# BUG-0503 — Dashboard kept a target filter from another server and showed "No hosts match"

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0503                                                     |
| Reported  | 2026-10-13                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Low                                                          |
| Area      | frontend (Dashboard filters)                                 |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

On the Dashboard with server **Awesomation** selected, the Targets filter still read
`Tello-F014A0 - …` — a device on another server — and the page showed only
"No hosts match the selected filters".

## Root cause

The target / model / tag picks are persisted in localStorage and shared by the Dashboard and
Device Control pages (`frontend/src/hooks/useDeviceFilters.ts`). The Dashboard cleared them only
when the server changed **while the Dashboard was mounted**. A server switched on another page,
or a pick restored from an earlier session, survived and filtered every host away. The Device
Control page (`Rec.tsx`) already dropped picks that no longer exist; the Dashboard did not.

## Fix

The pruning moved into a shared `usePruneDeviceFilters` hook in `useDeviceFilters.ts`, used by
both pages. The Dashboard runs it once the selected server's hosts are loaded, so a target, model
or tag that is not among the current options is removed from the selection.

## Verification

Pick a target on one server, switch servers from the Device page, open the Dashboard: the
filter reads "All Targets" and the hosts of the selected server are listed.
