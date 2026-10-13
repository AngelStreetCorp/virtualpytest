# BUG-0493 — One alert in five was created without a frame

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0493                                                     |
| Reported  | 2026-10-12                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | backend_host / incident manager                              |
| Fixed in  | Unreleased                                                   |
| Commit    | `10de3cb4c`                                                  |

---

## Symptom

1,399 of 6,122 alerts over 3 days (lab DB, 2026-10-12) had no `metadata.r2_images`. Nobody could see what the
device showed, and alert triage could not judge them: the vision route (MiniMax VLM) refuses a call without an image
(BUG-0492). By host: labox-web 425 of 979 freezes, vpt-pi1 263, labox-backend 165 of 165, vpt-mf1 156 freezes and
70 audio_loss, vpt-pi4 137 audio_loss, vpt-nipogi 101 of 101.

## Root cause

`IncidentManager.process_detection` (`backend_host/scripts/incident_manager.py`) uploads the start frame right before
it creates the alert, but it created the alert even when nothing was uploaded:

- **Freeze with no thumbnail on disk.** The freeze branch uploaded only `last_3_thumbnails`. On labox-web the
  detector often finds no `_thumbnail.jpg` for the compared frames ("Added last_3_thumbnails to metadata: 0 items"),
  while the 3 capture frames exist. Nothing was uploaded and nothing was logged.
- **Upload failure or timeout.** `_upload_with_timeout` returned None and the alert went out without an image
  ("proceeding without image").

On vpt-nipogi every upload fails: its storage endpoint is `http://127.0.0.1:9000`, which `vpt-tunnel.service`
forwarded to MinIO (192.168.0.101:9000). That unit is now `vpt-tunnel.service.bak-20261009` and nothing listens on
port 9000. That is a host setup issue, not fixed by this change.

## Fix

- The freeze branch uploads the capture frames when no thumbnail exists. The audio_loss / blackscreen fallback to
  the current frame also falls back to the capture frames.
- No frame uploaded means no alert. The incident stays pending, the warning
  `<type> has no uploaded frame - alert NOT created, retry in 60s` is logged, and the upload is retried after
  `CREATE_RETRY_BACKOFF` (60 s, the BUG-0109 back-off). If the issue clears first, no alert is created.
- Test: `tests/backend_host/test_alert_needs_frame.py`.

A host that cannot upload (vpt-nipogi today) now creates no alerts and logs that warning once a minute per pending
issue, until its storage works again.

## Verification

After the host deploy, new alerts without a frame should be 0:

```sql
SELECT host_name, count(*) FILTER (WHERE metadata->'r2_images' IS NULL) no_frame, count(*)
FROM alerts WHERE created_at > now() - interval '1 hour' GROUP BY 1;
```
