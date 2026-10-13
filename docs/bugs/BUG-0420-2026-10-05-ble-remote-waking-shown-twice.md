# BUG-0420 — BLE remote panel shows "Waking STB…" twice while waking

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0420                                                     |
| Reported  | 2026-10-05                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Low                                                          |
| Area      | frontend                                                     |
| Fixed in  | Unreleased                                                   |
| Commit    | TBD                                                          |

---

## Symptom

On the BLE remote panel, pressing Power to wake a sleeping STB showed the wake state three
times: the heading "Waking STB…" with the detail line "Sending ADV_DIRECT_IND to <MAC> …",
then in the action row a spinner labelled "Waking STB…" next to Re-pair, plus a disabled
"Waking…" Power button with its own spinner, then Logs. Two spinners and two "Waking" labels
in one row, which also pushed Logs onto a second line.

## Root cause

`renderActionScreen()` in `frontend/src/components/controller/remote/BluetoothRemote.tsx`
rendered an inline spinner + "Waking STB…" label whenever `isWaking` was true, on top of the
headline/subtext (`actionHeadline` / `actionSubtext`) and the Power button, which already
switches to a disabled "Waking…" with a spinner while `isWaking` is true.

## Fix

Removed the inline "Waking STB…" spinner label from the action row (and the `isAdvertising`
flag only it used). The status is stated once by the heading and detail line; the disabled
Power button carries the progress. Re-pair and Logs are unchanged. Wake and pair behaviour
(`coldWake`, `isWaking` in `useBluetoothRemote`) are untouched.

## Verification

Rendered the panel in its waking state in a local Vite harness with a mocked
`useBluetoothRemote` (`isWaking=true`, bond present, daemon up, STB disconnected): before,
the row read "⟳ Waking STB… · RE-PAIR · ⟳ WAKING…" with Logs wrapped below; after, it reads
"RE-PAIR · ⟳ WAKING… (disabled) · LOGS" under the single heading + detail line.
`tsc --noEmit` clean; `node scripts/i18n-check.mjs` 0 errors (the file is not in
`translated-files.txt`; the fix only removes a literal).
