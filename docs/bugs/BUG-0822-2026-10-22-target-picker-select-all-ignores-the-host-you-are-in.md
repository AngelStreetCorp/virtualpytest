# BUG-0822 — The target picker's "Select all" ignores the host you are looking at, and clicking a host selects nothing

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0822                                                     |
| Reported  | 2026-10-22                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium — a selection control can silently widen to all 112 devices |
| Area      | frontend                                                     |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

Reported on `/device-control` (the Targets popover of the device filter bar).

- **Page / route:** /device-control, also /dashboard (Hosts and devices) and /rec — every page that
  renders `DeviceFilterBar`.
- **Viewport / theme:** desktop, dark

Steps to reproduce:

1. Open the **Targets** dropdown (the control reading "45 targets").
2. Click **vpt-mf1** in the host rail on the left. The panel shows that host's devices.
3. Click **Select all**.

**Expected:** the six devices of `vpt-mf1` are selected — "select all" means "everything in front of
me".

**Actual:** all 112 targets of the whole rack are selected. The rail still shows `vpt-mf1 0/6` while
the closed control jumps to "112 targets", and `Clear` then has to undo 112 rows instead of 6. The
same mismatch shows the other way round: inside a host the panel header checkbox takes the whole
host while **Select all** takes the whole rack.

Second half of the report: there is **no way to select a host from the rail**. Clicking `vpt-mf1`
only navigates (it showed its devices), so the only way to select a host is to open it and use the
panel header checkbox — while the rail row, which reads as a selectable item and carries a `3/3`
count, does nothing. Clicking the same row again does nothing either, so the control has no
"second click" step and the interaction cannot be learned from it.

Evidence: owner report with a screenshot of the popover open on `vpt-pi1` with the search narrowed
to `vpt` (rail: `All hosts 45/112`, `vpt-mf1 6/6`, `vpt-pi1 3/3`), 2026-10-22.

## Root cause

`frontend/src/components/common/TargetDropdown.tsx` held **two different ideas of "everything"** and
neither of them was "what the panel is showing":

1. **Select all / Clear were scoped to the search, not to the active host.** They were built on
   `visibleTargetOptions` (every option the search box leaves on screen) instead of on the active
   rail row. So clicking into `vpt-mf1` did not narrow them, and "Select all" meant the whole rack
   no matter which host the operator was reading.
2. **The rail row was navigation-only.** `onClick={() => setActiveHost(g.host)}` — and the sibling
   controls already acted on the host's *whole* target list: the panel header checkbox
   (`handleToggleHost(shownHost.targets)`) and the rail badge (`selectedCount / targets.length`).
   So the popover also contradicted itself: the badge and the header checkbox counted the host,
   "Select all" counted the search, and the rail row counted nothing.

The two lists that had to agree were computed independently and could not drift-check each other:
`hostGroups[].targets` (per host, whole rack) and `visibleTargetOptions` (the search intersection).

A second, quieter defect: `shownHost` was `hostGroups.find((g) => g.host === activeHost) ?? null`
while the rail row computed `active` with a *second*, differently-shaped predicate
(`hostGroups.some(...) ? activeHost : null`). When a search filtered the active host out, the two
disagreed about which row was highlighted.

## Fix

Two levels, and each one sits where it can be read: **the bar under the search box always means the
whole list; the host's own pair sits on the host's panel header, next to the list it applies to.**

- **The bar (always the whole rack).** "Select all" takes every target, "Clear" drops every target —
  whatever host is open, whatever the search shows. No context, no exception. `Select all` greys out
  when everything is selected, `Clear` when nothing is.
- **The host header (always this host).** When a host is open, its header row carries its own
  **Select all** / **Clear all**, scoped to that host: `Select all` adds the host's devices to the
  selection, `Clear all` removes only that host and leaves the others. Each greys out when it has
  nothing to do. `Select all` / `Clear all` already existed in `fr.json` and `de.json`; the host
  label on the row says which host they belong to.
- **The rail click cycles** in three steps: **1st click shows that host's devices** (navigation only,
  the selection is untouched), **2nd selects all of them**, **3rd unselects them all**. One click
  never both moves the panel and rewrites the selection the operator was reading. Switching hosts
  restarts the cycle at "show"; `All hosts` cycles over the whole list.
- `activeHostKey` is the single definition of the active row ("All hosts" owns the fallback when a
  search filters the active host out), so the rail highlight and the panel can no longer disagree —
  the old code computed `shownHost` and the highlight with two different predicates.
- `multiple={false}` pickers (AgentChat, the navigation editor) keep navigation-only rail clicks and
  get no host pair: a cycle over a one-target selection would be meaningless there.
- The rail row's `title` reads `vpt-mf1 · 3/6` instead of the bare host name, so the count is visible
  before the click.

### First attempt, revised the same day

The first pass made the bar itself context-sensitive — "Select all" meant the active host's devices —
in the name of one coherent rule. Deployed and reviewed on the live page, the owner rejected it as
too hard to reason about ("it is too hard to understand: keep select all to select everything, clear
to clear everything"). A control whose reach changes with a hidden context is the harder problem,
not the solved one. The revision keeps the absolute bar and moves the scoped pair onto the host
header, so the scope of every control is visible from where the control is.

## Verification

`tests/frontend/TargetDropdown.test.tsx` — 15 tests. 6 of them fail against the previous revision
and all 15 pass against this one (checked by reverting the component and re-running).

```
cd frontend && npx vitest run --config ../tests/frontend/vitest.config.ts TargetDropdown
```

Covered: the bar takes/drops **every** target even with a host open; the host pair is scoped to that
host and keeps the other hosts; the labels never collide (`Clear` in the bar, `Clear all` on the host
header); the pair appears only with a host open in multi mode; each button greys out when it has
nothing left to do; and the rail cycle — first click selects nothing, second selects the host, third
clears it, a partial host completes, switching hosts restarts the cycle, single mode is
navigation-only.

End-to-end, on the deployed frontend:

1. Open `/device-control`, open the Targets popover, click **vpt-mf1** → its devices appear, the
   closed control still reads the old selection (nothing selected by the click).
2. Click **vpt-mf1** again → the six devices are selected, the rail badge reads `vpt-mf1 6/6`.
3. Click **vpt-mf1** a third time → nothing selected, badge `0/6`.
4. With **vpt-mf1** open, the bar's **Select all** → **all 112** targets, whatever host is open.
5. With **vpt-mf1** open, the host header's **Clear all** → vpt-mf1's six go, the other hosts stay.
6. Click **All hosts** → the host header pair is gone; the bar is the only pair, and it is absolute.

Note: the component test moved from `frontend/src/components/common/TargetDropdown.test.tsx` to
`tests/frontend/TargetDropdown.test.tsx`. The component-test CI job only collects `tests/frontend/**`
and `features/*/**`, so the file beside the component never ran in CI.