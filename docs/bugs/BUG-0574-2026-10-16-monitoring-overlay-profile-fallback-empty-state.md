---
bug_id: BUG-0574
title: monitoring overlay — ProfileOverlay should fall back to the device's configured profile, not the tv_app default
summary: A device configured for `counting_cars` (or any non-tv_app profile) rendered the tv_app default overlay (FPS in/out, Blackscreen, Freeze, Macroblocks, Audio) instead of the profile-specific ProfileOverlay, because the overlay's branch condition only matched when the JSON's `profile` field was set — which is not the case on a cold monitor, a stuck service, or a model that's still loading. Fixed by also triggering on the device's `monitor_profiles[device_id]` (the value the operator picked in device settings), passing it to ProfileOverlay as a title fallback, and adding a one-line empty-state hint so the user can tell "monitor down" from "monitor running but profile analyzer hasn't run yet".
tags: [frontend, monitoring, profile, overlay, fallback]
keywords: [ProfileOverlay, MonitoringOverlay, effectiveProfile, monitor_profiles, profileName, empty_state, BUG-0574]
created: 2026-10-16
---

# BUG-0574

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0574                                                     |
| Reported  | 2026-10-16                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Low                                                          |
| Area      | frontend / monitoring                                        |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

## Symptom

Open a device configured for the `counting_cars` monitor profile in the rec
stream modal. The bottom-left overlay shows the **tv_app default view** even
though the device's monitor profile is `counting_cars`:

```
Profile: counting_cars
FPS: in — · out 10
Blackscreen: No
Freeze: No
Macroblocks: No
Audio: No
```

The profile name appears (because it comes from the `profileName` prop, which
reads `host.system_stats.monitor_profiles[device_id]`), but the panel below it
is the tv_app view: generic capture-quality metrics with no car counter, no
boxes, no KPIs, no profile headline. The `counting_cars` profile is supposed
to render through `ProfileOverlay` (UiOverlay or GenericOverlay), which
shows the configured `ui` block — counters, headline, "last checked" focus
panel — or, when no `ui` is set, the boxes / events / KPIs view. None of
that ever appears.

Two related symptoms on the same overlay:

- **`fps in` shows `—`** because `useMonitoring` only computes the input FPS
  after two captures land ≥400 ms apart. On a stuck monitor (no captures
  written) it stays null indefinitely. The operator has no way to tell
  "monitor not running" from "monitor running, but the scene is static".
- **No "monitor down" or "no data yet" hint** anywhere in the panel; the
  operator just sees an empty list of `0` events / `0` KPIs / `0` objects.

## Root cause

`frontend/src/components/monitoring/MonitoringOverlay.tsx:113` (pre-fix):

```ts
if (analysis?.profile && analysis.profile !== 'tv_app') {
  return <ProfileOverlay ... />;
}
```

`analysis.profile` is the `profile` field that `vpt-monitor-img` writes into
the latest `*.json` next to each `capture_*.jpg`. The condition requires it
to be non-empty. On a cold start, a stalled monitor, a model that's still
loading, or a vpt-monitor-img that hasn't yet stamped the JSON, this field
is `undefined` and the overlay falls through to the tv_app default branch,
which only knows how to show generic capture-quality metrics.

`monitor_profiles[device_id]` is the **configured** profile (the value the
operator picked in device settings). It is set as soon as the device is
registered, well before the monitor produces its first frame, so it is the
correct fallback to gate the conditional on.

## Fix

### `MonitoringOverlay.tsx`

- Add `effectiveProfile = analysis?.profile || profileName` and gate the
  ProfileOverlay branch on it. A `counting_cars` device now lands in
  `ProfileOverlay` from the moment the modal opens, even before the first
  monitor frame arrives.
- When `analysis` itself is null (the monitor hasn't written a JSON yet),
  synthesise a minimal placeholder with `profile: effectiveProfile` so
  ProfileOverlay has a non-null `analysis` to render. `ProfileOverlay`'s
  GenericOverlay already handles `observations: undefined` via `?? []`
  defaults, so the placeholder is enough.
- Pass `profileName` to `ProfileOverlay` so the panel title can fall back to
  the device's configured profile.
- Replace the stale `shownProfile` reference in the tv_app branch with
  `effectiveProfile` (the default branch now only runs when no profile is
  configured at all).

### `ProfileOverlay.tsx` (GenericOverlay)

- Accept `profileName` via `ProfileOverlayProps`.
- Title becomes `analysis.profile || profileName` so a cold `counting_cars`
  device still shows the right name, not a blank `Profile: —`.
- Compute `monitorIdle = observations.length === 0 && events.length === 0
  && kpis.length === 0` and render a one-line hint:
  - `fpsOut == null || fpsOut === 0` → **"No data yet — check vpt-monitor-img on the host"** (service down / no captures)
  - `fpsOut > 0` → **"Monitor running, profile analyzer has not produced data yet"** (model still loading, scene not relevant, etc.)

The hint is opt-in by being `monitorIdle`; an idle device whose profile
isn't doing anything is the rare case, and an active device with cars
flowing through the counters is the common case where the hint would only
add noise.

## Verification

- `vite build` ✓
- `tsc --noEmit` clean on the changed files (the one remaining error in
  `src/config/navItems.tsx` is pre-existing on `main` and unrelated).
- `eslint` clean on `MonitoringOverlay.tsx` and `ProfileOverlay.tsx`.
- Manual: open a `counting_cars` device in the rec stream modal. The
  bottom-left overlay should switch to the ProfileOverlay panel even on a
  fresh session, with the configured profile name in the title. When the
  monitor has produced nothing yet, the empty-state hint explains what to
  check.
- Manual regression: a `tv_app` device still shows the tv_app default
  panel (no ProfileOverlay).
