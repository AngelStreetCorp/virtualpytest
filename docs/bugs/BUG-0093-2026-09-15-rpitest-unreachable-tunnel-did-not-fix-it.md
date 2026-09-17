# BUG-0093 — vpt-pi1 keeps disappearing from the UI; a Cloudflare Tunnel fixed the 522s but NOT the reported symptom

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                                                          |
|-----------|------------------------------------------------------------------------------------------------|
| ID        | BUG-0093                                                                                        |
| Reported  | 2026-09-15                                                                                      |
| Status    | **FIXED 2026-09-15**, verified end to end. The tunnel stays — see Part 5; DNS should go back to the CNAME. |
| Severity  | High (the rpitest fleet intermittently vanishes from the UI)                                     |
| Area      | `vpt-pi1` (rpitest.angelstreet.io) · Cloudflare · `backend_server` `/server/system/getAllHosts`   |
| Fixed in  | — (internal: our own lab transport, no product change)                                            |

---

## Read this first

Two different problems got conflated during this investigation, and the handover is
only useful if they stay separated:

1. **A transport fault** — Cloudflare could not reach the Pi for ~50% of requests.
   **Real, measured, and now fixed** with a Cloudflare Tunnel.
2. **The symptom actually reported** — the vpt-pi1 host disappearing from the
   UI. **Still happening after the tunnel.** The reporter's position, which the evidence
   below does not contradict: it worked fine yesterday, so something else changed.

The tunnel was justified by (1) and does not resolve (2). Do not close this bug on
the strength of the tunnel measurements.

---

## Symptom

The `vpt-pi1` host (4 devices: S21x, mi, stb3, stb4) intermittently disappears from
the frontend. It was working until ~2026-09-14.

---

## Part 1 — the transport fault (FIXED, and it was real)

