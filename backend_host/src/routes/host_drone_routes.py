"""
Host Drone Routes

Host-side endpoints for the Tello pairing flow. Pairing does three things
on the host:

  1. nmcli joins the Tello's Wi-Fi AP. Changing a NetworkManager connection
     is privileged (polkit only lets any user *read* a scan), so this needs
     the `network` group or the sudoers drop-in
     `setup/local/linux/backend_host/sudoers.d/tello-wifi`. When the host is
     already associated the step is a no-op and is never treated as a failure
     — the SDK link check is what decides whether pairing worked. A host that
     keeps its LAN on Ethernet does not lose connectivity while wlan0 sits on
     the drone AP (measured on vpt-pi4, 2026-10-12); a Pi on Wi-Fi does.
  2. We push the new endpoint into the device's TelloRemoteController
     (``configure``) and let the controller open ITS OWN link (``link``):
     ``command``, then ``streamon`` so the video reaches vpt-stream right away.
     One socket owner on purpose: a Tello only answers the address:port that
     sent its first ``command``, so a separate check socket here used to be the
     only one the drone ever answered, and every flight command timed out.
     The link stays open, so the state datagrams (battery, temperature, speed)
     reach the tile through the status route.
     Every nmcli call and settle wait runs off the gevent hub (``off_hub``,
     BUG-0512): vpt-host is not monkey patched, so a 30 s `wifi connect` on the
     request greenlet froze every other request, stream playlists included.
  3. The controller remembers the paired SSID, so the device preview's automatic
     scan keeps re-joining that drone and ignores any other Tello nearby. The
     device keeps its DEVICE{i}_NAME; pairing never renames it.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import time
from typing import Any, Dict, List, Optional

from flask import Blueprint, jsonify, request

from backend_host.src.lib.utils.gevent_utils import off_hub
from backend_host.src.lib.utils.host_utils import (
    get_device_by_id,
    get_remote_controller_by_type,
)
from backend_host.src.lib.utils.route_decorators import route_exception_handler
from backend_host.src.lib.utils.route_request import get_json_payload, require_field
from backend_host.src.lib.utils.route_response import bad_request


logger = logging.getLogger(__name__)

host_drone_bp = Blueprint("host_drone", __name__, url_prefix="/host/drone")


TELLO_SSID_RE = re.compile(r"^TELLO-[0-9A-Fa-f]{6}$")

# A Wi-Fi scan takes ~3.3 s on vpt-pi4 (measured 2026-10-13); list after it is done.
SCAN_SETTLE_S = 4.0


# ---------- helpers --------------------------------------------------------------

def _scan_tello_ssids() -> List[Dict[str, Any]]:
    """Return the Tello-* APs visible to the host's wlan0."""
    # `rescan` only REQUESTS a scan and returns at once; the scan itself takes ~3.3 s
    # on vpt-pi4. Listing after 2 s read the PREVIOUS scan: a drone switched on a
    # moment ago was missing, one switched off was still listed. `list --rescan yes`
    # would wait for it, but unprivileged it silently skips the scan (93 ms, cached
    # list) and the sudoers drop-in only allows `rescan` and `connect`.
    _run_nmcli(["device", "wifi", "rescan"], 15)
    time.sleep(SCAN_SETTLE_S)
    out = subprocess.run(
        ["nmcli", "-t", "-f", "SSID,SIGNAL,SECURITY", "device", "wifi", "list"],
        capture_output=True, text=True, timeout=15,
    )
    if out.returncode != 0:
        raise RuntimeError(f"nmcli list failed: {out.stderr.strip()}")
    tellos: List[Dict[str, Any]] = []
    for line in out.stdout.splitlines():
        if not line.strip():
            continue
        # nmcli -t escapes ':' inside fields as '\\:'; the SSID is the
        # first field, signal the second, security the rest.
        parts = line.split(":")
        if len(parts) < 3:
            continue
        ssid, signal = parts[0], parts[1]
        security = ":".join(parts[2:])
        if TELLO_SSID_RE.match(ssid):
            try:
                sig = int(signal)
            except ValueError:
                sig = None
            tellos.append({"ssid": ssid, "signal": sig, "security": security or "OPEN"})
    return tellos


