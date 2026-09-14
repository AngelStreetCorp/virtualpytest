"""
Verification Validation Utility

Validates verification commands against available controllers before saving to database.
Prevents invalid verification commands from being stored in nodes.
"""

import logging
from typing import Dict, Any, List, Optional, Tuple
from backend_server.src.mcp.utils.api_client import MCPAPIClient
from shared.src.lib.config.constants import APP_CONFIG


logger = logging.getLogger(__name__)


class VerificationValidator:
    """
    Validates verification commands against available device controllers.
    
    This prevents invalid verification commands from being saved to nodes,
    catching errors at creation time rather than execution time.
    """
    
    def __init__(self, api_client: MCPAPIClient):
        self.api_client = api_client
        self._cache = {}  # Cache valid commands per device_model
    
    def validate_verifications(
        self,
        verifications: List[Dict[str, Any]],
        device_model: str,
        host_name: str = None,
        device_id: str = None
    ) -> Tuple[bool, List[str], List[str]]:
        """
        Validate a list of verifications against available controllers.
        
        Args:
            verifications: List of verification dicts with 'command', 'verification_type', 'params'
            device_model: Device model (e.g., 'web', 'android_mobile', 'android_tv', 'host_vnc')
            host_name: Host name (optional - used for fetching available commands)
            device_id: Device ID (optional - used for fetching available commands)
        
        Returns:
            Tuple of (is_valid, errors, warnings)
            - is_valid: True if all verifications are valid
            - errors: List of error messages
            - warnings: List of warning messages
        """
        if not verifications:
            return True, [], []
        
        # No default host_name - must be provided explicitly via get_compatible_hosts()
        device_id = device_id or self._get_default_device_id_for_model(device_model)
        
        # Get valid commands for this device model
        valid_commands = self._get_valid_commands(device_model, host_name, device_id)
        
        if not valid_commands:
            # If we can't fetch commands, return warning but allow save
            warning = (
                f"⚠️ Could not fetch valid verification commands for device model '{device_model}'. "
                f"Verifications will be validated at execution time."
            )
            return True, [], [warning]
        
        # Validate each verification
        errors = []
        warnings = []
        
        for i, verification in enumerate(verifications):
            command = verification.get('command')
            verification_type = verification.get('verification_type', 'unknown')
            
            if not command:
                errors.append(f"Verification {i+1}: Missing 'command' field")
                continue

            # Check if command exists for this device model
            if command not in valid_commands:
                similar = self._find_similar_command(command, valid_commands)
                error_msg = (
                    f"Verification {i+1}: Invalid command '{command}' for device model '{device_model}' "
                    f"(verification_type: {verification_type})\n"
                    f"   Available commands: {', '.join(sorted(valid_commands.keys())[:5])}..."
                )
                if similar:
                    error_msg += f"\n   Did you mean '{similar}'?"

                # Add helpful guidance for common mistakes
                if verification_type not in ['text', 'image', 'adb', 'appium', 'web', 'audio', 'video']:
                    error_msg += (
                        f"\n\n❌ Invalid verification_type '{verification_type}'"
                        f"\n💡 Valid types: text, image, adb, appium, web, audio, video"
                    )
                elif 'selector' in verification.get('params', {}) and device_model in ['android_mobile', 'android_tv', 'fire_tv']:
                    error_msg += (
                        f"\n\n❌ Mobile devices use 'search_term', not 'selector'"
                        f"\n💡 Use analyze_screen_for_verification() with platform='mobile'"
                    )

                errors.append(error_msg)
            else:
                # Command is valid - check params
                command_info = valid_commands[command]
                param_errors = self._validate_params(
                    verification.get('params', {}),
                    command_info.get('params', {}),
                    command
                )
                if param_errors:
                    warnings.extend(param_errors)
        
        is_valid = len(errors) == 0
        return is_valid, errors, warnings
    
    def _get_valid_commands(
        self,
        device_model: str,
        host_name: str,
        device_id: str
    ) -> Dict[str, Dict]:
        """
        Get valid verification commands for a device model.
        
        Returns dict mapping command_name -> command_info
        """
        cache_key = f"{device_model}_{host_name}_{device_id}"
        
        # Check cache
        if cache_key in self._cache:
            return self._cache[cache_key]
        
        try:
            # Call list_verifications endpoint
            result = self.api_client.post(
                '/mcp/list_verifications',
                data={
                    'device_id': device_id,
                    'host_name': host_name
                }
            )
            
            if not result.get('success'):
                logger.warning(
                    f"Failed to fetch verification commands for {device_model}: "
                    f"{result.get('error', 'Unknown error')}"
                )
                return {}
            
            # Parse response to build command map
            commands = {}
            verifications = result.get('verifications', {})
            
            for category, category_verifications in verifications.items():
                for verification in category_verifications:
                    command_name = verification.get('command')
                    if command_name:
                        commands[command_name] = {
                            'category': category,
                            'description': verification.get('description', ''),
                            'params': verification.get('params', {})
                        }
            
            # Cache the result
            self._cache[cache_key] = commands
            return commands
        
        except Exception as e:
            logger.error(f"Error fetching verification commands: {e}", exc_info=True)
            return {}
    
    def _get_default_device_id_for_model(self, device_model: str) -> str:
        """Get default device ID based on device model"""
        model_to_device = {
            'android_mobile': 'device1',
            'android_tv': 'device3',
            'web': 'host',
            'host_vnc': 'host',
            'fire_tv': 'device3',
            'stb': 'device1'
        }
        return model_to_device.get(device_model, 'device1')
    
    def _find_similar_command(self, command: str, valid_commands: Dict[str, Dict]) -> Optional[str]:
        """Find similar command using simple string matching"""
        command_lower = command.lower()
        
        # First try exact substring match
        for valid_cmd in valid_commands:
            if command_lower in valid_cmd.lower() or valid_cmd.lower() in command_lower:
                return valid_cmd
        
        # Try Levenshtein-like matching (simple version)
        def similarity(s1: str, s2: str) -> int:
            """Simple similarity score based on common characters"""
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
        command: str
    ) -> List[str]:
        """
        Validate parameters against expected schema.
        
        Returns list of warning messages (not errors - params are flexible)
        """
        warnings = []
        
        # Check for required params
        for param_name, param_info in expected_params.items():
            if param_info.get('required', False) and param_name not in provided_params:
                warnings.append(
                    f"   ⚠️ Command '{command}': Missing required parameter '{param_name}'"
                )
        
        return warnings
    
    def get_valid_commands_for_display(
        self,
        device_model: str,
        host_name: str = None,
        device_id: str = None
    ) -> str:
        """
        Get formatted list of valid commands for error messages.
        
        Returns:
            Formatted string listing available commands by category
        """
        # No default host_name - must be provided explicitly via get_compatible_hosts()
        device_id = device_id or self._get_default_device_id_for_model(device_model)
        
        valid_commands = self._get_valid_commands(device_model, host_name, device_id)
        
        if not valid_commands:
            return f"No verification commands available for device model '{device_model}'"
        
        # Group by category
        by_category = {}
        for cmd, info in valid_commands.items():
            category = info.get('category', 'other')
            if category not in by_category:
                by_category[category] = []
            by_category[category].append(cmd)
        
        # Format output
        lines = [f"\n📋 Available verification commands for '{device_model}':\n"]
        for category, commands in sorted(by_category.items()):
            lines.append(f"  **{category.upper()}**:")
            for cmd in sorted(commands):
                lines.append(f"    - {cmd}")
        
        lines.append(f"\n💡 To see full details, call: list_verifications(device_id='{device_id}', host_name='{host_name}')")
        
        return "\n".join(lines)


def validate_node_verifications(
    verifications: List[Dict[str, Any]],
    device_model: str,
    api_client: MCPAPIClient,
    host_name: str = None,
    device_id: str = None
) -> Tuple[bool, List[str], List[str]]:
    """
    Convenience function to validate node verifications.
    
    Returns:
        Tuple of (is_valid, errors, warnings)
    """
    validator = VerificationValidator(api_client)
    return validator.validate_verifications(
        verifications,
        device_model,
        host_name,
        device_id
    )

