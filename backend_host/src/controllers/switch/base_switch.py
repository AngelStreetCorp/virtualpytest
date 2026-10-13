"""
Base Switch Controller (TASK-31 follow-up).

Placeholder no-op controller. Real implementations (HDMI matrix over serial
or TCP, sys-botbase/usb-botbase for Nintendo Switch) inherit from this and
override the methods that actually drive the hardware.

Today: every method returns a stub response so the controller_manager can
load the device even before the real controller is built. When the first
real implementation lands, replace these stubs with the real serial /
USB / TCP traffic.
"""

from typing import Dict, Any, Optional


class BaseSwitchController:
    """No-op base class for switch controllers."""

    def __init__(self, controller_name: str = "Base Switch Controller", **kwargs):
        self.controller_name = controller_name
        self.device_id = kwargs.get("device_id", "unknown")
        self.kwargs = kwargs
        print(f"SWITCH[{self.controller_name}]: Initialized as placeholder — no real controller yet")

    def get_status(self) -> Dict[str, Any]:
        """Return placeholder status."""
        return {
            "success": True,
            "controller_type": "switch",
            "is_implemented": False,
            "controller_name": self.controller_name,
            "device_id": self.device_id,
            "message": "Switch controller not yet implemented",
        }

    def switch_input(self, input_number: int, **kwargs) -> bool:
        """
        Switch to the given HDMI input. Placeholder — real implementation
        (matrix / KVM / sys-botbase) overrides this.

        Args:
            input_number: 1-based input number on the switch.

        Returns:
            True on success, False on failure.
        """
        print(f"SWITCH[{self.controller_name}]: switch_input({input_number}) — placeholder, no-op")
        return False

    def list_inputs(self) -> Dict[str, Any]:
        """List available inputs. Placeholder."""
        return {"success": False, "error": "switch controller not implemented", "inputs": []}

    def send_command(self, command: str, **kwargs) -> Dict[str, Any]:
        """
        Send a generic command. Placeholder — real sys-botbase / matrix
        controllers will override this.

        Args:
            command: command name (e.g. 'press_a', 'select_input').

        Returns:
            Result dict with success + response payload.
        """
        print(f"SWITCH[{self.controller_name}]: send_command({command!r}) — placeholder, no-op")
        return {"success": False, "error": "switch controller not implemented"}