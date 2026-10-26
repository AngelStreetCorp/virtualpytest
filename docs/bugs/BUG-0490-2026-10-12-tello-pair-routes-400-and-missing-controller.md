# BUG-0490 — Tello pairing never worked: every /host/drone/tello/* call answered 400 before reading a field

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0490                                                     |
| Reported  | 2026-10-12                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                         |
| Area      | backend (backend_host)                                       |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

Every Tello pairing call on a real host failed immediately, with an error that named
no real problem:

```console
$ curl -X POST -H "X-API-Key: $KEY" -H 'Content-Type: application/json' \
    -d '{"device_id":"device5"}' http://127.0.0.1:6109/host/drone/tello/last_known
{"error":["device5",null],"success":false}
```

The drone itself was fine — it answered `command` → `ok` in 25 ms over the SDK and sent
a 127-byte state datagram with `bat:83`, `temph:72`. The failures were entirely in the
platform route. Reproduced on vpt-pi4 with a live `TELLO-C5B142` associated on `wlan0`.

## Root cause

Three independent defects, all in the host-side pairing flow, each fatal on its own.

**1. `require_field` was used as a truthiness test** — `backend_host/src/routes/host_drone_routes.py`.
The helper returns a two-tuple `(value, error_response)`, and the route did:

```python
if err := require_field(payload, "device_id"):
    return bad_request(err)
```

A non-empty tuple is *always* truthy, so this branch fired on every request, including
well-formed ones, and passed the tuple to `bad_request` — which is exactly the
`{"error": ["device5", null]}` above, where the echoed `device_id` is the tuple's value
and `null` its error. All four routes (`pair`, `mission_pads`, `flight_summary`,
`last_known`) had the same two lines, so **no drone route ever reached its own logic**.
Every other host route unpacks the tuple (`command, err = require_field(...)`).

**2. `'tello'` was missing from `controller_class_patterns`** — `backend_host/src/lib/utils/host_utils.py:969`.
`get_remote_controller_by_type()` maps a `remote_type` to controller class names; the table
listed `android_tv`, `ir_remote`, `android_mobile`, `appium`, `bluetooth_remote` and `vega`,
but not `tello`, so it returned `None` and printed `Unknown remote type: tello`.
`controllers/__init__.py:72` registers `TelloRemoteController` in `REMOTE_CONTROLLERS`, so
the controller really is built from `DEVICE{i}_TELLO_IP` — a controller that exists and a
controller this lookup can find are two different things.

**3. `_join_ap()` shelled out to `sudo nmcli`** — `backend_host/src/routes/host_drone_routes.py:109`.
Changing a NetworkManager connection is privileged: polkit lets any user *read* a scan but
refuses `nmcli device wifi connect` with `Not authorized to control networking`, and
`vpt_user` is not in the `network` group (verified on vpt-pi4: `id vpt_user` shows audio,
video, plugdev, systemd-journal, render). The route therefore 500'd at stage `join` before
reaching the controller step — and it treated that as fatal even when the host was already
associated and could already reach the drone.

## Fix

- All four routes unpack `require_field` the way every other host route does, and return
  the error response itself.
- `controller_class_patterns` gained `'tello': ('TelloRemoteController',)`.
- `nmcli` runs through `_run_nmcli()`, which tries the unprivileged call first (works where
  polkit allows it) and falls back to `sudo -n`. `_join_ap()` now reports
  `already_active` instead of failing when the host is associated already, and re-reads the
  association before believing a failed command. `tello_pair()` no longer 500s at stage
  `join`: the SDK link check is the real gate, and the `join` outcome is returned in the
  response either way.
- New `setup/local/linux/backend_host/sudoers.d/tello-wifi` lets `vpt_user` run exactly two
  NetworkManager verbs without a password: `device wifi rescan`, and `device wifi connect
  TELLO-*`. The `TELLO-*` argument pin means the rule cannot be used to re-point the host at
  an arbitrary access point, and the route independently validates the SSID against
  `^TELLO-[0-9A-Fa-f]{6}$` before reaching it. Wired into the main sudoers block in
  `install_host.sh`.

## Verification

`tests/backend_host/test_tello_pair_routes.py` (new, 9 tests) pins all three: the lookup
resolves `tello` to a `TelloRemoteController` and still returns `None` for an unknown type;
`_join_ap()` is a no-op when already associated, falls back to `sudo -n` when polkit
refuses, reports sudo's reason over polkit's, and believes the association over a failed
command; and the route returns 200 when the link verifies despite a failed join, 500 at
stage `link` carrying the join detail, and 400 for a non-Tello SSID.

- `tests/backend_host/test_tello_pair_routes.py` — 9 passed
- `tests/drone` — 82 passed (unchanged)

Run on vpt-pi4 (Python 3.11, the host venv's packages) against the branch. The defects were
reproduced live first: `Unknown remote type: tello` from the deployed code, and
`sudo: a password is required` for the nmcli join as `vpt_user`.

**After deploying `main` to vpt-pi4** (drone powered off, so `pair` cannot succeed — the point is
that it now reaches the right stage and reports real reasons):

```
$ curl -X POST … -d '{"device_id":"device3"}' …/host/drone/tello/last_known
{"airborne":false,"device_id":"device3","ip":"192.168.x.1","pose":{"x":100.0,"y":100.0,"yaw":0.0,"z":0.0},
 "state":{},"state_age_s":null,"state_port":8890,"success":true}

$ curl -X POST … -d '{"device_id":"device3","ssid":"TELLO-C5B142"}' …/host/drone/tello/pair
{"error":"no reply from 192.168.x.1:8889 in 5.0s","stage":"link","success":false,
 "join":{"ok":false,"reason":"Error: No network with SSID 'TELLO-C5B142' found."},"tello_ip":"192.168.x.1"}

$ curl -X POST … -d '{"device_id":"device3"}' …/host/drone/tello/flight_summary
{"device_id":"device3","log_path":null,"success":true,"summary":null}
```

`last_known` went from `{"error":["device5",null],"success":false}` to a real payload; `pair` moved
from an immediate 400 to stage `link` with the join failure reported alongside it; the lookup probe
went from `Unknown remote type: tello` → `None` to returning a `TelloRemoteController`. The `join`
reason is nmcli's own "No network with SSID found" rather than polkit's "Not authorized", which
shows the route really is reaching the privileged `nmcli` through the new drop-in.

The sudoers rule was checked on the live host too: `device wifi rescan` runs as `vpt_user` (rc=0),
`sudo -l` lists exactly the two intended rules, and both `nmcli con down` and
`nmcli device wifi connect EvilNet` are still rejected — so the `TELLO-*` argument pin holds.