# BUG-0158 — Backend Host stalls when starting with no configured devices

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0158                                                     |
| Reported  | 2026-09-23                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | backend_host startup                                         |
| Fixed in  | Unreleased                                                   |
| Commit    | `03dd66493b`                                                 |

---

## Symptom

On a host with no `DEVICE*_NAME` configuration and no host VNC capture configuration,
Backend Host startup stopped after `Creating new host instance`. Such a host should be
allowed to run with zero devices.

## Root cause

`app.py` detected the host IP before route registration, but `get_host()` called
`create_host_from_environment()`, which detected it a second time before its next startup
log. The duplicate network probe made empty-host startup appear stalled.

## Fix

Pass the already detected IP from application startup into `get_host()`, and retain the
existing fallback detection for other callers. Empty configuration now logs explicitly and
produces a host with zero devices.

## Verification

Start Backend Host with no `DEVICE*_NAME` variables and no `HOST_VIDEO_CAPTURE_PATH` or
`HOST_VNC_STREAM_PATH`. Startup should log that it created an empty host and continue to
serve health checks.
