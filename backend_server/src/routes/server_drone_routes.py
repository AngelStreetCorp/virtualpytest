"""
Server Drone Routes

Server-side drone proxy endpoints. The Tello tools in
``backend_server/src/mcp/tools/tello_tools.py`` call these routes,
which forward to the host's ``/host/remote/executeCommand`` so the
host's ``TelloRemoteController`` (and its safety guard) handles the
command.
"""

from flask import Blueprint, jsonify, request

from backend_server.src.lib.utils.route_utils import proxy_to_host_with_params


server_drone_bp = Blueprint("server_drone", __name__, url_prefix="/server/drone")


@server_drone_bp.route("/tello/execute", methods=["POST"])
def tello_execute():
    """Forward a Tello command to the host's ``TelloRemoteController``.

    The request body is forwarded as-is to the host's
    ``/host/remote/executeCommand``. The host expects ``device_id``,
    ``command`` and ``params``; the server route resolves the
    ``host_name`` (from the body or from a query param) into a host
    endpoint and proxies.
    """
    print("[@route:server_drone:tello_execute] Forwarding Tello command")
    request_data = request.get_json() or {}

    host_name = request_data.get("host_name")
    if not host_name:
        return jsonify({
            "success": False,
            "error": "host_name is required",
        }), 400

    # The host doesn't need its own name echoed back; strip it.
    host_payload = {
        "device_id": request_data.get("device_id"),
        "command": request_data.get("command"),
        "params": request_data.get("params") or {},
    }

    response_data, status_code = proxy_to_host_with_params(
        "/host/remote/executeCommand", "POST", host_payload, {},
    )
    return jsonify(response_data), status_code


@server_drone_bp.route("/tello/status", methods=["GET"])
def tello_status():
    """Return the Tello controller's status (link, airborne, IP, ports).

    Proxies to the host's drone route. This used to ask for
    ``/host/remote/getStatus``, which has never existed — the ``/host/remote``
    blueprint exposes only takeScreenshot, screenshotAndDump, getApps,
    tapCoordinates, executeCommand, dumpUi and getOrientation. Every call 404'd,
    and because the tile's poll aborts on any non-2xx, the drone tile could never
    get past its first question and never reached the scan. See BUG-0500.
    """
    host_name = request.args.get("host_name")
    device_id = request.args.get("device_id")
    if not host_name or not device_id:
        return jsonify({
            "success": False,
            "error": "host_name and device_id are required",
        }), 400

    response_data, status_code = proxy_to_host_with_params(
        "/host/drone/tello/status", "POST",
        {"device_id": device_id}, {},
    )
    return jsonify(response_data), status_code


# =====================================================
# PAIRING FLOW
# =====================================================

@server_drone_bp.route("/tello/scan", methods=["POST"])
def tello_scan():
    """Scan the host for Tello-* APs (no device_id needed; the host scans its wlan)."""
    print("[@route:server_drone:tello_scan] Scanning host for Tello APs")
    request_data = request.get_json() or {}
    host_name = request_data.get("host_name") or request.args.get("host_name")
    if not host_name:
        return jsonify({
            "success": False,
            "error": "host_name is required",
        }), 400

    # The host route doesn't need a device_id, so the request body is empty.
    response_data, status_code = proxy_to_host_with_params(
        "/host/drone/tello/scan", "POST", {}, {},
    )
    return jsonify(response_data), status_code


@server_drone_bp.route("/tello/pair", methods=["POST"])
def tello_pair():
    """Pair a Tello: join its AP, verify the SDK link, push the new endpoint
    into the device's TelloRemoteController.

    Body:
        host_name   (str, required)
        device_id   (str, required)
        ssid        (str, required)            e.g. TELLO-C5B142
        tello_ip    (str, optional)            defaults to 192.168.10.1
        state_port  (int, optional)            defaults to 8890
        video_port  (int, optional)            defaults to 11111
        cmd_port    (int, optional)            defaults to 8889
    """
    print(f"[@route:server_drone:tello_pair] Pairing Tello")
    request_data = request.get_json() or {}
    host_name = request_data.get("host_name")
    if not host_name:
        return jsonify({
            "success": False,
            "error": "host_name is required",
        }), 400
    if not request_data.get("device_id"):
        return jsonify({
            "success": False,
            "error": "device_id is required",
        }), 400
    if not request_data.get("ssid"):
        return jsonify({
            "success": False,
            "error": "ssid is required",
        }), 400

    # Forward the full request body to the host. The host does the
    # nmcli join + SDK link verify + controller.endpoint swap.
    response_data, status_code = proxy_to_host_with_params(
        "/host/drone/tello/pair", "POST", request_data, {},
    )
    return jsonify(response_data), status_code


