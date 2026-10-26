# BUG-0904 — An aborted or cancelled campaign is shown as failed in the results table

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0904                                                     |
| Reported  | 2026-10-25                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | frontend (test reports — campaign results table)             |
| Fixed in  | build 90145 |
| Commit    | see branch `fix/campaign-aborted-status`                     |

---

## Symptom

In the campaign results table of the Test Reports page, the status cell of a campaign that
never reached a verdict was painted as a red **Fail**. A campaign whose `status` is `aborted`
or `cancelled` was reported as a test failure, next to campaigns whose checks really did fail —
and the cell said nothing more than "Fail", so the two were indistinguishable.

The campaigns affected are the ones the platform stops rather than the ones that break: a run
whose `error_message` reads `Execution aborted - scheduler restarted` (the host scheduler
restarted mid-campaign) and a night that never started because the device was busy (written as
`status='cancelled'` with the `skipped` flag, see BUG-0898). Neither is a failing check: the
checks never produced a verdict.

## Root cause

`frontend/src/pages/TestReports.tsx`, campaign results table, status cell. The cell rendered
three states from two signals:

```
result.status === 'running'  → running icon
result.success               → pass icon
otherwise                    → fail icon (red)
```

`campaign_executions.status` accepts six values (`pending`, `running`, `completed`, `failed`,
`cancelled`, `aborted` — the CHECK constraint in `20260918_fix_execution_integrity.sql`), and both
`cancelled` and `aborted` are written with `success=false`. The cell never read the status
except to test for `running`, so both terminal-not-failed states fell through to the last
branch and were drawn in the red reserved for "this failed".

## Fix

`frontend/src/pages/TestReports.tsx` only — one branch added to the same cell, before the
`success` test:

- `status === 'aborted'` → the `Block` icon in the muted (`color="disabled"`) grey, tooltip
  **Aborted**;
- `status === 'cancelled'` → the same icon, tooltip **Cancelled**.

Everything else in the cell is untouched: a running campaign still shows the running icon, a
successful one still shows the pass icon, and a campaign that really failed still shows the red
fail icon. The icon is the one the platform already uses for a stopped execution
(`Block as AbortedIcon`, as in `ExecutionHistoryTable.tsx`); only its colour is neutral grey
here, because in this table it must not read as a failure.

## Verification

`frontend` typecheck (`tsc --noEmit`) and lint (`eslint src/pages/TestReports.tsx`) pass.
Behaviour of the cell, in order of the branch chain: `running` → running icon; `aborted` →
grey Block, tooltip "Aborted"; `cancelled` → grey Block, tooltip "Cancelled"; `success` →
pass icon; anything else → red fail icon.
