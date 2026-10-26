# BUG-0551 — Take Control / stream modal header shows only the device name, not "<device> - <host>"

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                              |
|-----------|------------------------------------|
| ID        | BUG-0551                           |
| Reported  | 2026-10-15                         |
| Status    | Fixed (pending deploy)             |
| Severity  | Low (cosmetic / consistency)       |
| Area      | frontend / `rec/` / modal header   |
| Fixed in  | build 90145 |

---

## Symptom

Opening Take Control on `stbv1+ - vpt-mf1` (or any non-VNC device) showed the modal's header as
`stbv1+ 🟢` — the device name only. The same device's preview tile underneath showed
`stbv1+ - vpt-mf1 · 🟢`. Two different titles for the same device, depending on whether the
preview or the modal was on top.

## Root cause

`frontend/src/components/rec/RecHostPreview.tsx` already builds a `displayName` (lines 475-479)
that handles three cases:

```ts
const displayName = device
  ? device.device_model === 'host_vnc'
    ? host.host_name
    : `${device.device_name} - ${host.host_name}`
  : host.host_name;
```

The modal header in `frontend/src/components/rec/RecStreamModalHeader.tsx` (lines 213-222)
was rendering the much simpler `(device?.device_name || host.host_name).replace(/_Host$/, '')`,
which dropped the host on every non-VNC device. Two render paths, two display strings, for the
same `host + device` pair.

## Fix

Mirrored the preview's `displayName` in `RecStreamModalHeader.tsx`: compute it once with the
same VNC vs non-VNC branching the preview uses, render it in the `DeviceInfoNameTooltip` and
in the visible `<Box>`, drop the `_Host$-suffix` strip (the preview never had it; this also
keeps the two paths textually aligned).

## Verification

- ESLint clean (`./node_modules/.bin/eslint src/components/rec/RecStreamModalHeader.tsx --max-warnings 0`).
- Visual: open any mobile/STB/host tile from the Device or Rec page, the modal header now
  reads `stbv1+ - vpt-mf1`, matching the preview tile underneath. VNC devices still show
  only the host name.
