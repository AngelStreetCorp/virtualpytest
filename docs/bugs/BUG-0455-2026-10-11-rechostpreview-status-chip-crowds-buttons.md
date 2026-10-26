# BUG-0455 — RecHostPreview header can't fit Localize + AVQ when the status chip carries the "online" / "running" / "error" text

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                                                  |
|-----------|----------------------------------------------------------------------------------------|
| ID        | BUG-0455                                                                               |
| Reported  | 2026-10-11                                                                             |
| Status    | Fixed                                                                                  |
| Severity  | Low                                                                                    |
| Area      | frontend — `frontend/src/components/rec/DeviceStatusChip.tsx`                          |
| Fixed in  | build 90145 |
| Commit    | TBD                                                                                    |

---

## Symptom

On the device-control page (`virtualpytest.angelstreet.io/device-control`), the REC preview
card header overflows when the device has a `preferred_userinterface` (Localize icon) **and** an
AVQ feature link. The two icon buttons either collide with the trailing status `Chip`
(`online` / `running` / `error`) or push it off-card, depending on the device name length and the
multi-tag chip collapsing. Same problem on cards whose names are long enough to share the row.

## Root cause

`DeviceStatusChip` was a full MUI `Chip` showing the live status as text:

```tsx
<Chip label={isHostStuck ? 'error' : isRunning ? 'running' : host.status} />
```

That Chip is ~50–70 px wide on a card whose header row tries to hold, left-to-right: device
name (1fr) + flags chip + lock icon + checkbox + info icon + LocalizeButton + AVQ IconButton +
status chip. The status Chip never had a `flexShrink` lower than 0 nor a fixed width, so it
competed with the icons for the same 12–20 px the Localize/AVQ buttons needed.

The same status was already being rendered as a 10×10 coloured dot in `RecStreamModalHeader.tsx`
(lines 230–275), with the full text surfaced via the tooltip on hover — the grid chip just
wasn't mirroring that pattern.

## Fix

`frontend/src/components/rec/DeviceStatusChip.tsx` now renders the same 10×10 coloured dot
instead of a text chip:

- red (`P.error`) when a host service is `stuck`, OR host.status is `offline` / unknown
- blue (`#3a8cff`) while a deployment/script is driving the device
- green (`#2ecc71`) when `host.status === 'online'` and nothing else is wrong
- a thin theme-aware halo (`P.borderColor`) so the dot stays visible on both light and dark
  card surfaces
- tooltip on hover carries the full status text (`Online` / `Offline` / `Running — <name>` /
  `Error — host services stuck`, plus the stuck-service list when relevant) — matching the
  wording in `RecStreamModalHeader` exactly

The wrapper box keeps the same 24×20 footprint the old Chip used, so the card header geometry
is stable. `flexShrink: 0` so a long device name can ellipsize without collapsing the dot.

Localize and AVQ buttons are intentionally kept — removing them was the alternative discussed
with the user, and shrinking the chip is the better fix (it preserves the workflow and the dot
still tells you whether the host is alive at a glance).

## Verification

1. Build: `cd frontend && npx tsc --noEmit` (no errors).
2. Open `virtualpytest.angelstreet.io/device-control`, pick a host with at least one
   `host_*` device whose `preferred_userinterface` is set and the AVQ feature enabled (e.g.
   `stb4` on vpt-pi1). The header should now be: name | flags | lock | checkbox? | info |
   Localize | AVQ | **●** with a coloured dot at the right edge.
3. Hover the dot — tooltip shows e.g. `Online`, `Running — <script>`,
   `Error — host services stuck` plus the stuck-service list when relevant.
4. Open the stream modal for the same device — the toolbar dot at the left of the title is
   the same colour, with the same tooltip wording (no drift between grid and modal).
