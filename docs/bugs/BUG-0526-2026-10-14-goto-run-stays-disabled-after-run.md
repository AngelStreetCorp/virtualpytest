# BUG-0526 — Go to node: Run stays disabled after a run ends, failure message unreadable

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                  |
|-----------|------------------------|
| ID        | BUG-0526               |
| Reported  | 2026-10-14             |
| Status    | Fixed (pending deploy) |
| Severity  | Low                    |
| Area      | frontend               |
| Fixed in  | build 90145 |
| Commit    | see git log            |

---

## Symptom

In Take Control, Go to node: after a run ended (passed or failed) the **Run** button stayed grey, so the
operator could not re-run. A failure message showed red text on a red filled box, in a large font.

## Root cause

`Navigation_NodeGotoPanel.tsx` disabled Run when `navigationError !== null` (set by every failed run and only
cleared by starting a run, which Run itself blocked) and, after a pass, when the device was at the
destination. Run was therefore dead until the panel was reopened.

## Fix

Run stays enabled once a result (error or success message) exists; starting a run clears the previous
message, error and report links (`useNode.executeNavigation`). The embedded view renders status as a compact
outlined Alert (0.75rem, theme colours) with small caption report links, and the whole embedded panel is
scaled to about 70 percent.
