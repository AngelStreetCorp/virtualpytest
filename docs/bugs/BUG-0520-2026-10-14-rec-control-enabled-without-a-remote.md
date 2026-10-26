# BUG-0520 — Control stays available on a device with no remote configured, and taking it locks the device behind a dead panel

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0520                                                     |
| Reported  | 2026-10-14                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Low                                                          |
| Area      | frontend (REC stream modal)                                  |
| Fixed in  | build 90145 |
| Commit    | `TBD`                                                        |

---

## Symptom

On a device whose host registered no remote controller (no `DEVICE{i}_IR_PATH` /
`DEVICE{i}_IR_SERIAL`, or a device model with no remote capability), the **Control**
button in the REC stream modal was still enabled and read `Control`. Clicking it took
the device lock, auto-opened the remote panel, and the user landed on the panel's
disabled empty state — "No remote configured" plus the "set DEVICE*_IR_PATH (lirc) or
DEVICE*_IR_SERIAL (USB IR Toy)" hint — with nothing pressable. The lock was still held
until released.

## Root cause

The take-control entry point was never gated on a remote being configured.
`RemotePanel` already detected the condition and said so in its own empty state, and
named the missing upstream gate in a comment next to that check:

> No remote controller configured for this device: render a clear disabled panel with
> the reason. **The take-control entry point should also be disabled upstream (gated on
> hasAnyRemote)** so users do not reach this state via the UI; this is the last-line
> visual.
> — `frontend/src/components/controller/remote/RemotePanel.tsx` (`hasAnyRemote`)

`hasAnyRemote` existed only as a local IIFE inside `RemotePanel`'s render. The header
that renders the Control button (`RecStreamModalHeader`) never asked the question, so
the modal offered an action whose only possible outcome was a dead panel.

The naive fix — "disable Control when the device has no remote" — is wrong on its own.
Control exists to drive the panel that opens with it: `useRecModalModes` opens the **Web**
panel for a desktop and the **Remote** panel for everything else. A `host_vnc` desktop is
driven over VNC (mouse/keyboard, `DesktopPanel` / `WebPanel`) and legitimately publishes
`device_capabilities.remote === null`, because `shared/src/lib/models/device.py` only
fills the `remote` slot from instantiated remote controllers. Gating on a remote alone
would have disabled Control on every VNC desktop on the platform.

## Fix

- `frontend/src/utils/remoteProfileUtils.ts` — new `hasRemoteConfigured(device)`, the
  single source of truth, mirroring the `hasAnyRemote` logic that was inline in
  `RemotePanel` so the entry point and the panel cannot drift. Handles both wire shapes
  of `device_capabilities.remote` (a string for one controller, a **list** for several —
  see `device.py`, which assigns the list form above one implementation and also falls
  back to the theoretical list) and counts the `switch` slot as a remote, so
  `nintendo_switch` and any future switch-driven device (`bluetooth_procon`) keep their
  control.
- `frontend/src/hooks/rec/useRecStreamLayout.ts` — `useRecDeviceChecks` now returns
  `canTakeControl = isDesktopDevice || hasRemoteConfigured(device)`. The desktop
  exemption is the fix for the regression above: a remote is required exactly when the
  panel control opens is a `RemotePanel`.
- `frontend/src/components/rec/RecHostStreamModal.tsx` — passes `canTakeControl` to the
  header, and guards the action itself (`handleToggleControl`) so a click landing on a
  stale render cannot lock the device either.
- `frontend/src/components/rec/RecStreamModalHeader.tsx` — new required `canTakeControl`
  prop; the Control button is disabled and its tooltip reads "No remote configured for
  this device" instead of "Control". Required rather than defaulted so a future caller
  has to decide instead of silently inheriting an enabled button.

Unchanged: every device that does have a remote, every `host_vnc` desktop, the release
side of the button, and `RemotePanel`'s last-line empty state (still reached if a device
loses its remote while control is held).

## Verification

- `tsc --noEmit -p tsconfig.json` — clean.
- `eslint` on all four changed files — clean. `node scripts/ui-check.mjs` (the lint
  gate's UI half) — clean. Note that this gate does **not** catch this class of change:
  it passes on a page with no card at all, so it is not evidence that the button behaves.
- Server contract confirmed by reading `shared/src/lib/models/device.py`: the `remote`
  slot is a string, a list, or `None`, and `switch` is set from the theoretical
  capabilities — the three shapes the helper handles.
- **Not verified in a browser.** The disabled state and the tooltip were not exercised
  against a live server. To confirm end-to-end: open the stream modal on a device with
  no remote configured — Control is greyed and its tooltip reads "No remote configured
  for this device"; on a device with a working remote, and on a `host_vnc` desktop,
  Control is unchanged.
- No test runner covers these files (no existing test references
  `useRecDeviceChecks` or `remoteProfileUtils`); the checks above are static.
