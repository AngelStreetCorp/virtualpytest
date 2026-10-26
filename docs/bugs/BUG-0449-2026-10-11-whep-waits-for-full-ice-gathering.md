# BUG-0449 — WEB (WebRTC) stream always falls back to HLS: the offer waits for ICE gathering that never ends

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0449                                                     |
| Reported  | 2026-10-11                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | frontend — `frontend/src/actions/webrtc/whepActions.ts`      |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

Choosing **WEB** in the rec modal's LOW / SD / HD / WEB selector logs
`[@hook:useWhepStream] WebRTC failed (timeout) — falling back to HLS` after 6 s and the
player goes back to HLS. MediaMTX on the host logs each attempt as
`session … closed: deadline exceeded while waiting connection` (TASK-79).

## Root cause

`openWhepSession` waited for `iceGatheringState === 'complete'` before POSTing the WHEP
offer. In Chrome on a machine with several interfaces (Tailscale, IPv6) gathering stayed in
`gathering` for more than 20 s, although the host and server-reflexive candidates were all
there after ~50 ms. The POST therefore went out after the 6 s `WHEP_CONNECT_TIMEOUT_MS`
had already fired, or never.

It was not the gateway: from an outside network, ICE binding
requests to the gateway public IP on UDP 8189 (vpt-pi3) and 8190 (vpt-pi1) got Binding Success
answers, and the iptables counter on vpt-pi3 showed them arriving.

## Fix

`waitForIceGathering` now resolves on `complete` **or** after `WHEP_ICE_GATHER_MAX_MS`
(1 s, in `frontend/src/constants/webrtcConstants.ts`), whichever comes first. The offer
carries the candidates gathered so far; MediaMTX learns any other browser address as
peer-reflexive from the connectivity checks.

## Verification

In the in-app browser on the Mac (outside the hosts' LAN), the same WHEP flow against
`https://<pi-server-host>/host/vpt-pi3/whep/capture1/whep`:

| Gather wait | Result |
|---|---|
| until `complete` (old) | still `gathering` after 20 s, no POST |
| capped at 1 s (new) | POST 201 at 1.4 s, ICE connected 1.6 s, video playing 2.5 s |
| capped at 1 s, answer filtered to the public candidate only | connected via the gateway public IP, UDP 8189, video playing 1.8 s, 1280×720, RTT 31 ms |