def _run_nmcli(args: List[str], timeout_s: float) -> subprocess.CompletedProcess:
    """Run ``nmcli <args>`` unprivileged first, then with ``sudo -n``.

    NetworkManager's polkit lets any user *read* a Wi-Fi scan but not *change*
    a connection, so `device wifi connect` needs either the `network` group or
    a sudoers rule for the service user
    (`setup/local/linux/backend_host/sudoers.d/tello-wifi`). Trying the cheap
    path first means a host that grants polkit works without the drop-in
    installed, and the privileged path stays a fallback instead of a hard
    dependency.
    """
    plain = subprocess.run(["nmcli", *args], capture_output=True, text=True, timeout=timeout_s)
    if plain.returncode == 0:
        return plain
    privileged = subprocess.run(
        ["sudo", "-n", "nmcli", *args],
        capture_output=True, text=True, timeout=timeout_s,
    )
    # The sudo error names the real blocker ("a password is required"), so
    # prefer it over polkit's vaguer "Not authorized to control networking".
    return privileged


def _active_wifi_ssid() -> Optional[str]:
    """The SSID any wireless device is associated with right now, if any."""
    out = subprocess.run(
        ["nmcli", "-t", "-f", "DEVICE,TYPE,NAME", "con", "show", "--active"],
        capture_output=True, text=True, timeout=15,
    )
    if out.returncode != 0:
        return None
    for line in out.stdout.splitlines():
        parts = line.split(":")
        if len(parts) >= 3 and parts[1].strip() in ("802-11-wireless", "wifi"):
            return parts[2].strip() or None
    return None


def _join_ap(ssid: str, timeout_s: float = 30.0) -> Dict[str, Any]:
    """Associate the host's wireless device with the Tello's AP.

    Returns ``{"ok", "already_active"}`` or ``{"ok": False, "reason"}``. A
    failure here is not fatal on its own: the host is often already
    associated, and the caller must still run the SDK link check, which is
    what actually decides whether pairing worked.
    """
    if _active_wifi_ssid() == ssid:
        return {"ok": True, "already_active": True}
    out = _run_nmcli(["device", "wifi", "connect", ssid], timeout_s)
    if out.returncode == 0:
        return {"ok": True, "already_active": False}
    # A join that landed but reported an error (older NetworkManager) still
    # counts, so re-read the association before believing the failure.
    if _active_wifi_ssid() == ssid:
        return {"ok": True, "already_active": True}
    reason = out.stderr.strip() or out.stdout.strip() or f"nmcli exited {out.returncode}"
    return {"ok": False, "reason": reason}


# ---------- two-radio hosts (tello_prio.sh) --------------------------------------
# A host with one Wi-Fi dongle per drone (scripts/drone/tello_prio.sh) keeps each radio out of
# NetworkManager and tells the drones apart by source address (DEVICE<i>_TELLO_LOCAL_IP). On such
# a slot `nmcli device wifi connect` joins the wrong radio (or none) and nmcli never reports the
# association, so pairing joins through the script and the association is read with iw.

TELLO_PRIO = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", "scripts", "drone", "tello_prio.sh"
)
DRONE_AP_IP = "192.168.10.1"


