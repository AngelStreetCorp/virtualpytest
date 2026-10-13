---
name: control-device-group
description: Send the same remote keys to several devices at once — devices of one model on the same remote (IR, BLE, ADB, Vega). Use when the user asks to act on all / every / several boxes together.
timeout_seconds: 600
requires_device: false
tools:
  - list_device_groups
  - list_actions
  - execute_group_action
  - capture_screenshot
triggers:
  - all devices
  - every device
  - all boxes
  - all stb
  - every stb
  - same model
  - group control
  - on all
  - together
  - multi device
  - several devices
tool_cache:
  list_device_groups:
    enabled: true
    ttl_seconds: 60
  list_actions:
    enabled: true
    ttl_seconds: 300
  execute_group_action: false
---

# Control a device group

Drive several devices with one remote: the same key goes to every device, in parallel.

## What a group is

A group = **device model + remote profile**. The remote profile is the controller and its key map:

| Profile | Controller |
|---|---|
| `ir:<ir_type>` (e.g. `ir:stb`, `ir:fire_tv`) | IR blaster with that key file |
| `ble:<ble_type>` (e.g. `ble:arris`) | emulated BLE remote with that profile |
| `adb_tv` | Android TV / Fire OS over ADB |
| `vega` | Fire TV on Vega OS |
| `adb_mobile`, `appium` | phones |

The same key name does **not** do the same thing on two profiles: `POWER` on an stb over IR is
not `POWER` on an stb over BLE, `HOME` over ADB is not `HOME` over IR. So:

- **Never build a group by hand.** Always take it from `list_device_groups` and pass its
  `device_model`, `remote_profile` and `targets` unchanged to `execute_group_action`.
- A device with two remotes (e.g. Fire OS on ADB and IR) appears in one group per profile.
  Prefer the profile the user names; otherwise the ADB/Vega one over IR/BLE.
- If the user names devices that are not in one group, say which ones differ (model or
  remote) and offer the groups that exist. Do not split the command silently.

## Multi-transport groups (TASK-80)

`list_device_groups` may return a group whose `transports` map gives each device
its own `remote_profile` while the group still shares one `displayed_profile` skin.
This is the case when the operator wants to drive, e.g. a STB on an IR transmitter
and a STB on a BLE dongle with one Fire TV remote: same model, different
controllers. The key set rendered is the **intersection** of every member's
key map; keys outside the intersection are still listed on the skin (so the
operator sees the layout) but greyed and skipped on send.

Rules:

- The group entry's `displayed_profile` is the *visual* skin, not necessarily
  the same as every member's transport. Use it as the skin label, never as the
  per-target profile.
- Each target in the `targets` array carries its own `remote_profile`. Pass it
  through to `execute_group_action` unchanged.
- "The same key name does the same thing on every member" only holds inside the
  intersection. Keys outside it are sent only when the per-target controller
  actually knows the name; otherwise the server returns `ack: skipped`.
- The model lock in the group tile is `modelsAreCompatible` (TASK-80 B), so
  `fire_tv_fireos` and `fire_tv_vega` group together as the `android_tv`
  family. The list returns one entry per `(family, displayed_profile)` pair.

## Workflow

1. `list_device_groups(device_model?)` → pick the group (ask only if two groups fit equally).
2. `list_actions(host_name, device_id)` on the **first** target → valid key names. They are
   valid for every target because the group shares the key map (TASK-80: the intersection).
3. `execute_group_action(device_model, remote_profile, targets, actions=[{"command": "press_key", "params": {"key": "HOME"}}])`.
   - For multi-transport groups, the per-target `remote_profile` on each target
     overrides `remote_profile`; the server fans out on the right transport per
     device and returns the chosen profile in each result.
   - Batch a known sequence in one call (e.g. HOME, then RIGHT ×3, then OK).
   - Add `"wait_time": 1500` (ms) in an action's params after keys that change screens (OK, HOME).
4. Read the result: one line per device, ✓ sent, ✗ error, ⏭ skipped (held by someone else —
   never taken over). Each result carries the `remote_profile` it used, useful when a
   multi-transport group fails on one path only. Report the skew line if it is above 300 ms.
5. "Sent" is not "worked". To confirm the screen, `capture_screenshot` per device, or pass
   `include_screenshot=true` on the last call, and say which devices differ.

## Limits

- 2 to 6 devices per call.
- Remote keys only (`press_key` and the controller's own commands from `list_actions`); no
  click_element / web actions — use the control-device skill per device for those.