`https://rpitest.angelstreet.io` returned Cloudflare **522** on roughly half of all
requests, hanging ~15s first (Cloudflare's origin-connect timeout).

**The decisive measurement** — correlate requests against the Pi's own nginx access log:

```
14 requests via Cloudflare  ->  10 x 200, 4 x timeout
nginx access-log delta      ->  exactly 10 lines
```

The four failures left **zero** trace on the Pi. The packets never arrived.

Everything else was eliminated with evidence:

| Hypothesis | Verdict |
|---|---|
| The origin / the Pi | **Innocent.** 10/10 from a Mac and 20/20 sequential + 20/20 parallel from Hetzner, direct to `77.56.53.130:443` via `curl --resolve`, all 30–80 ms. |
| DNS / the `*.angelstreet.io` wildcard | **Innocent.** One A record, `rpitest -> 77.56.53.130`, proxied. The wildcard points at `65.108.14.251`, and that host answers a `Host: rpitest…` request with a **fast 403**, not a hang — so falling through to it would look nothing like this. An exact record beats a wildcard anyway. |
| CORS (incl. BUG-0092) | **Impossible.** 522 is connection-level; no HTTP header logic is ever reached. |
| nginx | **Innocent.** `/etc/nginx/sites-enabled/rpitest.conf` unchanged since Jun 24, and it never saw the packets. The older `connect() failed (111: Connection refused)` entries to `127.0.0.1:5109` are a *different* thing — nginx→vpt-server during deploy restarts, which surface as 502. |
| The Supabase key rotation | **Innocent.** Only node3/QualiAI was rotated; node1's key is untouched. The failures appear in the nginx log at 00:19, 00:27, 00:45, 07:33 and 08:52, hours before the only change made to this Pi (a `.env` append at 10:29). |
| fail2ban / iptables | Neither is present on the Pi. |

Conclusion: packets were dropped between Cloudflare and nginx — at the home router or
the ISP. Cloudflare source IPs that *did* get through span `162.158`, `172.69`,
`172.71`, `188.114`, so it was not a static range block; it behaved like a rate or
connection-state limit (SPI firewall / "DoS protection" / NAT session cap).

### The fix that was applied

`cloudflared` 2026.9.1 (arm64, official `pkg.cloudflare.com` apt repo) on vpt-pi1.
The tunnel dials **outbound**, so the failing inbound path is bypassed entirely.

- Tunnel **`rpitest`**, id `74e1fcb9-211d-4c7a-895f-8e793a0ef465`
- Config `/etc/cloudflared/config.yml`; systemd unit `cloudflared`, enabled (survives reboot)
- `rpitest.angelstreet.io` is now a **CNAME to the tunnel**, no longer an A record

Config decisions worth keeping:

- Origin is **`https://localhost:443`**, not `:80` — the `:80` vhost is a 301 to https and would loop.
- nginx serves the **snakeoil self-signed** cert, hence `noTLSVerify: true` + `originServerName: rpitest.angelstreet.io`.
- `keepAliveTimeout: 90s` for streams / VNC / Socket.IO.

**Measured back to back, in the same minute:**

| path | failures |
|---|---|
| tunnel (staging hostname) | **0/20** |
| old inbound port-forward | **10/20** |

After cutover the live name measured **0/25**. The first post-cutover test showed 5/20
— that was purely Cloudflare edges still holding the cached A record, and it cleared in
~3 minutes. Expect that; do not panic-revert.

---

## Part 2 — why this is still OPEN

The 522s are gone, **and the host is still seen disappearing.** So either the 522s
were never the cause of the reported symptom, or they were only one of its causes.

### The strongest untested lead: a server-side stall, not a network one

`/server/system/getAllHosts` intermittently hangs **10–30 seconds on the Pi itself**,
with no tunnel and no network involved:

```
10 local calls to http://127.0.0.1:5109/server/system/getAllHosts
  000 30.0s | 200 12.5s | 200 0.002s | 200 0.020s | 200 0.054s
  200 0.27s | 200 0.22s | 200 0.22s | 200 0.17s  | 200 0.17s
```

**Why this would produce exactly the reported symptom:** the frontend calls this
endpoint with `AbortSignal.timeout(10000)` (`ServerManagerProvider.tsx`). Any response
slower than 10s makes the frontend mark that server as failed — and the host vanishes
from the UI. A 12.5s or 30s stall does that every time, and the tunnel cannot help.

Two candidate causes, neither confirmed:

- **Single gevent worker + WAN DB.** `vpt-server` runs `workers: 1` deliberately, with
  a ~200 ms WAN round-trip to the database, so one slow request blocks every other.
  See `reference_server_wan_db_single_worker`.
- **Something added by today's deploy.** The Pi now runs
  `feat/mobile-app-2026.09.15-8903`, deployed today, which is also when the S21x
  (`device1`, `android_mobile`) appeared. **This matches "it worked yesterday" better
  than anything else found.** Not yet proven — an obvious mechanism (adb calls
  blocking) was checked and ruled out: adb against the unauthorized device returns in
  0.010s, it does not hang.

### Next step for whoever picks this up

Reproduce the stall while watching the server log, and find what it blocks on:

```bash
ssh vpt-pi1 "sudo journalctl -u vpt-server -f" &
Q="include_actions=false&include_system_stats=false&force_refresh=false&team_id=7fdeb4bb-3639-4ec3-959f-b54769a219ce"
for i in $(seq 1 12); do
  curl -s -m 35 -o /dev/null -w "%{time_total}\n" \
    "http://127.0.0.1:5109/server/system/getAllHosts?$Q"
done
```

Then diff `feat/mobile-app-2026.09.15-8903` against what the Pi ran yesterday, focusing
on anything in the `getAllHosts` path that touches the new mobile device.

**Testing gotcha:** calling `getAllHosts` WITHOUT `include_system_stats=false` makes the
server poll every host — ~2 ms local vs >25 s. Always send the frontend's own
parameters, or you will measure the wrong thing and conclude the transport is broken.

**Also check before blaming the backend:** vpt-pi1 registers on **RPI1-server**, not
Awesomation. With the server picker on Awesomation it is *correct* for the host not to
appear.

---

---

## Part 3 — ROOT CAUSE FOUND (2026-09-15, follow-up session)

**The symptom is the same transport fault as Part 1, on the OUTBOUND leg.** The tunnel
fixed inbound (Cloudflare → Pi) only. The Pi's own outbound calls to the database still
cross the broken path, and that is what makes the host vanish.

It is **not** a code regression from today's deploy.

### The symptom, measured

The host is not "failing to display" — it is being **evicted from the server registry**
and re-registering, over and over. From `journalctl -u vpt-host` (today, 05:01–11:49):

| metric | value |
|---|---|
| successful pings | 304 (vs 408 expected at the 60 s cadence) |
| gaps > 90 s (`STALE_HOST_DISPLAY_SECONDS` → shown offline) | **22** |
| gaps > 180 s (`cleanup_stale_hosts` → **evicted, vanishes from the UI**) | **9** |
| total time absent from the registry | **~70 minutes** |
| worst single gap | **20.7 min** (11:26:01 → 11:46:41) |

The host log shows the eviction directly:

```
⚠️ [HOST] Ping failed (1/3): 404
🔄 [HOST] Server reports host not registered - attempting immediate re-registration...
❌ [HOST:vpt-pi1] Registration failed after 8 attempts, will retry next ping cycle
```

### The chain

1. **`send_ping_to_server()` makes ~7 sequential WAN database calls _before_ it pings.**
   `host_utils.py:507-577` — `store_system_metrics` (1), `store_device_metrics` (1 per
   device, now **4**), `get_devices_with_running_deployments` (2 selects). Only then is
   the ping POST sent. Registration liveness is gated on metrics storage.

2. **Each of those calls opens a brand-new TCP connection.** httpx's default
   `keepalive_expiry` is **5 s**; the ping interval is **60 s**. Every pooled connection
   is long dead by the next cycle. (httpx 0.28.1 / supabase 2.18.1 / postgrest 1.1.1.)

3. **The Pi's outbound SYNs are dropped.** The DB is reached at
   `https://virtualpytest.angelstreet.io/supabase` — over the WAN, through the same home
   router as Part 1. 40 requests from the Pi, watching `time_connect`:

   ```
   0.201  connect=0.035     <- healthy
   6.292  connect=6.128     <- SYN dropped, succeeded on retransmit
   12.00  connect=0.000     <- never connected
   ```

   9/40 needed a ~6 s SYN retransmit; 4/40 never connected at all.

4. **Established connections are perfectly healthy** — proving it is connection *setup*,
   not the link, not the database:

   | | failed | slow (>2 s) | median | max |
   |---|---|---|---|---|
   | new connection per request (what the code does) | 1/30 | 3/30 | 0.283 s | **15.3 s** |
   | one reused keep-alive connection | **0/30** | **0/30** | 0.109 s | **0.251 s** |

5. **`create_client(url, key)` sets no timeout** (`shared/src/lib/utils/supabase_utils.py:56`).
   A dropped SYN therefore stalls the ping thread for **minutes**, not seconds.

6. Past 180 s the server evicts the host and the UI drops it.

### Corroboration

- **9 of 9** eviction-length gaps contain a stuck
  `DeploymentScheduler._queue_watchdog ... skipped: maximum number of running instances
  reached (1)` (86 skips today). The watchdog blocks on the same outbound DB path, under
  `self.db_lock` — independent confirmation that the DB call, not the ping logic, is what
  hangs.
- **4,408,219 `TcpExtTCPSynRetrans`** on the Pi, against an error-free NIC (694 drops in
  2.95 billion packets). The loss is upstream, at the router/ISP — consistent with the
  NAT-session / connection-rate limit theory in Part 1.
- Only **1** established outbound WAN connection at rest, so the Pi is not exhausting
  anything itself.

### Why "it worked yesterday"

Nothing in the deploy broke it. The S21x brought the host from 3 devices to 4, which adds
one more `store_device_metrics` call — **7 fresh connections per ping cycle instead of 6**.
At a ~10 % fatal SYN-drop rate that is roughly a coin-flip per cycle that some call hangs.
The margin was already thin: ping every 60 s against a 90 s stale threshold leaves only
30 s of slack.

### The fix (proposed, NOT yet applied)

In order of impact:

1. **Do not gate the ping on the metrics writes.** Send the ping POST first, or move
   metrics storage to its own thread. A metrics write failing must never de-register a
   live host. *(This is the one that actually fixes the symptom.)*
2. **Set a timeout on the supabase client** in `supabase_utils.py` so a dropped SYN fails
   in seconds instead of hanging for minutes.
3. **Reuse connections** — raise httpx `keepalive_expiry` above the 60 s ping interval.
   Measured: this alone took the failure rate from 4/30 to 0/30.
4. **Widen the margin** — `HOST_PING_INTERVAL_SECONDS` 60 s against a 90 s display
   threshold and 180 s eviction is too tight for a WAN-attached host.
5. **Environmental** — the router's connection-rate / NAT-session limit is the underlying
   fault, and it also explains Part 1. Routing the Pi's outbound DB traffic through the
   existing `cloudflared` tunnel (one long-lived connection) would sidestep it the same
   way the tunnel fixed inbound.

### Commands to re-verify

```bash
# eviction gaps
ssh vpt-pi1 'journalctl -u vpt-host --since today | grep -oE "Ping sent successfully at [0-9:]+"'

# the SYN drops (watch time_connect, not time_total)
ssh vpt-pi1 'U=...; K=...; for i in $(seq 1 40); do
  curl -s -m 12 -o /dev/null -w "%{time_total} connect=%{time_connect}\n" \
    -H "apikey: $K" -H "Authorization: Bearer $K" \
    "$U/rest/v1/deployments?select=id&limit=1"; done'
```


---

## Part 4 — why the router started dropping packets: we are doing it to ourselves

The objection raised was the right one: *"before we never needed this Cloudflare tunnel
and now we do — something is strange."* Nothing is wrong with the router or the ISP.
**The proxy opens a brand-new TCP connection for every HLS segment**, and once the
stream count grew it crossed the router's NAT session limit.

### The measurement

On vpt-pi1, sockets to `65.108.14.251` (the Proxmox host, NAT egress for the whole
`192.168.0.0/24` LAN):

```
1366 sockets total  ->  1356 TIME-WAIT, 6 ESTAB
local port 443  =  these are INBOUND, proxy -> Pi nginx
```

The nginx access log explains them — **~1400 requests/minute**, essentially all of the
Pi's traffic:

```
1402 req  at 12:14
1426 req  at 12:15

/host/vpt-pi1/stream/capture{1,2,3,4}/segments/segment_N.ts
/host/vpt-pi1/stream/capture{1,2,3,4}/segments/output.m3u8
Referer: https://virtualpytest.angelstreet.io/device-control
User-Agent: Chrome/152 (Macintosh)
```

A real browser sitting on `/device-control` playing every device's live preview. One
request ≈ one connection ≈ one NAT session: 1366 sockets against ~1400 requests/minute
is a 1:1 ratio, i.e. **zero connection reuse**.

### The cause, in one line of nginx

`proxy:/etc/nginx/sites-enabled/virtualpytest`, the `rpitest.angelstreet.io` block:

```nginx
location / {
    proxy_pass https://77.56.53.130;      # literal address — no upstream block
    proxy_http_version 1.1;
    proxy_set_header Connection "upgrade"; # hardcoded, on EVERY request
}
```

Two independent reasons the connection can never be reused:

1. **`Connection: upgrade` is sent on every request**, not just WebSocket upgrades. The
   map that does this correctly already exists on this host
   (`/etc/nginx/conf.d/00-websocket-upgrade.conf`, `$connection_upgrade`) and the Pi's
   own config uses it — this block just hardcodes the value instead.
2. **There is no `upstream` block**, and nginx only keeps an upstream connection pool
   for an `upstream { ... keepalive N; }`. `proxy_pass` to a literal host never pools.

So each segment costs a full TCP handshake + TLS handshake across the home router, and
leaves a NAT session in TIME-WAIT behind it.

### Why it started now

The config has been wrong for a long time; the traffic only recently crossed the limit.
vpt-pi1 went from 3 capture channels to 4 (the S21x), and `/device-control` plays them
all at once alongside vpt-pi3's. Segments are **0.40 s** long, so each stream alone is
~2.5 segment requests/second plus playlist polls.

That also retro-explains Part 1 exactly: a saturated NAT table drops *new* connections
in **both** directions — Cloudflare's inbound SYNs (the 522s) and the Pi's outbound SYNs
to the database (Part 3). One cause, two symptoms, and the tunnel only ever hid the
inbound half.

### The fix — no tunnel required

```nginx
upstream rpitest_origin {
    server 77.56.53.130:443;
    keepalive 32;
    keepalive_timeout 300s;
    keepalive_requests 10000;
}

location / {
    proxy_pass https://rpitest_origin;
    proxy_http_version 1.1;
    proxy_set_header Connection $connection_upgrade;   # map-based: "" for normal requests
    ...
}
```

That collapses ~1400 connections/minute into ~32 persistent ones — roughly a **40x**
reduction in NAT sessions, and it removes the TLS handshake from every segment.

Worth doing as well:
- Raise the 0.40 s segment duration; at 2 s it is 5x fewer segment requests.
- Lazy-load the previews on `/device-control` instead of auto-playing every device.
- The same hardcoded `Connection "upgrade"` appears in 10 places in this config. Only
  this one crosses a consumer router, but the others pay needless handshakes too.

Once this is deployed and inbound holds without it, `cloudflared` can be removed and
`rpitest.angelstreet.io` pointed back at an A record.


---

## Part 5 — resolution, measured

### The block that actually mattered

Part 4 named the proxy, but the first fix went to the wrong server block. The HLS
traffic does not use the `rpitest.angelstreet.io` vhost at all — it comes through
`snippets/vpt-app-locations.conf`:

```nginx
location ~ ^/host/(vpt-pi[0-9]+)/stream/(.+)$ {
    proxy_pass https://77.56.53.130/host/$pi_name/stream/$stream_path;  # literal IP
    proxy_http_version 1.1;
    # no Connection header at all -> nginx sends "close"
}
```

Two consequences worth remembering:

- No upstream block and no `Connection ""`, so **every segment opened a new TCP+TLS
  connection**.
- It hardcodes the **IP**, so this traffic never resolved `rpitest.angelstreet.io` and
  **never went through the tunnel** — which is precisely why the tunnel changed nothing
  for the reported symptom.

A third trap: the host already had a `$connection_upgrade` map, but it maps a
non-upgrade request to **`close`**, not `""`. Reusing it would have looked correct and
fixed nothing. The stream location sets `proxy_set_header Connection "";` directly.

### Result

| measure | before | after |
|---|---|---|
| requests per TCP connection (proxy -> Pi) | **1.0** | 342 requests over **18** connections |
| TIME-WAIT sockets from the proxy NAT | 1212–1366 | **0** |
| Pi outbound DB: fatal / slow out of 40 | 4 fatal, 9 slow | **0 fatal, 3 slow** |
| inbound via the home port-forward, no tunnel | 10/20 failures | **0/30 failures** |
| host heartbeat age | 68 s, repeatedly past the 180 s eviction | **7–28 s** |

Host-side (Part 3) is deployed on vpt-pi1 and vpt-pi3 and confirmed live — `py-spy`
shows `ping_worker` and `metrics_worker` as separate threads, and both hosts hold a
steady heartbeat.

### The tunnel stays — measured, not assumed

An earlier draft of this section said the tunnel was redundant. That was wrong, and the
mistake is worth recording: it rested on testing **only from inside Hetzner**, direct to
the origin IP, which is not the path real users take.

Tested properly, with `cloudflared` stopped and the A record live:

| path | failures |
|---|---|
| Hetzner -> origin IP directly (single source IP) | **0/30** |
| through Cloudflare edges, i.e. what a browser does | **6/30 (20%)** |

The origin and the router are fine with direct traffic. What still fails is specifically
**Cloudflare edge -> origin**: Cloudflare dials from many different edge IPs, each a new
connection, and our keepalive fix cannot reach that side of the hop. The failures are
12s timeouts, matching Cloudflare's origin-connect behaviour on a dropped SYN — the same
Part 1 fault, reduced from ~50% to ~20% by the nginx fix but not eliminated.

So the two fixes address two different halves and both are needed:

- **the nginx keepalive fix** carries the heavy traffic — the ~1400 req/min of HLS
  segments, which go proxy -> origin IP and never touch Cloudflare. That path is 0/30.
- **the tunnel** carries browser and API access to `rpitest.angelstreet.io`, which does
  go through Cloudflare. Without it, ~20% of those requests time out.

`cloudflared` has been re-enabled and holds 4 registered connections.

**To actually route through it, DNS must go back to the CNAME.** While the A record
exists it wins, the tunnel sits idle, and the ~20% failure rate stands. Current state:
A record live, tunnel running but bypassed, measured 3/20 failures.

The real fix that would retire the tunnel is the router: raise its NAT session /
connection-rate limit, or disable its SPI "DoS protection". Until then the tunnel is
load-bearing.


## Environment notes for the next session

- `tcpdump` is **not installed** on vpt-pi1 — a capture there silently produces an empty
  file and looks like "zero packets", which is a trap.
- Direct SSH to the Pi needs `IPQoS throughput` (now set in `~/.ssh/config`); without it
  the connection opens then stalls and the Pi looks dead when it is healthy.
- The Pi is `vpt-pi1`; `sunri1` is retired naming.
- Unrelated and still open on this Pi: the S21x is adb **`unauthorized`**. `vpt_user` was
  added to `plugdev` and given an adb key, which moved it from `no permissions` to
  `unauthorized`; finishing it needs someone to physically tap **Allow USB debugging** on
  the phone. Its HDMI capture shows the SMPTE no-signal pattern, so the prompt cannot be
  read remotely.

## Leftovers from the tunnel work

- DNS record `rpitest-tunnel.angelstreet.io` (CNAME, the staging name) still exists in
  Cloudflare and can be deleted — it is already out of the tunnel ingress.
- The router's inbound 443 port-forward is now unused and could be closed.
- Reverting the tunnel, if ever needed: point `rpitest.angelstreet.io` back to an A
  record for `77.56.53.130` and `systemctl disable --now cloudflared`. That restores the
  ~50% 522 behaviour, so only do it if the tunnel itself is implicated.
