# BUG-0824 — Two Tello video feeds on one host fight over UDP port 11111

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0824                                                     |
| Reported  | 2026-10-22                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | backend_host (run_ffmpeg.sh)                                 |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

With two Tellos on vpt-pi4 (one radio each, `DEVICE3_VIDEO=udp://<drone-1 host address>:11111`,
`DEVICE4_VIDEO=udp://<drone-2 host address>:11111`) only one drone's stream starts. `ss -lun` shows a single
ffmpeg on `0.0.0.0:11111`; the other ffmpeg exits at once.

## Root cause

ffmpeg's `udp://` input binds the wildcard address and ignores the host in the URL, so the second
ffmpeg gets "Address already in use". The per-drone source address is lost.

## Fix

`backend_host/scripts/run_ffmpeg.sh`: a `udp://<ip>:<port>` source gets `?localaddr=<ip>` (unless the
ip is 0.0.0.0), which makes ffmpeg bind that address only. Verified on vpt-pi4: two listeners on
each drone address on one test port coexist.

## Verification

Both ffmpegs listen on their own address and both drone tiles show video after a `vpt-stream` restart.
