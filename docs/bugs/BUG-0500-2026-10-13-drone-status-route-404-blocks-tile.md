# BUG-0500 — The drone status route asked the host for a page that never existed, so the tile could never report the drone's real state

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                            |
|-----------|------------------------------------------------------------------|
| ID        | BUG-0500                                                         |
| Reported  | 2026-10-13                                                       |
| Status    | Fixed                                                            |
| Severity  | Medium                                                           |
| Area      | backend_server / backend_host — drone (Tello) status polling     |
| Fixed in  | build 90145 |
| Commit    | `db36f0f43`                                                      |

---

## Symptom

The Tello tile on `/device-control` always read **"AP check failed — vpt-pi4 cannot be reached"**, whatever the drone
was actually doing. The browser's network log showed one call failing on every poll:

```
GET /server/drone/tello/status?host_name=vpt-pi4&device_id=device3
  -> 404 {"error": "The requested URL was not found on the server..."}
```

The tile never showed "AP unavailable — power on the drone", and never showed "Connected", no matter how many times
**Scan** was pressed.

## Root cause

`/server/drone/tello/status` proxied to **`/host/remote/getStatus`** — an address that has never existed.

The `host_remote` blueprint (`url_prefix='/host/remote'`) exposes exactly seven routes:

```
/takeScreenshot  /screenshotAndDump  /getApps  /tapCoordinates
/executeCommand  /dumpUi             /getOrientation
```

There is no `getStatus` among them. The comment above the call said the route *was* the generic remote status route and
that it would return `{linked, airborne, ip, ...}` — it was never verified against the host's blueprint.

The **404 was not just a missing answer, it aborted the whole poll chain.** `useDroneWifiStatus` asks three questions in
order:

1. is the link already up? → `/server/drone/tello/status`
2. if not, is the AP in range? → `/server/drone/tello/scan`
3. if it is, join it → `/server/drone/tello/pair`

`apiClientJson` throws on any non-2xx, and the hook's `catch` sets the error state and returns. So question 1 failing
meant questions 2 and 3 **never ran**. The tile could not reach "AP unavailable / Power on the drone" even with the drone
genuinely off — the most useful state it could have shown.

A second, independent problem: the host's copy of the drone code had never received BUG-0490, so the drone routes did
not exist on that machine at all.

## Fix

**`backend_host/src/routes/host_drone_routes.py`** — new route:

```python
@host_drone_bp.route("/tello/status", methods=["POST"])
```

It resolves the device's Tello controller and returns `controller.get_status()`, which already emits exactly the
contract the tile expects (`success`, `linked`, `last_error`, `airborne`, `ip`, ports).

**A device with no Tello controller answers HTTP 200 with `linked: false`, not 404.** "No link" is a valid answer, and
returning 404 here would reintroduce exactly this bug through the back door: the tile would throw, skip its scan, and
show the catch-all error again.

**`backend_server/src/routes/server_drone_routes.py`** — proxy retargeted from `/host/remote/getStatus` to
`/host/drone/tello/status`.

No frontend change was needed: the tile already polls `/server/drone/tello/status` and already reads `linked`.

### Why not reuse `/host/drone/tello/last_known`?

It answers a different question — "where was the drone last", for the *Find my Tello* UI. It returns state/pose/age but
no `linked` field, and it returns **404** when there is no controller, which is precisely the response shape that broke
the tile. A route that answers the right question with the right contract was the better fix than repointing at a
neighbour that answers a different one.

## Tests

- `tests/drone/test_tello_status_route.py` (new, 3 tests) — pins the proxy target, that a `linked: false` answer passes
  through untouched, and that missing params are a 400.
- `tests/backend_host/test_tello_pair_routes.py` (+3 tests) — pins the controller's link state, the
  **200-not-404** rule, and the 400.

All 15 pass. This test lives under `tests/drone/`, not `tests/backend_server/`, because that directory's conftest
skips the entire module unless a live backend answers `/server/health` — which would have silently skipped the exact
regression this bug is about.

## Verification

Root cause first reproduced directly on vpt-pi4, which settles the diagnosis:

| host route | result |
|---|---|
| `/host/remote/getStatus` (what the server called) | **404** |
| `/host/remote/executeCommand` (same blueprint) | 400 — exists, rejected body |
| `/host/drone/tello/scan` | 200 |
| `/host/drone/tello/status` (new) | 404 before the deploy |

A sibling route in the same namespace answering 400 and the scan answering 200
proves the host was reachable, the API key was good, and exactly one address was
missing. This is also why the earlier "the proxy has nothing to dial"
explanation (`host_ip = None` in the registry) was wrong.

After deploying the two route files to vpt-pi4 and restarting `vpt-host` then
`vpt-server`, the whole chain answers:

```
GET /host/drone/tello/status -> 200
  {"success": true, "linked": false, "airborne": false, "ip": "192.168.x.1",
   "state_port": 8890, "video_port": 11111, "last_error": null, ...}
```

`linked: false` is the truth: the Tello is powered off.

Browser probe on the live build, both schemes — and note the **scan now runs**,
which it never could before:

```
drone api  : 200 .../server/drone/tello/status?... | 200 .../server/drone/tello/scan?...
overlay    : AP unavailable / Power on the drone
placeholder: true
scan chip  : true
raw leak   : false
PASS [light] / PASS [dark]
```

The tile now reports the one state it could never reach: the drone's access
point is not in range because the drone is switched off.

## Deploy note

vpt-pi4 turned out **not** to be stale for BUG-0490 — `host_utils.py` there
already carries the `'tello'` entry (line 981) and is byte-identical to the repo
checkout. Only the two route files differed, so only those two were pushed.
An earlier reading of that file truncated the grep output and wrongly suggested
the `tello` key was missing.

The Pi is not reachable through `update_core.sh` for a single host — a `--host`
deploy fans out to all ten machines in `HOST_IPS`, so any host lease blocks it.
This deploy claimed `node1-vpt/vpt-pi4` directly and pushed only that machine.