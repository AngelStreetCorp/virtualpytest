# BUG-0044 — vpt smoke scripts fail on every run: host URL from the server has no scheme

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0044                                                     |
| Reported  | 2026-09-03                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium (platform self-test reports false failures)           |
| Area      | `test_scripts/vpt/smoke_device_control.py`, `smoke_video_stream.py` |
| Fixed in  | build 8713                                                   |
| Commit    | `8eedde984`                                                  |

---

## Symptom

Running the platform smoke scripts through the runner (first ever runs, host-clone-1,
2026-09-03 07:52 UTC) gave 3/5 passes. `smoke_device_control` and `smoke_video_stream` failed
every host-side check with

```
Invalid URL '/host/sample-app-backend/health': No scheme supplied. Perhaps you meant https:///host/sample-app-backend/health?
```

## Root cause

`/server/system/getAllHosts` publishes each host's `host_url` as a **browser-relative** path
(`/host/<name>`) that the reverse proxy resolves. Both scripts took that value verbatim and
called `requests.get(f"{host_url}/health")`, which `requests` rejects without a scheme.
`smoke_ui`, `smoke_heatmap` and `smoke_network_server` only talk to the server, so they were
unaffected.

## Fix

Both scripts prefix the server origin when `host_url` starts with `/`:

```python
host_url = host_info.get("host_url", "").rstrip("/")
if host_url.startswith("/"):
    host_url = server_url.rstrip("/") + host_url
```

The relative-stream-URL branch in `smoke_video_stream` already derived its base from
`host_url`, so it now resolves to `<server>/host/<name>/…` as intended.

Same commit family also gives every `smoke_*` script a `--userinterface virtualpytest_web`
default so runs are recorded under that interface and appear on the *VirtualPyTest Self-Test*
Grafana dashboard.

## Verification

- Failure reproduced from the R2 execution logs of both runs (`Invalid URL … No scheme
  supplied` on every host call).
- Fix compiled locally; not yet executed on a deployed host (hosts still run the pre-fix
  build). Re-run `vpt/smoke_device_control` and `vpt/smoke_video_stream` on host-clone-1 after
  the next deploy and check the Self-Test dashboard's per-script table.
