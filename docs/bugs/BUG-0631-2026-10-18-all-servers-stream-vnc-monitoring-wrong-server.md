# BUG-0631: device tiles of other servers loop on 400 "Host not found" in 'All servers' mode

**Date:** 2026-10-18
**Severity:** medium — with 'All servers' selected, VNC / stream tiles of hosts owned by another server stayed on
"Loading stream..." and the browser kept re-requesting.

## What was happening

BUG-0625 routed Take Control to the server that owns the host, but the shared controller helper `postToHost`
(`useControllerApi.ts`) and the monitoring `latest-json` fetch (`useMonitoring.ts`) still posted to the selected
server. That server does not know the host, so `/server/av/getStreamUrl`, `/server/system/vnc-info` and
`/server/monitoring/latest-json` answered 400 "Host not found" and the tiles retried.

## What ships

`postToHost` and the `latest-json` fetch use `buildServerUrlForServer(host.server_url, …)` when the host carries
its owner `server_url`, else the selected server as before.