def _radio_for(controller: Any) -> Optional[Dict[str, Any]]:
    """The dedicated radio of a slot with its own source address, else None.

    Returns ``{"iface", "index", "host_ip"}``: the interface and drone number that tello_prio.sh
    configured for the slot's DEVICE<i>_TELLO_LOCAL_IP (read back from the kernel's policy rules).
    """
    host_ip = getattr(controller, "local_ip", None)
    if not host_ip or host_ip == "0.0.0.0":
        return None
    try:
        rules = subprocess.run(["ip", "-4", "rule", "show"], capture_output=True, text=True, timeout=5).stdout
        route = subprocess.run(
            ["ip", "-4", "route", "get", DRONE_AP_IP, "from", host_ip],
            capture_output=True, text=True, timeout=5,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    table = re.search(rf"from {re.escape(host_ip)} lookup (\d+)", rules)
    dev = re.search(r"\bdev (\S+)", route)
    if not table or not dev:
        return None
    return {"iface": dev.group(1), "index": int(table.group(1)) // 100, "host_ip": host_ip}


def _ssid_on(iface: str) -> Optional[str]:
    """The SSID ``iface`` is associated with right now (iw), if any."""
    out = subprocess.run(["iw", "dev", iface, "link"], capture_output=True, text=True, timeout=10)
    m = re.search(r"^\s*SSID: (.+)$", out.stdout, re.M)
    return m.group(1).strip() if m else None


def _join_radio(radio: Dict[str, Any], ssid: str, timeout_s: float = 25.0) -> Dict[str, Any]:
    """Associate the slot's own radio with ``ssid`` through tello_prio.sh (root, via sudoers)."""
    if _ssid_on(radio["iface"]) == ssid:
        return {"ok": True, "already_active": True, "iface": radio["iface"]}
    out = subprocess.run(
        ["sudo", "-n", os.path.normpath(TELLO_PRIO), "up", str(radio["index"]), radio["iface"], ssid, radio["host_ip"]],
        capture_output=True, text=True, timeout=timeout_s,
    )
    if out.returncode == 0 and _ssid_on(radio["iface"]) == ssid:
        return {"ok": True, "already_active": False, "iface": radio["iface"]}
    reason = (out.stderr.strip() or out.stdout.strip() or f"tello_prio.sh exited {out.returncode}")
    return {"ok": False, "reason": reason, "iface": radio["iface"]}


def _associated_ssid(controller: Any) -> Optional[str]:
    """The SSID the slot's drone link rides on: its own radio, else the host's NetworkManager one."""
    radio = _radio_for(controller)
    return _ssid_on(radio["iface"]) if radio else _active_wifi_ssid()


def _join_and_settle(ssid: str, controller: Any = None) -> Dict[str, Any]:
    radio = _radio_for(controller) if controller is not None else None
    join = _join_radio(radio, ssid) if radio else _join_ap(ssid)
    time.sleep(3)
    return join


# ---------- routes ---------------------------------------------------------------

@host_drone_bp.route("/tello/scan", methods=["POST"])
@route_exception_handler()
def tello_scan():
    """Scan for Tello-* APs visible to the host."""
    tellos = off_hub(_scan_tello_ssids)
    return jsonify({"success": True, "tellos": tellos, "count": len(tellos)})


@host_drone_bp.route("/tello/status", methods=["POST"])
@route_exception_handler()
def tello_status():
    """Is the drone's SDK link up? Cheap, local, no network I/O.

    Body:
        device_id  (str, required)

    This is what the Device page polls to tell "the drone is off" apart from "the
    drone is on but landed", so it must answer in a shape the frontend can act on
    and must NOT 404 when there is nothing to report.

    A device with no Tello controller is a legitimate answer — ``linked: false``,
    HTTP 200 — not a missing page. The tile's poll aborts on any non-2xx and lands
    in its catch-all error state, so a 404 here would hide the real state behind
    "could not check", which is exactly the bug this route exists to remove.
    """
    payload = get_json_payload(request)
    device_id, err = require_field(payload, "device_id")
    if err:
        return err

    controller = get_remote_controller_by_type(device_id, "tello")
    if controller is None:
        return jsonify({
            "success": False,
            "linked": False,
            "last_error": None,
            "error": f"no Tello controller for device {device_id}",
        }), 200

    # The controller already returns {success, linked, airborne, ip, last_error,
    # ...} — the exact contract the tile's StatusResponse expects. Two host facts
    # are added for the tile:
    #   associated — the host's Wi-Fi is on this slot's drone right now. `linked`
    #                only means the controller's UDP link is open, which happens on
    #                the first command, so the tile used to re-pair a paired drone
    #                every poll, and a second `command` often goes unanswered.
    #   video_live — fresh HLS segments exist. Until then the live playlist is
    #                missing (or a stale cold one is served) and the player shows
    #                a black tile, so the tile keeps its placeholder.
    status = controller.get_status()
    paired = status.get("ssid")
    status["associated"] = bool(paired) and off_hub(_associated_ssid, controller) == paired
    # On the drone's Wi-Fi but no fresh link (vpt-host restarted, drone power-cycled): relink
    # in the background so battery and temperature come back without a re-pair.
    if status["associated"]:
        controller.link_in_background()  # no-op while the link is fresh
    # The tile's single truth: on the drone's Wi-Fi AND its state datagrams are fresh (or it is
    # airborne). `linked` alone stays true after the drone is switched off (BUG-0519).
    status["connected"] = bool(status["associated"] and status.get("link_alive"))
    if not status["connected"] and not status.get("airborne"):
        status["telemetry"] = {}  # last reading of a drone that is gone
        # Off the drone's Wi-Fi: release the dead socket. (On its Wi-Fi but silent, the background
        # relink above re-enters SDK mode instead.)
        drop = getattr(controller, "drop_dead_link", None)
        if not status["associated"] and drop is not None and drop():
            status["linked"] = False
            status["last_error"] = getattr(controller, "last_error", None)
    status["video_live"] = _video_live(device_id)
    return jsonify(status), 200


def _video_live(device_id: str, max_age_s: float = 5.0) -> bool:
    """True when the device's live playlist was written in the last few seconds."""
    device = get_device_by_id(device_id)
    segments = device.get_capture_dir("segments") if device is not None else None
    if not segments:
        return False
    try:
        return time.time() - os.path.getmtime(os.path.join(segments, "output.m3u8")) < max_age_s
    except OSError:
        return False


@host_drone_bp.route("/tello/pair", methods=["POST"])
@route_exception_handler()
def tello_pair():
    """Join a Tello's AP, verify the SDK link, push the new endpoint into the controller.

    Body:
        device_id  (str, required)
        ssid       (str, required)            e.g. TELLO-C5B142
        tello_ip   (str, optional)            defaults to 192.168.10.1
        state_port (int, optional)            defaults to 8890
        video_port (int, optional)            defaults to 11111
        cmd_port   (int, optional)            defaults to 8889

    Returns:
        success, ssid, tello_ip, ports, and a 'link' dict with the verify outcome.
    """
    payload = get_json_payload(request)
    # require_field returns a (value, error_response) TUPLE. Testing that tuple
    # for truthiness is always true — a non-empty tuple — so every drone route
    # answered 400 {"error": ["<device_id>", null]} before reading a single
    # field. Unpack it the way every other host route does.
    device_id, err = require_field(payload, "device_id")
    if err:
        return err
    ssid, err = require_field(payload, "ssid")
    if err:
        return err

    if not TELLO_SSID_RE.match(ssid):
        return bad_request(f"ssid must look like TELLO-XXXXXX, got {ssid!r}")

    tello_ip: str = payload.get("tello_ip", "192.168.10.1")
    state_port: int = int(payload.get("state_port", 8890))
    video_port: int = int(payload.get("video_port", 11111))
    cmd_port: int = int(payload.get("cmd_port", 8889))

    # 1) Join the AP. Deliberately not fatal: the host is often already
    #    associated, and an unprivileged service may not be able to change
    #    the connection at all while still being perfectly able to reach the
    #    drone. The link check below is the real gate.
    #    Then wait for DHCP to settle. Both block, so off the hub.
    controller = get_remote_controller_by_type(device_id, "tello")
    if controller is not None:
        join = off_hub(_join_and_settle, ssid, controller)
    if controller is None:
        return jsonify({
            "success": False, "stage": "controller",
            "error": f"no Tello controller for device {device_id}",
            "ssid": ssid, "tello_ip": tello_ip,
        }), 404

    # 3) Point the controller at the drone (an endpoint change releases its old link;
    #    configure refuses while airborne) and open the link
    #    from the controller itself: `command` + `streamon` from its fixed port.
    controller.execute_command("configure", {
        "tello_ip": tello_ip,
        "state_port": state_port,
        "video_port": video_port,
        "cmd_port": cmd_port,
    })
    link = controller.execute_command("link", {})
    if not link.get("success"):
        return jsonify({
            "success": False, "stage": "link",
            "error": link.get("error") or "no reply from the drone",
            "ssid": ssid, "tello_ip": tello_ip, "join": join,
        }), 500

    # 4) Remember which drone is in this slot (the tile's scan sticks to it).
    controller.set_paired_ssid(ssid)

    return jsonify({
        "success": True,
        "ssid": ssid,
        "tello_ip": tello_ip,
        "state_port": state_port,
        "video_port": video_port,
        "cmd_port": cmd_port,
        "link": link,
        "join": join,
    })


@host_drone_bp.route("/tello/mission_pads", methods=["POST"])
@route_exception_handler()
def tello_mission_pads():
    """Set the room's Mission Pad layout for a Tello device (Tello Talent only).

    Body:
        device_id    (str, required)
        mission_pads (dict, required)   e.g. {"1": [200, 100, 0], "2": [400, 100, 0]}

    Pass an empty dict or omit to disable snapping (pose falls back to dead reckoning).
    """
    payload = get_json_payload(request)
    device_id, err = require_field(payload, "device_id")
    if err:
        return err
    if "mission_pads" not in payload:
        return bad_request("mission_pads is required (use {} to disable)")

    device_id: str = payload["device_id"]
    raw = payload.get("mission_pads") or {}
    # Normalise: JSON object keys are strings; controller expects ints. Coerce.
    pads: dict = {}
    for k, v in raw.items():
        try:
            pid = int(k)
            x, y, z = (float(v[0]), float(v[1]), float(v[2]))
            pads[pid] = (x, y, z)
        except (TypeError, ValueError, KeyError, IndexError):
            return bad_request(f"mission_pads entry {k!r} must be [x, y, z] numbers")

    controller = get_remote_controller_by_type(device_id, "tello")
    if controller is None:
        return jsonify({
            "success": False,
            "error": f"no Tello controller for device {device_id}",
        }), 404

    if not hasattr(controller, "set_mission_pads"):
        return jsonify({
            "success": False,
            "error": f"Tello controller on {device_id} does not support mission_pads",
        }), 400

    controller.set_mission_pads(pads)
    return jsonify({
        "success": True,
        "device_id": device_id,
        "mission_pads": {str(k): list(v) for k, v in pads.items()},
        "enabled": bool(pads),
    })


@host_drone_bp.route("/tello/flight_summary", methods=["POST"])
@route_exception_handler()
def tello_flight_summary():
    """Return the per-flight summary for a Tello device (rows, peak altitude, distance, etc.).

    The script (or Atlas) calls this after a flight to attach the path and
    the small numbers to the test report via PlatformReporter.flight_log_step.
    """
    payload = get_json_payload(request)
    device_id, err = require_field(payload, "device_id")
    if err:
        return err
    controller = get_remote_controller_by_type(device_id, "tello")
    if controller is None:
        return jsonify({
            "success": False,
            "error": f"no Tello controller for device {device_id}",
        }), 404
    summary = controller.get_flight_summary()
    if summary is None:
        return jsonify({
            "success": True,
            "device_id": device_id,
            "summary": None,
            "log_path": getattr(controller, "last_log_path", None),
        })
    return jsonify({
        "success": True,
        "device_id": device_id,
        "summary": summary,
        "log_path": summary.get("log_path"),
    })


@host_drone_bp.route("/tello/command_history", methods=["POST"])
@route_exception_handler()
def tello_command_history():
    """Driving history of a Tello: every command sent (takeoff, land, move, rotate, stick changes, refused ones), newest last.

    Body: device_id, optional limit (default 100, at most 500), flight (the n-th takeoff since the controller started), since_seq.
    """
    payload = get_json_payload(request)
    device_id, err = require_field(payload, "device_id")
    if err:
        return err
    controller = get_remote_controller_by_type(device_id, "tello")
    if controller is None:
        return jsonify({"success": False, "error": f"no Tello controller for device {device_id}"}), 404
    try:
        limit = min(500, max(1, int(payload.get("limit", 100))))
        flight = payload.get("flight")
        flight = None if flight in (None, "") else int(flight)
        since_seq = int(payload.get("since_seq", 0))
    except (TypeError, ValueError):
        return jsonify({"success": False, "error": "limit, flight and since_seq must be integers"}), 400
    log = controller.command_log
    return jsonify({"success": True, "device_id": device_id, "commands": log.history(limit, flight, since_seq),
                    "flight": log.flight, "log_path": log.path})


@host_drone_bp.route("/tello/last_known", methods=["POST"])
@route_exception_handler()
def tello_last_known():
    """Return the last seen state and pose for a Tello device.

    Used by Atlas (MCP) to locate the drone after
    a flight. Returns the freshest state datagram and the freshest pose
    (snapped if a Mission Pad was visible at the time, dead-reckoned
    otherwise), plus how stale they are. After a flight ends, this is
    the last point we saw the Tello — if the link is still up, also
    returns the link's age.
    """
    payload = get_json_payload(request)
    device_id, err = require_field(payload, "device_id")
    if err:
        return err
    controller = get_remote_controller_by_type(device_id, "tello")
    if controller is None:
        return jsonify({
            "success": False,
            "error": f"no Tello controller for device {device_id}",
        }), 404

    state = controller._state() or {}
    pose = controller.pose()
    state_age_s = controller.client.state_age_s() if controller.client is not None else None
    return jsonify({
        "success": True,
        "device_id": device_id,
        "ip": controller.tello_ip,
        "state_port": controller.state_port,
        "airborne": controller.airborne,
        "state": state,
        "state_age_s": state_age_s,
        "pose": ({"x": pose.x, "y": pose.y, "z": pose.z, "yaw": pose.yaw_deg}
                 if pose is not None else None),
        "log_path": controller.last_log_path,
    })
