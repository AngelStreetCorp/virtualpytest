# BUG-0506 — Tello take-off timed out: commands left from a port the drone does not answer

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0506                                                     |
| Reported  | 2026-10-13                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                         |
| Area      | backend_host / drone                                         |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

The Tello Remote panel showed `Take off: link to 192.168.x.1:8889 failed: Tello-XXXXXX: timeout after
10.0s waiting for reply to 'command'` on a paired drone whose video was playing. On the host (on the
drone's Wi-Fi, ping fine, video arriving on UDP 11111) `command` sent from a random local port, and from a
fixed port 9000, timed out every time; only the very first `command` — sent by the pair route — had been
answered.

## Root cause

A Tello only answers the address:port that sent its first `command` after power-on. Pairing checked the
link from its own one-shot socket (`_verify_link` in `backend_host/src/routes/host_drone_routes.py`),
then the controller opened its link from a different, random port (`TelloClient` bound its command socket
to port 0), so the drone never answered the controller. A failed connect also left its sockets open.

## Fix

- `shared/src/lib/drone/tello.py`: `TelloClient(local_cmd_port=…)` sends every command from one fixed local
  port (SO_REUSEADDR) and closes every socket when `connect()` fails. `enter_sdk()` re-sends `command`.
- `backend_host/src/controllers/remote/tello.py`: the controller uses local port 8889, has a `link` command,
  keeps its link after landing (state datagrams keep flowing for the battery), and re-sends `command` to a
  landed drone whose state went silent (power cycle).
- `host_drone_routes.py`: pairing no longer opens its own socket; it configures the controller and calls
  its `link`. The status route reopens the link in the background when the host is on the drone's Wi-Fi but
  the controller has none (vpt-host restarted).

- Second defect found on the same host: `get_telemetry` linked on the request thread. vpt-host serves
  Flask-SocketIO on gevent without monkey patching, so a 10 s blocking `recvfrom` (drone off) froze every
  request, and each 2 s poll of the remote panel kept the host wedged (stream playlists → Cloudflare 524).
  Reads now never link on the request path: `link_in_background()` runs on an OS thread, at most one at a
  time, not again within 10 s of a failure; the handshake waits 4 s.

## Verification

- `tests/drone/test_tello_controller.py::test_every_command_leaves_from_the_one_port_the_drone_answers`:
  a fake drone that only answers its first sender keeps answering across a re-link.
- `test_telemetry_never_blocks_the_request_on_an_unreachable_drone`: a read answers in < 0.5 s.
- On the bench: power-cycle the drone, let the tile pair it, then `command` and `battery?` from the remote
  panel answer repeatedly.
