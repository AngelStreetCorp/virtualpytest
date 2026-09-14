# Writing Test Scripts

How to create test scripts that integrate with the VirtualPyTest framework: parameter declaration, target rules, step reporting, and metadata.

---

## Quick Start

Every script uses the `@script` decorator from `shared.src.lib.executors.script_decorators`:

```python
#!/usr/bin/env python3
import os, sys

current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(os.path.dirname(current_dir))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from shared.src.lib.executors.script_decorators import script, get_context, get_args

_script_args = [
    "--timeout:int:30",
    "--mode:str:auto:auto|fast|slow",
]

@script("my_script", "Description of what this script does")
def main():
    args = get_args()
    context = get_context()

    # Your logic here...

    context.overall_success = True
    return True

main._script_args = _script_args
main._target_rules = {
    "target_type": "host",
    "host_os": "all",
    "device_model": "all",
}

if __name__ == "__main__":
    main()
```

---

## `_script_args` — Parameter Declaration

The `_script_args` list declares parameters that appear in the **Run Tests** UI. The backend parses this list and sends parameter metadata to the frontend for rendering.

### Format

```
"--param_name:type:default:choices"
```

| Part | Required | Description |
|------|----------|-------------|
| `--param_name` | Yes | Parameter name (dashes allowed, e.g., `--max-iteration`) |
| `type` | Yes | Data type: `str`, `int`, `bool` |
| `default` | No | Default value (empty string = no default) |
| `choices` | No | Pipe-separated list of allowed values |

### Types and UI Rendering

| Type | Frontend Control | Notes |
|------|-----------------|-------|
| `str` | Text field | Default rendering |
| `str` with `choices` | Dropdown (Select) | Shows choices as menu items |
| `int` | Number input | Step = 1, numeric keyboard on mobile |
| `bool` | True/False dropdown | Values: `true` or `false` |

Parameters named `password`, `secret`, or `token` (case-insensitive) are automatically rendered as **masked inputs**.

### Examples

```python
_script_args = [
    # Simple string with default
    "--gateway_url:str:https://192.168.1.1",

    # String with choices → dropdown
    "--network_mode:str:eth:eth|wifi",
    "--wan_mode:str:kpiWanIp:kpiWanIp|kpiWanIpv6",
    "--protocol:str:icmp:icmp|tcp|udp",
    "--gateway_profile:str:auto:auto|example_mv3|example_sib|example_sib3",

    # Integer → number input
    "--port:int:993",
    "--count:int:5",
    "--timeout:int:30",

    # Boolean → true/false dropdown
    "--headless:bool:false",
    "--audio-analysis:bool:false",

    # Password → masked text field
    "--password:str:myDefaultPassword",

    # Empty default (user must fill in)
    "--email:str:",
    "--ssid:str:",
]
```

### Framework Parameters

The parameters `--host` and `--device` are **framework-level** — they are added automatically by the execution engine based on the selected target. Do **not** declare them in `_script_args`.

---

## `_target_rules` — Target Compatibility

Controls which targets (hosts/devices) are shown in the Run Tests UI when this script is selected.

```python
main._target_rules = {
    "target_type": "host",       # "host" | "device" | "all"
    "host_os": "windows",        # "all" | "linux" | "windows" | "mac"
    "device_model": "all",       # "all" | model name | "model1|model2"
}
```

| Field | Values | Description |
|-------|--------|-------------|
| `target_type` | `host`, `device`, `all` | `host` = runs on the host itself; `device` = needs a connected device; `all` = either |
| `host_os` | `all`, `linux`, `windows`, `mac` | Filter hosts by OS (detected from `platform.system()`) |
| `device_model` | `all`, or model name(s) | Filter by device model. Pipe-separated for multiple: `android_tv\|android_mobile` |

### Examples

```python
# Windows-only host script
main._target_rules = {"target_type": "host", "host_os": "windows", "device_model": "all"}

# Any device (Android TV or mobile)
main._target_rules = {"target_type": "device", "host_os": "all", "device_model": "android_tv|android_mobile"}

# Any target, any OS
main._target_rules = {"target_type": "all", "host_os": "all", "device_model": "all"}
```

---

## Step Reporting — `record_step_immediately()`

For detailed report visibility, record steps with commands and verifications. Each step appears as a collapsible row in the HTML test report.

