# BUG-0857 — The "N in warning" badge counted hosts it could not name, and clicking it did nothing

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0857                                                     |
| Reported  | 2026-10-23                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Low                                                          |
| Area      | frontend                                                     |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

On the dashboard, the amber badge read **"2 in warning"** next to the "Monitoring problem" chip
while the screen showed two servers and one host on an older build. The number could not be
reconciled with the cards below it:

- the badge counted **hosts**, but the tooltip spoke about **version mismatch** for every one of
  them — a host that was amber for a full disk or a degraded backend was announced as a version
  mismatch;
- the tooltip never named the hosts, so there was no way to tell which two they were;
- the chip was not clickable at all, so there was no way to narrow the page down to the hosts it
  was counting (the red "N in error" chip next to it filters, this one did nothing).

## Root cause

`frontend/src/components/dashboard/HostsDevicesView.tsx` computed `warningHostCount` with a bare
`hostHasWarning()` loop and rendered it as a static `<Chip>` with a hardcoded tooltip:

```tsx
title={tn(warningHostCount,
  'Version mismatch: {count} host runs a different build than the server. Nothing is broken.',
  'Version mismatch: {count} hosts run a different build than the server. Nothing is broken.')}
```

`hostHasWarning()` (in `frontend/src/components/dashboard/hostHealth.ts`) is amber for **three**
different reasons — a build that differs from the server's, a backend that reports the host
degraded, and a disk over the 85 % line — so the tooltip described one of them for all of them.
The chip had no `onClick`, while the red chip beside it toggled the `errorOnly` filter.

## Fix

- `hostHealth.ts` gains `hostWarningReasons(host, serverVersion)`: the exact reasons behind the
  amber verdict (version / degraded / disk), empty for a healthy host and for a host in error
  (red outranks amber).
- The dashboard builds the amber host list from that helper, so the badge counts and the tooltip
  describe the same hosts and the same reasons.
- The amber chip is now **clickable**: it toggles a "warnings only" filter that narrows the page
  to the amber hosts, exactly like the red chip narrows it to the hosts in error. The two filters
  are exclusive (a host is red or amber, never both) and the amber one drops itself when the last
  amber host recovers, so it can never leave the page empty with no way back.
- The tooltip now names every amber host, its server and the reason it is amber
  ("<host> (<server>) — runs build main-2026.10.22-89574, server runs
  main-2026.10.23-89703"), and the mobile header gets the same amber chip.

## Verification

- `frontend/src/components/dashboard/hostHealth.test.ts` covers the new helper: a version
  mismatch, a degraded backend, a full disk, a host amber for two reasons, a healthy host, a host
  in error (no amber reasons) and a host that reports no version at all.
- On the dashboard: open the amber badge's tooltip — it lists the hosts it counts; click it — the
  page keeps only those hosts; click it again — every host is back.
