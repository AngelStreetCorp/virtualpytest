"""
Group Tools - one remote command on several devices at once (TASK-76).

A group is a device model + a remote profile ('ir:stb', 'ble:arris', 'adb_tv', 'vega'…):
the same key name only means the same thing on the same controller and key map, so a
group is always taken from list_device_groups, never built by hand.
"""

import json
import time
from typing import Any, Dict, List

from shared.src.lib.config.constants import get_team_id
from shared.src.lib.config.remote_profiles import GROUP_MAX_SIZE, build_groups

from ..utils.api_client import MCPAPIClient
from ..utils.lock_ownership import auto_lock
from ..utils.screenshot_capture import capture_image_block


def _text(msg: str, is_error: bool = False) -> Dict[str, Any]:
    return {"content": [{"type": "text", "text": msg}], "isError": is_error}


class GroupTools:
    """List same-remote device groups and drive them with one command."""

    def __init__(self, api_client: MCPAPIClient):
        self.api = api_client
        # "host:device" -> session id of a lock this tool call acquired (released at the end).
        self._control_sessions: Dict[str, str] = {}

    def list_device_groups(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        List devices that can be driven together: same device model AND same remote profile.

        A remote profile is the controller plus its key map: 'ir:<ir_type>' (IR blaster),
        'ble:<ble_type>' (BLE remote), 'adb_tv' (Android TV / Fire OS over ADB), 'vega'
        (Fire TV Vega), 'adb_mobile', 'appium'. An stb on IR and an stb on BLE are NOT one
        group: POWER does not do the same thing on both. Use a group exactly as returned
        here with execute_group_action.

        TASK-80 multi-transport: the `android_tv` family alias (fire_tv_fireos +
        fire_tv_vega + android_tv) lets two Fire TVs on different OSes group under
        one Fire TV remote. The group entry's `remote_profile` is the *displayed*
        skin; the per-target `remote_profile` lives on each target in
        `targets[].remote_profile` and is what the server fans out on. Multi-
        transport BLE/IR groups of the same model are NOT returned here — the
        frontend `/device-control` tile owns that case; the MCP tool keeps the
        strict per-profile model so the agent's reasoning stays simple.

        Example: list_device_groups(device_model='stb')

        Args:
            params: {
                'device_model': str (OPTIONAL - only groups of this model, e.g. stb, fire_tv_fireos),
                'remote_profile': str (OPTIONAL - only groups on this profile, e.g. ir:stb, adb_tv)
            }

        Returns:
            MCP-formatted response: one line per group plus a JSON block of groups with their targets
        """
        result = self.api.get('/server/system/getAllHosts')
        if not result.get('success'):
            return _text(f"Error: cannot list hosts: {result.get('error', 'unknown error')}", True)

        devices = [
            {**d, 'host_name': h.get('host_name')}
            for h in result.get('hosts', []) if h.get('status', 'online') == 'online'
            for d in h.get('devices', [])
        ]
        groups = build_groups(devices)
        if params.get('device_model'):
            groups = [g for g in groups if g['device_model'] == params['device_model']]
        if params.get('remote_profile'):
            groups = [g for g in groups if g['remote_profile'] == params['remote_profile']]

        if not groups:
            return _text("No group: no two online devices share a device model and a remote profile.")

        lines = [f"{len(groups)} group(s) (max {GROUP_MAX_SIZE} devices per command):"]
        for g in groups:
            names = ', '.join(f"{d['host_name']}/{d['device_id']} ({d.get('device_name') or '?'})" for d in g['devices'])
            lines.append(f"- {g['device_model']} · {g['remote_profile']} → {len(g['devices'])} devices: {names}")
        lines.append("\nGroups (pass device_model, remote_profile and targets to execute_group_action):")
        lines.append(json.dumps([
            {'device_model': g['device_model'], 'remote_profile': g['remote_profile'],
             'targets': [{'host_name': d['host_name'], 'device_id': d['device_id']} for d in g['devices']]}
            for g in groups
        ], indent=1))
        return _text('\n'.join(lines))

    def execute_group_action(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Send the same remote commands to every device of a group, in parallel per command.

        Take the group from list_device_groups (device_model + remote_profile + targets);
        the server refuses a target of another model or remote profile. Key names come
        from list_actions on the FIRST target and are valid for all of them, because they
        share the key map. Locks each device for the call and releases it after; a device
        someone else holds is skipped and named, never taken over.

        Each action: {"command": "press_key", "params": {"key": "HOME"}}. Optional
        "params": {"wait_time": 1500} waits that many ms after the command (all devices).

        Example: execute_group_action(device_model='stb', remote_profile='ir:stb', targets=[{'host_name': 'pi1', 'device_id': 'device1'}, {'host_name': 'pi2', 'device_id': 'device1'}], actions=[{'command': 'press_key', 'params': {'key': 'HOME'}}])

        Args:
            params: {
                'targets': list (REQUIRED - the group's targets from list_device_groups: host_name + device_id each, 2 to 6),
                'remote_profile': str (REQUIRED - the group's remote profile, e.g. ir:stb, ble:arris, adb_tv),
                'actions': list (REQUIRED - remote commands: command press_key with params key, e.g. HOME),
                'device_model': str (OPTIONAL - the group's device model; checked by the server),
                'force_unlock': bool (OPTIONAL - stop a running script/testcase holding a device; never another user's take-control),
                'include_screenshot': bool (OPTIONAL - attach one screenshot per device after the last action, default false)
            }

        Returns:
            MCP-formatted response: per action, one line per device (sent / error / skipped) and the skew between devices
        """
        targets: List[Dict[str, str]] = params.get('targets') or []
        remote_profile = params.get('remote_profile')
        actions = params.get('actions') or []
        team_id = params.get('team_id', get_team_id())

        if len(targets) < 2 or not remote_profile or not actions:
            return _text("Error: targets (2+ devices), remote_profile and actions are required. "
                         "Get them from list_device_groups.", True)
        if len(targets) > GROUP_MAX_SIZE:
            return _text(f"Error: at most {GROUP_MAX_SIZE} devices per group call.", True)
        if any(not a.get('command') for a in actions):
            return _text('Error: every action needs a command, e.g. {"command": "press_key", "params": {"key": "HOME"}}', True)

        lines: List[str] = []
        ready: List[Dict[str, str]] = []
        for t in targets:
            error = auto_lock(self.api, self._control_sessions, params, t.get('host_name'), t.get('device_id'),
                              team_id, bool(params.get('force_unlock')), 'group')
            if error:
                reason = ' '.join(c.get('text', '') for c in error.get('content', []))
                lines.append(f"⏭ {t.get('host_name')}/{t.get('device_id')} skipped: {reason}")
            else:
                ready.append(t)

        try:
            if len(ready) < 1:
                return _text('\n'.join(lines + ["❌ No device of the group could be locked."]), True)

            session_ids = [s for s in (params.get('session_id'), params.get('_caller_browser_session_id')) if s]
            session_ids += list(self._control_sessions.values())
            failed = 0
            for i, action in enumerate(actions, 1):
                cmd_params = dict(action.get('params') or {})
                wait_ms = cmd_params.pop('wait_time', 0)
                # TASK-80: pass each target's own remote_profile through; the
                # top-level remote_profile is the default for any target that
                # doesn't carry one (backward-compat with v1 callers).
                result = self.api.post('/server/remote/executeCommandGroup', data={
                    'targets': ready,
                    'remote_profile': remote_profile,
                    'device_model': params.get('device_model'),
                    'command': action['command'],
                    'params': cmd_params,
                    'session_ids': session_ids,
                }, params={'team_id': team_id})

                if result.get('mismatches'):
                    bad = '; '.join(f"{m['host_name']}/{m['device_id']}: {m['reason']}" for m in result['mismatches'])
                    return _text('\n'.join(lines + [f"❌ Not one group: {bad}. Use list_device_groups."]), True)
                if 'results' not in result:
                    return _text('\n'.join(lines + [f"❌ {action['command']}: {result.get('error', 'group send failed')}"]), True)

                label = f"{action['command']} {cmd_params.get('key', '')}".strip()
                # TASK-80: surface the per-target profile when the group uses
                # more than one transport, so a BLE-only failure on one member
                # is readable in the per-line output.
                used = sorted({p for p in (r.get('remote_profile') for r in result['results']) if p})
                multi = ' · transports: ' + ', '.join(used) if len(used) > 1 else ''
                lines.append(f"{i}. {label} (skew {result.get('skew_ms', 0)} ms){multi}:")
                for r in result['results']:
                    mark = '⏭' if r.get('skipped') else ('✓' if r['success'] else '✗')
                    detail = '' if r['success'] else f" — {r.get('error')}"
                    transport = f" via {r['remote_profile']}" if len(used) > 1 and r.get('remote_profile') else ''
                    lines.append(f"   {mark} {r['host_name']}/{r['device_id']}{transport}{detail}")
                    failed += 0 if r['success'] else 1
                if wait_ms:
                    time.sleep(min(float(wait_ms), 10000) / 1000)

            lines.append("⚠️ Commands sent; screen state not verified (use capture_screenshot per device).")
            response = _text('\n'.join(lines), failed > 0)
            response['action_state_verified'] = False
            if params.get('include_screenshot'):
                for t in ready:
                    block = capture_image_block(self.api, t['device_id'], t['host_name'], team_id)
                    if block:
                        response['content'].append(block)
            return response
        finally:
            for t in ready:
                self._auto_unlock(t['host_name'], t['device_id'], team_id)

    def _auto_unlock(self, host_name: str, device_id: str, team_id: str) -> None:
        """Release a lock this call acquired (a lock the caller already held is kept)."""
        session_id = self._control_sessions.pop(f"{host_name}:{device_id}", None)
        if session_id:
            self.api.post('/server/control/releaseControl',
                          data={'host_name': host_name, 'device_id': device_id, 'session_id': session_id},
                          params={'team_id': team_id})
