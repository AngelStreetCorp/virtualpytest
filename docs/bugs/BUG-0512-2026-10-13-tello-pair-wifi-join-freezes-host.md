# BUG-0512 — Pairing or scanning for a Tello froze the whole vpt-host while nmcli ran

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0512                                                     |
| Reported  | 2026-10-13                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                         |
| Area      | backend_host / drone                                         |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

While POST `/host/drone/tello/pair` joined the drone's Wi-Fi, or POST `/host/drone/tello/scan`
scanned for drones, every other request on that host stopped: stream tiles stalled and the status
poll hung. A join waits up to 30 s (`nmcli device wifi connect`, then the `sudo -n` retry) plus a
3 s DHCP settle; a scan waits for `rescan` plus a 4 s settle and the list.

## Root cause

Same as [BUG-0511](BUG-0511-2026-10-13-tello-flight-command-freezes-host.md): vpt-host serves
gevent without monkey patching, so `subprocess.run` and `time.sleep` on a request greenlet block
the hub. BUG-0511 moved the controller's drone waits off the hub; the route's own nmcli calls
(`_join_ap` → `_run_nmcli`, `_scan_tello_ssids`, `_active_wifi_ssid` in the status poll) and its
settle sleeps still ran on the request greenlet.

## Fix

- `_off_hub` moved from `controllers/remote/tello.py` to
  `backend_host/src/lib/utils/gevent_utils.py` as `off_hub` (the controller imports it).
- `host_drone_routes.py`: the pair route runs the join + DHCP settle (`_join_and_settle`), the
  scan route runs `_scan_tello_ssids`, and the status route runs `_active_wifi_ssid` through
  `off_hub`.

## Verification

`tests/drone/test_tello_gevent_hub.py::test_pair_wifi_join_leaves_the_host_answering` (codebox):
a fake `nmcli` on PATH whose `wifi connect` is a real `sleep 3` subprocess; the pair request runs
in a greenlet while `/host/drone/tello/status` is called — status answers in < 0.5 s and the whole
spawn-to-answer window stays < 1 s while the pair is still waiting. Against the previous route the
same test fails (6 s: join + settle on the hub). `tests/backend_host/test_tello_pair_routes.py`
and the rest of `tests/drone/` stay green.