```python
context.record_step_immediately({
    "message": "Check Wi-Fi interface (netsh wlan show interfaces)",
    "success": result["success"],
    "actions": [
        {"command": "netsh wlan show interfaces"}
    ],
    "verifications": [
        {"success": True, "label": "Wi-Fi connected", "details": "Interface: Wi-Fi, Signal: 85%"},
        {"success": False, "label": "Signal strength", "details": "Expected > 50%, got 30%"},
    ],
})
```

| Field | Type | Description |
|-------|------|-------------|
| `message` | string | Step title shown in the report |
| `success` | bool | Overall step pass/fail |
| `actions` | list | Commands executed — `{"command": "..."}` |
| `verifications` | list | Check results — `{"success": bool, "label": "...", "details": "..."}` |

### Pattern: Raw Command + Raw Output

For debuggability, always capture and expose the raw command and its output:

```python
cmd = "netsh wlan show interfaces"
result = subprocess.run(cmd.split(), capture_output=True, text=True, timeout=20)
output = (result.stdout or "") + ("\n" + result.stderr if result.stderr else "")

# Print for logs
print(f"\n{'='*80}")
print(f"[step] Running command: {cmd}")
print(f"{'='*80}")
print(output or "(empty)")
print(f"{'='*80}\n")

# Record step with command
context.record_step_immediately({
    "message": "Check Wi-Fi interface",
    "success": result.returncode == 0,
    "actions": [{"command": cmd}],
    "verifications": [{"success": result.returncode == 0, "label": "Command succeeded", "details": f"exit={result.returncode}"}],
})

# Store in metadata for report access
return {"success": True, "raw_cmd": cmd, "raw_output": output, ...}
```

---

## Metadata and Execution Summary

### `context.metadata`

Dict stored in the `script_results` database row. Used for KPI dashboards (Grafana), report details, and debugging.

```python
context.metadata = {
    "timestamp": datetime.now().isoformat(),
    "host_name": context.host.host_name,
    "script_name": "my_script",
    "input_values": {
        "timeout": timeout,
        "mode": mode,
    },
    # Raw command/response for debugging
    "raw_cmd": cmd,
    "raw_output": output,
    # KPIs for Grafana
    "responseTime": response_time_ms,
    "serviceAvailability": 1,
}
```

### `context.execution_summary`

Multi-line string shown in the report header:

```python
context.execution_summary = (
    "MY SCRIPT SUMMARY\n"
    f"Host: {context.host.host_name}\n"
    f"Command: {cmd}\n"
    f"Response Time: {response_time_ms}ms\n"
    f"Result: {'SUCCESS' if success else 'FAILED'}"
)
```

### `context.error_message`

Set on failure to explain what went wrong:

```python
if not success:
    context.error_message = "Connection timed out after 30s"
```

---

## Locked Targets and Queuing

When running a script on a locked target (another script is already executing):

- The script is **automatically queued** via the deployment scheduler.
- It will execute once the target becomes free (FIFO order).
- The **Device Queue** panel appears in the UI showing queued scripts.
- Unlocked targets execute immediately in parallel as usual.

No user interaction needed — the same mechanism used for multi-script runs handles the queuing.

---

## File Organization

Place scripts in `test_scripts/` subdirectories by category:

```
test_scripts/
├── gw/           # Gateway/network scripts (speedtest, ping, DNS, IMAP)
├── web/          # Web browser scripts (YouTube, Netflix, Facebook)
├── tv/           # TV/STB scripts (zapping, navigation)
├── mobile/       # Mobile device scripts (camera, apps)
├── android/      # Android-specific scripts
├── vpt/          # VirtualPyTest self-test / smoke scripts
├── api/          # API test scripts
└── test_campaign/ # Campaign runner scripts (shown in Campaigns tab, not Tests tab)
```

Scripts in `test_campaign/` are filtered out of the Tests tab and only appear in the Campaigns tab.

---

## Reference Scripts

| Script | Demonstrates |
|--------|-------------|
| `gw/windows_lan_connection_information.py` | Full pattern: raw_cmd, raw_output, record_step_immediately, metadata KPIs |
| `gw/email_imap_login.py` | Multi-step with connectivity + auth, masked passwords, choices |
| `gw/gw_network_connect.py` | Choices dropdown (`eth\|wifi`) |
| `gw/superping.py` | Choices + integer params, multi-family network testing |
| `tv/fullzap.py` | Boolean params, iterations, userinterface framework param |
| `web/youtube_video_check.py` | Browser automation with headless toggle |
