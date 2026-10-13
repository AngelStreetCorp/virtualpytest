"""
Switch controllers package (TASK-31).

The `switch` controller slot drives input on a device that has no remote:
- `hdmi_switch` (base_switch.py): no-op placeholder for a future HDMI matrix.
- `bluetooth_procon` (bluetooth_procon.py): a Nintendo Switch driven as an
  emulated Bluetooth Pro Controller. The Bluetooth side runs in the root
  daemon procon/procon_daemon.py (vpt-procon.service, nxbt venv); the
  controller calls its local HTTP API.
"""
