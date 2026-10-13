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
  2. We verify the link: ping the Tello, then send a plain-text
     ``command`` and read the reply (Tello EDU/TT binary-mode ack is
     accepted as well, same fix as ``shared/src/lib/drone/tello.py``).
  3. We push the new endpoint into the device's TelloRemoteController
     via ``configure`` so the next command re-binds on the new IP/ports.
"""

from __future__ import annotations

import logging
import re
import socket
import subprocess
import time
from typing import Any, Dict, List, Optional

from flask import Blueprint, jsonify, request

from backend_host.src.lib.utils.host_utils import (
    get_remote_controller_by_type,
)
from backend_host.src.lib.utils.route_decorators import route_exception_handler
from backend_host.src.lib.utils.route_request import get_json_payload, require_field
from backend_host.src.lib.utils.route_response import bad_request


logger = logging.getLogger(__name__)

host_drone_bp = Blueprint("host_drone", __name__, url_prefix="/host/drone")


TELLO_SSID_RE = re.compile(r"^TELLO-[0-9A-Fa-f]{6}$")


# ---------- helpers --------------------------------------------------------------

def _scan_tello_ssids() -> List[Dict[str, Any]]:
    """Return the Tello-* APs visible to the host's wlan0."""
    _run_nmcli(["device", "wifi", "rescan"], 15)
    time.sleep(2)
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


def _verify_link(tello_ip: str, cmd_port: int, timeout_s: float = 5.0) -> Dict[str, Any]:
    """Send 'command' to the Tello and confirm a non-empty reply.

    A Tello in binary mode (Tello EDU/Tello Talent, or a plain Tello that
    was put into binary by a prior client) answers with a 0xcc... packet
    instead of the text 'ok'. Any non-empty reply is treated as success
    (same fix as the Tello client itself). The script is not yet imported
    here because this is a stdlib-only check; we keep it in a single
    short-lived socket.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", 0))
    sock.settimeout(timeout_s)
    try:
        sock.sendto(b"command", (tello_ip, cmd_port))
        data, _ = sock.recvfrom(2048)
    except socket.timeout:
        return {"ok": False, "reason": f"no reply from {tello_ip}:{cmd_port} in {timeout_s}s"}
    finally:
        sock.close()
    if not data:
        return {"ok": False, "reason": "empty reply"}
    return {"ok": True, "bytes": len(data)}


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


# ---------- routes ---------------------------------------------------------------

@host_drone_bp.route("/tello/scan", methods=["POST"])
@route_exception_handler()
def tello_scan():
    """Scan for Tello-* APs visible to the host."""
    tellos = _scan_tello_ssids()
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
    # ...} — the exact contract the tile's StatusResponse expects.
    return jsonify(controller.get_status()), 200


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
    join = _join_ap(ssid)

    # 2) Wait for DHCP to settle.
    time.sleep(3)

    # 3) Verify the link. The Tello in binary mode answers with a 0xcc
    # packet; the helper accepts any non-empty reply.
    link = _verify_link(tello_ip, cmd_port)
    if not link["ok"]:
        return jsonify({
            "success": False, "stage": "link",
            "error": link["reason"], "ssid": ssid, "tello_ip": tello_ip,
            "join": join,
        }), 500

    # 4) Push the new endpoint into the device's TelloRemoteController.
    controller = get_remote_controller_by_type(device_id, "tello")
    if controller is None:
        return jsonify({
            "success": False, "stage": "controller",
            "error": f"no Tello controller for device {device_id}",
            "ssid": ssid, "tello_ip": tello_ip,
        }), 404

    # Use the existing _configure surface so the safety guard is rebuilt
    # consistently. tello_ip / state_port / video_port / cmd_port are
    # accepted by _configure and the link is released so the next
    # command re-binds on the new endpoint.
    controller.execute_command("configure", {
        "tello_ip": tello_ip,
        "state_port": state_port,
        "video_port": video_port,
        "cmd_port": cmd_port,
    })

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


@host_drone_bp.route("/tello/last_known", methods=["POST"])
@route_exception_handler()
def tello_last_known():
    """Return the last seen state and pose for a Tello device.

    Used by the 'Find my Tello' UI and by Atlas to locate the drone after
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
