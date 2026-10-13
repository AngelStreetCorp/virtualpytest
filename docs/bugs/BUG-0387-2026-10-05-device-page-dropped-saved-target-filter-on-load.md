# BUG-0387 — Device page dropped a saved Target filter when the page loaded

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0387                                                     |
| Reported  | 2026-10-05                                                   |
| Status    | Closed                                                       |
| Severity  | Low                                                          |
| Area      | frontend                                                     |
| Fixed in  | Unreleased |

---

## Symptom

On the Device (Rec) page, a Target filter chosen earlier (kept in the browser as
`rec_filters_target`) was cleared on reload, so the page showed every device again instead of
the saved selection.

## Root cause

`frontend/src/pages/Rec.tsx` prunes saved filters that no longer match any device (so a filter
from another workspace does not hide everything). It skipped pruning while `isLoading`, but that
flag lied for one render: `HostManagerProvider` copies the server's hosts into `availableHosts`
in an effect, and reported `isLoading = serverLoading` only. When the server data was already
there (cached, or just arrived), the first render had `isLoading=false` with an empty host list,
`useRec` produced zero devices, and the prune removed every saved target as "unknown". The Flag
filter had the same exposure: tags load separately (`useDeviceFlags`) and were pruned before they
arrived.

## Fix

- `frontend/src/contexts/HostManagerProvider.tsx`: `isLoading` stays true while the server has
  hosts that have not been copied into `availableHosts` yet.
- `frontend/src/pages/Rec.tsx`: the Flag filter is pruned only after the device tags have loaded
  (`useDeviceFlags().isLoading`).

## Verification

- `cd frontend && ./node_modules/.bin/tsc --noEmit` passes.
- After deploy: on the Device page pick a Target, reload — the Target stays selected and the
  grid shows only that target. Switching to a workspace without that target still clears it.

### Live check (2026-10-05, node1)

Device page: Target filter set to "Phone slot 1 - host-clone-1" (`rec_filters_target` saved), page re-entered: the filter is still applied and only that device is shown.
