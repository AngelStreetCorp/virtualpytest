# BUG-0884 — The Atlas context did not say which userinterface a device runs, so every navigation prompt failed first

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0884                                                     |
| Reported  | 2026-10-23                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | backend / ai agent                                           |
| Fixed in  | build 90145 |
| Commit    | `ad2685064`                                                |

---

## Symptom

"Navigate {device} to settings" and "Go to the live TV screen on {device}" failed on the first
attempt, because Atlas did not know which userinterface the device runs:

```
navigate_to_node → Error: User interface 'labox-mobile' not found
```

Atlas had guessed the **device name** as the interface name. It then spent six tool calls
(`navigate_to_node` ×3, `get_execution_results`, `localize`, `search_docs`) looking the real name
up (`stb_android_mobile`) and still failed the navigation ("Could not resolve target_node_label
'live_tv'"). Both prompts are contract rows (TASK-163: UC-089, UC-090) and both failed in the
baseline run.

## Root cause

`_build_full_context_section` (`backend_server/src/agent/core/manager.py`) printed the device list
as name, host and id only:

```
**Available Devices:** labox-mobile (host_name='labox-mobile', device_id='device1'), …
```

The navigation tools take a **userinterface name**, and the "Available Interfaces" line listed the
interfaces of the team without saying which device each belongs to. The mapping was in the data all
along — the page sends the whole device record (`hosts.flatMap(host => host.devices)`) and it
carries `preferred_userinterface` ("sauce-demo", "stb_android_mobile", …) — the context builder
simply dropped the field.

## Fix

`backend_server/src/agent/core/manager.py`, `_build_full_context_section`: each device line now
carries its own interface, and one line says what it is for:

```
**Available Devices:** labox-mobile (host_name='labox-mobile', device_id='device1', userinterface='stb_android_mobile'), …
A device's userinterface is the tree to navigate it (pass it as userinterface_name to
navigate_to_node / list_navigation_nodes); it is the device's own interface, not the one selected in the page.
```

`scripts/atlas_usecase_bench.py` had the same gap: its `ui_context()` kept name/host/id/model and
dropped `preferred_userinterface`, so the benchmark was not sending what the page sends. It now
keeps the field.

## Verification

```bash
python3 - <<'PY'
import sys; sys.path.insert(0, '.')
from backend_server.src.agent.core.manager import QAManagerAgent
m = QAManagerAgent.__new__(QAManagerAgent)
print(m._build_full_context_section({
    'host_name': 'labox-mobile', 'device_id': 'device1', 'userinterface_name': '',
    'available_devices': [{'host_name': 'labox-mobile', 'device_id': 'device1',
                            'device_name': 'labox-mobile',
                            'preferred_userinterface': 'stb_android_mobile'}]}))
PY
```

The device line must show `userinterface='stb_android_mobile'`. End-to-end: after the deploy, run
UC-089 / UC-090 again and check that `navigate_to_node` is called with the device's own interface.
