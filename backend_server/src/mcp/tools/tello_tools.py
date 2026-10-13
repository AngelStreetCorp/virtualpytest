"""
Tello Tools - Ryze/DJI Tello drone control for AI agents (Atlas / Forge).

Each method talks to the host's ``TelloRemoteController`` via the server
``/server/drone/tello/execute`` proxy, which in turn forwards to
``/host/remote/executeCommand`` on vpt-host. The controller's safety guard
(geofence, ceiling, battery floor, temperature, separation, keepalive) is
applied server-side before every SDK command — the agent only sees the
verdict, never the raw SDK.

Tools:
  takeoff, land, emergency, move, rotate, flip, set_speed, get_telemetry

All methods take ``host_name`` and ``device_id`` (the VPT device entry
where the Tello is registered, model ``tello``). Additional parameters
are command-specific.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from ..utils.api_client import MCPAPIClient
from ..utils.mcp_formatter import MCPFormatter
from shared.src.lib.config.constants import get_team_id


MOVE_DIRECTIONS = ("forward", "back", "left", "right", "up", "down")
ROTATE_DIRECTIONS = ("cw", "ccw")
FLIP_DIRECTIONS = ("f", "b", "l", "r")


class TelloTools:
    """Tello drone control tools for AI agents (Atlas, Forge, ...)."""

    def __init__(self, api_client: MCPAPIClient):
        self.api = api_client
        self.formatter = MCPFormatter()

    # ---------- internals ---------------------------------------------------------

    def _require_host_device(self, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Return a formatted error response if host_name or device_id is missing, else None."""
        if not params.get("host_name") or not params.get("device_id"):
            return self.formatter.format_api_response({
                "success": False,
                "error": "host_name and device_id are required",
            })
        return None

    def _execute(self, params: Dict[str, Any], command: str, cmd_params: Dict[str, Any]) -> Dict[str, Any]:
        """Forward a high-level Tello command to the host controller."""
        err = self._require_host_device(params)
        if err is not None:
            return err
        data = {
            "host_name": params["host_name"],
            "device_id": params["device_id"],
            "command": command,
            "params": cmd_params,
        }
        return self.api.post(
            "/server/drone/tello/execute",
            data=data,
            params={"team_id": params.get("team_id", get_team_id())},
        )

    # ---------- public tools -----------------------------------------------------

    def takeoff(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Take off and hover (~80 cm).

        Refused if battery < 40% or temperature >= 85 C. The Tello's
        in-air 15-second watchdog is held off by the controller's
        keepalive; you don't need to poll.

        Example: takeoff(host_name='vpt-pi4', device_id='device5')

        Args:
            params: {
                'host_name': str (REQUIRED),
                'device_id': str (REQUIRED)
            }

        Returns:
            MCP-formatted response. On success, ``output_data.telemetry``
            includes battery, height, temperature.
        """
        return self._execute(params, "takeoff", {})

    def land(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Land the Tello at its current position. Always allowed, even when
        the safety guard would otherwise refuse (the guard must never
        trap a drone in the air).

        Example: land(host_name='vpt-pi4', device_id='device5')

        Args:
            params: {
                'host_name': str (REQUIRED),
                'device_id': str (REQUIRED)
            }

        Returns:
            MCP-formatted response.
        """
        return self._execute(params, "land", {})

    def emergency(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        EMERGENCY STOP. Cuts the motors — the drone drops. Never sent
        automatically. Use only as a last resort, never as a substitute
        for ``land``.

        Example: emergency(host_name='vpt-pi4', device_id='device5')

        Args:
            params: {
                'host_name': str (REQUIRED),
                'device_id': str (REQUIRED)
            }

        Returns:
            MCP-formatted response. Reply is ``ok`` on success.
        """
        return self._execute(params, "emergency", {})

    def move(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Move the Tello in a direction by 20-500 cm. The host's
        ``SafetyGuard`` checks the move against the geofence, ceiling,
        battery, and the peer drone before it is sent; refused moves
        return ``success: false`` with a ``reason``.

        Example: move(host_name='vpt-pi4', device_id='device5',
                      direction='forward', cm=50)

        Args:
            params: {
                'host_name': str (REQUIRED),
                'device_id': str (REQUIRED),
                'direction': str (REQUIRED, one of forward|back|left|right|up|down),
                'cm': int (REQUIRED, 20..500)
            }

        Returns:
            MCP-formatted response. On a guard clip, ``clipped_from``
            names the requested move and ``sent`` is what was actually
            sent.
        """
        direction = str(params.get("direction", "")).lower()
        try:
            cm = int(params.get("cm"))
        except (TypeError, ValueError):
            return self.formatter.format_api_response({
                "success": False, "error": "cm must be an integer (20..500)",
            })
        if direction not in MOVE_DIRECTIONS:
            return self.formatter.format_api_response({
                "success": False,
                "error": f"direction must be one of {', '.join(MOVE_DIRECTIONS)}",
            })
        if not 20 <= cm <= 500:
            return self.formatter.format_api_response({
                "success": False, "error": f"cm {cm} out of range 20..500",
            })
        return self._execute(params, "move", {"direction": direction, "cm": cm})

    def rotate(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Rotate the Tello clockwise or counter-clockwise by 1-360 degrees.

        Example: rotate(host_name='vpt-pi4', device_id='device5',
                        direction='cw', deg=30)

        Args:
            params: {
                'host_name': str (REQUIRED),
                'device_id': str (REQUIRED),
                'direction': str (REQUIRED, one of cw|ccw),
                'deg': int (REQUIRED, 1..360)
            }

        Returns:
            MCP-formatted response.
        """
        direction = str(params.get("direction", "")).lower()
        try:
            deg = int(params.get("deg"))
        except (TypeError, ValueError):
            return self.formatter.format_api_response({
                "success": False, "error": "deg must be an integer (1..360)",
            })
        if direction not in ROTATE_DIRECTIONS:
            return self.formatter.format_api_response({
                "success": False, "error": "direction must be 'cw' or 'ccw'",
            })
        if not 1 <= deg <= 360:
            return self.formatter.format_api_response({
                "success": False, "error": f"deg {deg} out of range 1..360",
            })
        return self._execute(params, "rotate", {"direction": direction, "deg": deg})

    def flip(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Flip the Tello in a direction. There is a 5-second cooldown
        between flips on the firmware; a flip inside the cooldown is
        refused with a Tello ``error`` reply, which the tool surfaces
        as ``success: false``.

        Example: flip(host_name='vpt-pi4', device_id='device5', direction='f')

        Args:
            params: {
                'host_name': str (REQUIRED),
                'device_id': str (REQUIRED),
                'direction': str (REQUIRED, one of f|b|l|r)
            }

        Returns:
            MCP-formatted response.
        """
        direction = str(params.get("direction", "")).lower()
        if direction not in FLIP_DIRECTIONS:
            return self.formatter.format_api_response({
                "success": False, "error": "direction must be one of f, b, l, r",
            })
        # The controller's _to_sdk maps the high-level "flip" verb to the
        # raw SDK text "flip <dir>".
        return self._execute(params, "sdk", {"cmd": f"flip {direction}"})

    def set_speed(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Set the Tello's flight speed in cm/s (10-100). The value sticks
        for the next moves until changed. Default after power-on is 100.

        Example: set_speed(host_name='vpt-pi4', device_id='device5', cm_s=50)

        Args:
            params: {
                'host_name': str (REQUIRED),
                'device_id': str (REQUIRED),
                'cm_s': int (REQUIRED, 10..100)
            }

        Returns:
            MCP-formatted response.
        """
        try:
            cm_s = int(params.get("cm_s"))
        except (TypeError, ValueError):
            return self.formatter.format_api_response({
                "success": False, "error": "cm_s must be an integer (10..100)",
            })
        if not 10 <= cm_s <= 100:
            return self.formatter.format_api_response({
                "success": False, "error": f"cm_s {cm_s} out of range 10..100",
            })
        return self._execute(params, "sdk", {"cmd": f"speed {cm_s}"})

    def get_telemetry(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Read live Tello telemetry: battery, height, temperature, and the
        controller's dead-reckoned pose. Useful before a flight to
        confirm the guard won't refuse a takeoff (battery >= 40%,
        temperature < 85 C).

        Example: get_telemetry(host_name='vpt-pi4', device_id='device5')

        Args:
            params: {
                'host_name': str (REQUIRED),
                'device_id': str (REQUIRED)
            }

        Returns:
            MCP-formatted response. ``output_data.telemetry`` is the
            parsed state datagram (bat, h, temph, tof, time, ...);
            ``output_data.pose`` is the dead-reckoned {x, y, z, yaw}.
        """
        return self._execute(params, "get_telemetry", {})
