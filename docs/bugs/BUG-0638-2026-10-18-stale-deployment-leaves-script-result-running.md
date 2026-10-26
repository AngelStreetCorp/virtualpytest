# BUG-0638 — A stale deployment left its script result without a verdict

- **Reported**: 2026-10-18
- **Visible to**: teams using recurring deployments whose host restarts or whose script is killed during report finalisation.

## Symptom

A script that had finished its device work could remain without `success` in
`script_results` while video extraction, report generation, or R2 uploads were
still running. If the host was killed during that tail, the deployment scheduler
could mark only `deployment_executions` as failed. The linked script result then
looked unfinished, and later scheduled fires treated the device as busy or
skipped it.

## Fix

The script executor records the verdict and execution time before the report
tail begins; the existing final update still adds report paths and metadata.
Both stale-execution cleanup paths now also mark the linked `script_results` row
failed, with the same completion timestamp and cleanup error.

No database migration is required.
