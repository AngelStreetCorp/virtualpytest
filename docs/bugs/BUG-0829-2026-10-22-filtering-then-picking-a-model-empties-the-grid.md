# BUG-0829 — Filtering targets then picking a model empties the device grid

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0829                                                     |
| Reported  | 2026-10-22                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | frontend (`useDeviceFilters`, `DeviceFilterBar`, `Rec`, `HostsDevicesView`) |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

On `/device-control`, with 4 targets selected in the **Targets** dropdown, opening **More**
and picking a model (or a tag, or a profile) emptied the whole grid:

> No targets match the selected filters. Try adjusting your filter criteria.

The chosen value was a dead end — no device carried it *after* the target filter had
narrowed the list — yet it was offered as if it worked. The same trap exists on the
Dashboard ("No hosts match the selected filters"), which shares the same filters.

## Root cause

The grid is the **AND** of four axes — target, model, monitoring profile, tag — but every
option list was built from the **whole fleet**:

- `Rec.tsx` derived `targetOptions` / `uniqueDeviceModels` / `uniqueProfiles` / `uniqueFlags`
  from `avDevices`, before any filter ran;
- `HostsDevicesView.tsx` did the same from `selectedServerData`.

So an axis could offer a value that no *surviving* device had. Selecting it intersected two
sets with nothing in common and the grid went empty — with a filter chip set that explains
nothing, and no indication of which value was responsible.

The tag axis had a second variant of the same defect: with the default **AND** combinator,
picking tag `alpha` (on device A) removes device B, so a second tag `beta` (only on B)
became a dead end *one click later*. The option lists could not express that, because they
never re-read the surviving set.

## Fix

`reachableFilterOptions()` in `frontend/src/hooks/useDeviceFilters.ts` counts each axis over
the devices that **survive the current selection**, and `narrowFilterOptions()` applies the
result to a list while keeping every selected value visible.

The rule is one line:

> a value is on offer only while at least one surviving device carries it.

That makes the empty state unreachable by clicking. Pick anything offered and at least one
device is still there; the lists are recomputed after every change, so they track the user
down the narrowing path (select 2 Tellos, open **More**, and the STB model's tags are already
gone).

### Scope: Models / Profiles / Tags only

**Targets are deliberately not narrowed.** The target filter is a *union* — adding a target
can only widen the result, so it is never a dead end. Narrowing it would also have broken
[BUG-0822](BUG-0822-2026-10-22-target-picker-select-all-ignores-the-host-you-are-in.md), whose
rule is that the bar under the search box always means the whole list: "Select all" takes
EVERY target, "Clear" drops EVERY target. A control whose meaning shifts with context is the
thing that owner rejected there. `tests/frontend/DeviceFilterBar.reachability.test.tsx` locks
that contract down in both directions.

### Selected values stay visible

A device going offline must not make its own filter value unselectable, so a value already
selected is kept in the list even when nothing reachable carries it — otherwise the operator
is stranded on an empty grid with no way to clear it. Pruning of values that no longer exist
at all (`usePruneDeviceFilters`) still runs on the **unfiltered** lists, as do the Dashboard
deep links (`?device=`, `?host=`, `?favorites=1`).

### Both pages

The filters are persisted in `localStorage` and shared, so fixing only one page would leave
the same dead end on the other. `HostsDevicesView.tsx` gained a single
`matchesAttributeFilters` predicate used by both the host list and the reachability pool —
two copies of the AND would drift, and the drifted one would let the bar offer a combination
that empties the page.

## Verification

- `tests/frontend/useDeviceFilters.reachability.test.ts` — 13 cases on the rule, including
  the invariant "every offered value, added to the current selection, leaves a device",
  walked along the exact path from the report (targets → model → profile).
- `tests/frontend/DeviceFilterBar.reachability.test.tsx` — 10 cases on what the operator is
  actually offered (More popover, mobile inline selects, selected-but-unreachable values) plus
  the three BUG-0822 guards.
- Discriminating: with `DeviceFilterBar.tsx` stashed, 5 of the 10 component cases fail; the 5
  BUG-0822 guards pass in both states.
- `tsc --noEmit`, eslint on the four changed files, and the 59 tests covering Rec,
  DeviceControl, Dashboard, AgentDashboard, QuickfilterBadgeArea and TargetDropdown: green.