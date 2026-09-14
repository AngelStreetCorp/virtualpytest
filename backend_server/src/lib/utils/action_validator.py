"""
Action Command Validation Utility

Validates action commands against available controllers before saving to database.
Reads device_action_types directly from the in-process host_manager — no HTTP loopback.
"""

import logging
import threading
from typing import Dict, Any, List, Optional, Tuple


logger = logging.getLogger(__name__)


_COMMANDS_CACHE: Dict[str, Dict[str, Dict]] = {}
_COMMANDS_CACHE_LOCK = threading.Lock()


class ActionValidator:
    """
    Validates action commands against available device controllers.

    This prevents invalid action commands from being saved to edges,
    catching errors at creation time rather than execution time.
    """

    def validate_action_sets(
        self,
        action_sets: List[Dict[str, Any]],
        device_model: str,
        host_name: str = None,
        device_id: str = None
    ) -> Tuple[bool, List[str], List[str]]:
        """
        Validate action commands in action_sets against available controllers.

        Returns:
            Tuple of (is_valid, errors, warnings)
        """
        if not action_sets:
            return True, [], []

        device_id = device_id or self._get_default_device_id_for_model(device_model)
        valid_commands = self._get_valid_commands(device_model, host_name, device_id)

        if not valid_commands:
            warning = (
                f"⚠️ Could not fetch valid action commands for device model '{device_model}'. "
                f"Actions will be validated at execution time."
            )
            return True, [], [warning]

        errors: List[str] = []
        warnings: List[str] = []

        for action_set_idx, action_set in enumerate(action_sets):
            action_set_id = action_set.get('id', f'action_set_{action_set_idx}')

            self._validate_action_list(
                action_set.get('actions', []),
                valid_commands,
                device_model,
                f"action_set '{action_set_id}'",
                errors,
                warnings,
            )
            self._validate_action_list(
                action_set.get('retry_actions', []),
                valid_commands,
                device_model,
                f"retry_actions in '{action_set_id}'",
                errors,
                warnings,
            )
            self._validate_action_list(
                action_set.get('failure_actions', []),
                valid_commands,
                device_model,
                f"failure_actions in '{action_set_id}'",
                errors,
                warnings,
            )

        return len(errors) == 0, errors, warnings

    def _validate_action_list(
        self,
        actions: List[Dict[str, Any]],
        valid_commands: Dict[str, Dict],
        device_model: str,
        context: str,
        errors: List[str],
        warnings: List[str]
    ):
        for action_idx, action in enumerate(actions):
            command = action.get('command')

            if not command:
                errors.append(f"Action {action_idx + 1} in {context}: Missing 'command' field")
                continue

            if command not in valid_commands:
                similar = self._find_similar_command(command, valid_commands)
                error_msg = (
                    f"Action {action_idx + 1} in {context}: Invalid command '{command}' for device model '{device_model}'\n"
                    f"   Available commands: {', '.join(sorted(valid_commands.keys())[:5])}..."
                )
                if similar:
                    error_msg += f"\n   Did you mean '{similar}'?"
                errors.append(error_msg)
            else:
                command_info = valid_commands[command]
                param_errors = self._validate_params(
                    action.get('params', {}),
                    command_info.get('params', {}),
                    command,
                    context,
                )
                if param_errors:
                    warnings.extend(param_errors)

    def _get_valid_commands(
        self,
        device_model: str,
        host_name: str,
        device_id: str
    ) -> Dict[str, Dict]:
        """
        Get valid action commands for a device model via in-process host_manager.

        Cached at module level so repeated edge saves don't re-fetch.
        """
        cache_key = f"{device_model}_{host_name}_{device_id}"

        with _COMMANDS_CACHE_LOCK:
            if cache_key in _COMMANDS_CACHE:
                return _COMMANDS_CACHE[cache_key]

        try:
            from backend_server.src.lib.utils.server_utils import get_host_manager

            host_manager = get_host_manager()
            host_data = host_manager.get_host(host_name) if host_name else None
            if not host_data:
                return {}

            device_data = next(
                (d for d in host_data.get('devices', []) if d.get('device_id') == device_id),
                None,
            )
            if not device_data:
                return {}

            commands: Dict[str, Dict] = {}
            for category, category_actions in (device_data.get('device_action_types') or {}).items():
                for action in category_actions:
                    command_name = action.get('command')
                    if command_name:
                        commands[command_name] = {
                            'category': category,
                            'description': action.get('description', ''),
                            'params': action.get('params', {}),
                        }

            with _COMMANDS_CACHE_LOCK:
                _COMMANDS_CACHE[cache_key] = commands
            return commands

        except Exception as e:
            logger.error(f"Error fetching action commands: {e}", exc_info=True)
            return {}

    def _get_default_device_id_for_model(self, device_model: str) -> str:
        model_to_device = {
            'android_mobile': 'device1',
            'android_tv': 'device3',
            'web': 'host',
            'host_vnc': 'host',
            'fire_tv': 'device3',
            'stb': 'device1',
        }
        return model_to_device.get(device_model, 'device1')

    def _find_similar_command(self, command: str, valid_commands: Dict[str, Dict]) -> Optional[str]:
        command_lower = command.lower()

        for valid_cmd in valid_commands:
            if command_lower in valid_cmd.lower() or valid_cmd.lower() in command_lower:
                return valid_cmd

        def similarity(s1: str, s2: str) -> int:
            s1, s2 = s1.lower(), s2.lower()
            return sum(c in s2 for c in s1)

        best_match = None
        best_score = 0
        for valid_cmd in valid_commands:
            score = similarity(command, valid_cmd)
            if score > best_score and score >= len(command) * 0.5:
                best_score = score
                best_match = valid_cmd
        return best_match

    def _validate_params(
        self,
        provided_params: Dict[str, Any],
        expected_params: Dict[str, Dict],
        command: str,
        context: str,
    ) -> List[str]:
        warnings: List[str] = []
        for param_name, param_info in expected_params.items():
            if param_info.get('required', False) and param_name not in provided_params:
                warnings.append(
                    f"   ⚠️ Command '{command}' in {context}: Missing required parameter '{param_name}'"
                )
        return warnings

    def get_valid_commands_for_display(
        self,
        device_model: str,
        host_name: str = None,
        device_id: str = None,
    ) -> str:
        device_id = device_id or self._get_default_device_id_for_model(device_model)
        valid_commands = self._get_valid_commands(device_model, host_name, device_id)

        if not valid_commands:
            return f"No action commands available for device model '{device_model}'"

        by_category: Dict[str, List[str]] = {}
        for cmd, info in valid_commands.items():
            category = info.get('category', 'other')
            by_category.setdefault(category, []).append(cmd)

        lines = [f"\n📋 Available action commands for '{device_model}':\n"]
        for category, commands in sorted(by_category.items()):
            lines.append(f"  **{category.upper()}**:")
            for cmd in sorted(commands):
                lines.append(f"    - {cmd}")
        lines.append(
            f"\n💡 To see full details, call: list_actions(device_id='{device_id}', host_name='{host_name}')"
        )
        return "\n".join(lines)


def validate_edge_actions(
    action_sets: List[Dict[str, Any]],
    device_model: str,
    host_name: str = None,
    device_id: str = None,
) -> Tuple[bool, List[str], List[str]]:
    """Convenience wrapper around ActionValidator.validate_action_sets."""
    return ActionValidator().validate_action_sets(
        action_sets,
        device_model,
        host_name,
        device_id,
    )