@server_drone_bp.route("/tello/mission_pads", methods=["POST"])
def tello_mission_pads():
    """Set the Mission Pad layout for a Tello device on a host (Tello Talent only).

    Body:
        host_name    (str, required)
        device_id    (str, required)
        mission_pads (dict, required)  e.g. {"1": [200, 100, 0], "2": [400, 100, 0]}
    """
    request_data = request.get_json() or {}
    host_name = request_data.get("host_name")
    if not host_name:
        return jsonify({"success": False, "error": "host_name is required"}), 400
    if not request_data.get("device_id"):
        return jsonify({"success": False, "error": "device_id is required"}), 400
    if "mission_pads" not in request_data:
        return jsonify({"success": False, "error": "mission_pads is required"}), 400

    response_data, status_code = proxy_to_host_with_params(
        "/host/drone/tello/mission_pads", "POST", request_data, {},
    )
    return jsonify(response_data), status_code


@server_drone_bp.route("/tello/flight_summary", methods=["POST"])
def tello_flight_summary():
    """Per-flight summary for a Tello device (rows, peak altitude, total distance, etc.).

    The script (or Atlas) calls this after a flight, then forwards the
    returned dict to ``PlatformReporter.flight_log_step`` to attach the
    per-flight log to the test report.
    """
    request_data = request.get_json() or {}
    host_name = request_data.get("host_name")
    if not host_name:
        return jsonify({"success": False, "error": "host_name is required"}), 400
    if not request_data.get("device_id"):
        return jsonify({"success": False, "error": "device_id is required"}), 400
    response_data, status_code = proxy_to_host_with_params(
        "/host/drone/tello/flight_summary", "POST", request_data, {},
    )
    return jsonify(response_data), status_code


@server_drone_bp.route("/tello/command_history", methods=["POST"])
def tello_command_history():
    """Driving history of a Tello device: every command sent, newest last (see the host route)."""
    request_data = request.get_json() or {}
    if not request_data.get("host_name"):
        return jsonify({"success": False, "error": "host_name is required"}), 400
    if not request_data.get("device_id"):
        return jsonify({"success": False, "error": "device_id is required"}), 400
    response_data, status_code = proxy_to_host_with_params(
        "/host/drone/tello/command_history", "POST", request_data, {},
    )
    return jsonify(response_data), status_code


@server_drone_bp.route("/tello/last_known", methods=["POST"])
def tello_last_known():
    """Last-seen state + pose for a Tello device (Find my Tello / locate it).

    After a flight or after the link drops, this is the freshest point
    we have for the drone. Includes ``state_age_s`` so the panel can warn
    when the link is stale.
    """
    request_data = request.get_json() or {}
    host_name = request_data.get("host_name")
    if not host_name:
        return jsonify({"success": False, "error": "host_name is required"}), 400
    if not request_data.get("device_id"):
        return jsonify({"success": False, "error": "device_id is required"}), 400
    response_data, status_code = proxy_to_host_with_params(
        "/host/drone/tello/last_known", "POST", request_data, {},
    )
    return jsonify(response_data), status_code


# ---------------------------------------------------------------------------------------------------------------
# Voice (TASK-160): the executor shared by Actions > Voice (agent/voice_device.py) and the Atlas voice path.
# Logic: lib/utils/drone_voice.py. There is no /tello/voice route any more: Actions > Voice is the one entry point.

_voice_executor = None


def _voice():
    global _voice_executor
    if _voice_executor is None:
        from backend_server.src.lib.utils import drone_voice
        from backend_server.src.lib.utils.lock_utils import get_device_lock_info
        from backend_server.src.lib.utils.server_utils import get_host_manager
        from shared.src.lib.database import audit_events_db
        from shared.src.lib.utils.build_url_utils import call_host

        def send(host_name, device_id, command, params):
            host_info = get_host_manager().get_host(host_name)
            if not host_info:
                return {"success": False, "error": f'host "{host_name}" not found'}
            data, status = call_host(host_info, "/host/remote/executeCommand", "POST",
                                     {"device_id": device_id, "command": command, "params": params}, timeout=30)
            return data if isinstance(data, dict) else {"success": False, "error": f"host answered {status}"}

        def lock_ok(host_name, device_id, caller):
            return drone_voice.holds_lock(get_device_lock_info(host_name, device_id), caller)

        def audit(event):
            audit_events_db.record(category="control", action="drone.voice", actor_kind="user",
                                   actor_id=(event.get("caller") or {}).get("user_id"),
                                   target=f'{event.get("host_name")}/{event.get("device_id")}',
                                   outcome="ok" if event.get("decision") in ("sent", "answered") else "denied",
                                   meta={k: event.get(k) for k in ("transcript", "parsed", "decision", "reason",
                                                                   "drone_reply", "battery")})

        _voice_executor = drone_voice.VoiceExecutor(send, lock_ok, audit)
    return _voice_executor
