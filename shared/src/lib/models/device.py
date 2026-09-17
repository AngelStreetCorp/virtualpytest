"""
Device Model

Represents a single device with its controllers organized by type.

NOTE: This module is only for use by backend_host.
It should NOT be imported by backend_server (would cause circular dependencies).
"""

from __future__ import annotations  # Enable PEP 563 - postponed evaluation of annotations
from typing import Dict, List, Optional, Any, TYPE_CHECKING

# Lazy import to avoid circular dependency when backend_server imports shared
if TYPE_CHECKING:
    from backend_host.src.controllers.base_controller import BaseController


class Device:
    """
    A device that holds controllers organized by abstract type.
    
    Example usage:
        device = Device("device1", "IRSTB_PROD_Test2", "stb")
        av_controller = device.get_controller('av')
        remote_controller = device.get_controller('remote')
        verification_controllers = device.get_controllers('verification')
    """
    
    def __init__(self, device_id: str, device_name: str, device_model: str, host_name: str = None, device_ip: str = None, device_port: str = None, video_stream_path: str = None, video_capture_path: str = None, video: str = None, ir_type: str = None, device_platform: str = None, preferred_userinterface: str = None, preferred_variant: str = None):
        """
        Initialize a device.

        Args:
            device_id: Device identifier (e.g., 'device1', 'device2')
            device_name: Device name from environment (e.g., 'IRSTB_PROD_Test2')
            device_model: Device model from environment (e.g., 'stb')
            host_name: Name of the host this device belongs to
            device_ip: Device IP address
            device_port: Device port
            video_stream_path: Video stream path for URL building (e.g., '/host/stream/capture1')
            video_capture_path: Video capture path for URL building (e.g., '/var/www/html/stream/capture1')
            video: Video device path (e.g., '/dev/video0', '/dev/video2')
            ir_type: IR remote type (e.g., 'samsung', 'stb')
            device_platform: Optional granular platform tag parsed from DEVICE{i}_MODEL
                suffix (e.g. 'example-v2' from 'stb-example-v2'). None when bare.
                Used by variant resolution at unified-graph build time.
            preferred_userinterface: Optional per-device default userinterface
                (DEVICE{i}_USERINTERFACE). Used as the fallback when a navigation
                script is launched without --userinterface, and preselected in
                the Run Tests UI. None when unset.
            preferred_variant: Optional per-device default named variant
                (DEVICE{i}_VARIANT). Only meaningful paired with
                preferred_userinterface — callers reset it to base when the
                effective userinterface differs. None when unset.
        """
        self.device_id = device_id
        self.device_name = device_name
        self.device_model = device_model
        self.device_platform = device_platform
        self.preferred_userinterface = preferred_userinterface
        self.preferred_variant = preferred_variant
        self.device_locale = None  # set at script-start by probe_locale; None until probed
        self.host_name = host_name
        self.device_ip = device_ip
        self.device_port = device_port
        self.ir_type = ir_type
        
        # Store video paths for URL building purposes
        self.video_stream_path = video_stream_path
        self.video_capture_path = video_capture_path
        self.video = video
        
        # Controllers organized by type
        self._controllers: Dict[str, List[BaseController]] = {
            'av': [],
            'remote': [],
            'verification': [],
            'power': [],
            'network': []
        }
        
        # Capabilities derived from controllers
        self._capabilities: List[str] = []
        
        # Shared navigation context for all executors
        self.navigation_context = {
            'current_tree_id': None,
            'current_node_id': None,
            'current_node_label': None,
            'previous_node_id': None,
            'previous_node_label': None,
            'current_node_navigation_success': None,
            'last_action_executed': None,
            'last_action_timestamp': None,
            'team_id': None
        }
    
    def add_controller(self, controller_type: str, controller: BaseController):
        """
        Add a controller to this device.
        
        Args:
            controller_type: Abstract type ('av', 'remote', 'verification', etc.)
            controller: The controller instance
        """
        if controller_type not in self._controllers:
            self._controllers[controller_type] = []
        
        self._controllers[controller_type].append(controller)
    
    def _get_controller(self, controller_type: str) -> Optional[BaseController]:
        """
        Get the first controller of the specified type.
        
        PRIVATE METHOD - Only for use by service executors:
        - ActionExecutor
        - VerificationExecutor  
        - NavigationExecutor
        - ZapExecutor (specialized executor)
        - AiExecutor
        
        Scripts and routes should use service executors instead of direct controller access.
        
        Args:
            controller_type: Abstract type ('av', 'remote', 'verification', etc.)
            
        Returns:
            First controller of the type, or None if not found
        """
        controllers = self._controllers.get(controller_type, [])
        return controllers[0] if controllers else None
    
    def get_controllers(self, controller_type: str) -> List[BaseController]:
        """
        Get all controllers of the specified type.
        
        Args:
            controller_type: Abstract type ('av', 'remote', 'verification', etc.)
            
        Returns:
            List of controllers of the specified type
        """
        return self._controllers.get(controller_type, [])
    
    def has_controller(self, controller_type: str) -> bool:
        """
        Check if device has any controllers of the specified type.
        
        Args:
            controller_type: Abstract type to check
            
        Returns:
            True if device has controllers of this type
        """
        return len(self._controllers.get(controller_type, [])) > 0
    
    def is_mobile_device(self) -> bool:
        """
        Check if this device is a mobile device.
        
        Returns:
            True if device model contains 'mobile'
        """
        return "mobile" in self.device_model.lower()
    
    def get_capture_dir(self, subfolder: str = 'captures') -> Optional[str]:
        """
        Get capture directory for this device with automatic hot/cold storage resolution.
        
        This is the SINGLE SOURCE OF TRUTH for capture path lookup - all executors should use this.
        
        Args:
            subfolder: Subfolder name ('captures', 'thumbnails', 'segments', 'metadata')
        
        Returns:
            Full path to capture directory (hot if RAM mode, cold otherwise), or None if not available
        
        Examples:
            device.get_capture_dir('captures') -> '/var/www/html/stream/capture1/hot/captures' (RAM mode)
            device.get_capture_dir('thumbnails') -> '/var/www/html/stream/capture1/thumbnails' (SD mode)
        """
        if not self.video_capture_path:
            return None
        
        # Use centralized hot/cold resolution (same pattern as base_controller.py)
        from shared.src.lib.utils.storage_path_utils import get_capture_storage_path
        
        return get_capture_storage_path(self.video_capture_path, subfolder)

    
    def get_capabilities(self) -> List[str]:
        """
        Get all capabilities of this device.
        
        Returns:
            List of abstract capability types (what the device can do)
        """
        # Return abstract types based on which controllers are present
        capabilities = []
        for controller_type, controllers in self._controllers.items():
            if controllers:  # If we have controllers of this type
                capabilities.append(controller_type)
        return capabilities
    
    def get_available_verifications(self) -> Dict[str, Any]:
        """
        Get available verifications from ALL controllers that implement get_available_verifications().
        
        This method doesn't hardcode which controller types can provide verifications.
        Instead, it checks ALL controller types and lets each controller declare its own verifications.
        
        Returns:
            Dictionary mapping verification_type to list of verification definitions
            Example: {'adb': [...], 'text': [...], 'web': [...]}
        """
        verification_types = {}
        
        # Check ALL controller types - don't hardcode which can provide verifications
        for controller_type, controllers in self._controllers.items():
            for controller in controllers:
                # If controller has the method, it can provide verifications
                if hasattr(controller, 'get_available_verifications'):
                    try:
                        controller_verifications = controller.get_available_verifications()
                        
                        if not controller_verifications:
                            continue  # Skip empty lists
                        
                        # Group verifications by their verification_type field
                        for verification in controller_verifications:
                            v_type = verification.get('verification_type')
                            
                            if not v_type:
                                print(f"[@device:get_available_verifications] WARNING: Verification '{verification.get('command')}' from {controller.__class__.__name__} missing 'verification_type' field")
                                continue
                            
                            if v_type not in verification_types:
                                verification_types[v_type] = []
                            
                            verification_types[v_type].append(verification)

                    except Exception as e:
                        print(f"[@device:get_available_verifications] Error getting verifications from {controller.__class__.__name__}: {e}")
        
        return verification_types
    
    def get_available_actions(self) -> Dict[str, Any]:
        """
        Get available actions from all action controllers (remote, av, power, etc.).
        
        Returns:
            Dictionary mapping action categories to their available actions
            Example: {'Remote': [...], 'Power': [...]}
        """
        action_types = {}
        
        # Check all controller types that can provide actions
        action_controller_types = ['remote', 'av', 'power', 'desktop', 'web', 'network']
        
        for controller_type in action_controller_types:
            controllers = self.get_controllers(controller_type)
            
            for controller in controllers:
                # Check if controller has get_available_actions method
                if hasattr(controller, 'get_available_actions'):
                    try:
                        controller_actions = controller.get_available_actions()
                        # Merge actions into the action_types dict
                        for action_category, actions in controller_actions.items():
                            if action_category not in action_types:
                                action_types[action_category] = []
                            action_types[action_category].extend(actions)
                    except Exception as e:
                        print(f"[@device:get_available_actions] Error getting actions from {controller.__class__.__name__}: {e}")
        
        return action_types

    def to_dict(self) -> Dict[str, Any]:
        """
        Convert device to dictionary with detailed capabilities for serialization.
        
        Returns:
            Dictionary representation of the device with detailed capability format
        """
        from shared.src.lib.config.device_capabilities import get_device_capabilities
        
        # Get theoretical capabilities from factory (for reference)
        theoretical_capabilities = get_device_capabilities(self.device_model)
        
        # Build actual capabilities based on successfully instantiated controllers
        actual_capabilities = {
            'av': None,
            'remote': None,
            'desktop': None,
            'web': None,
            'power': None,
            'ai': None,
            'verification': []
        }
        
        # Check which controllers are actually available
        if self._controllers.get('av'):
            # Get the implementation name from the first AV controller
            av_controller = self._controllers['av'][0]
            controller_name = av_controller.__class__.__name__.lower()
            if 'hdmi' in controller_name:
                actual_capabilities['av'] = 'hdmi_stream'
            elif 'camera' in controller_name:
                actual_capabilities['av'] = 'camera_stream'
            elif 'vnc' in controller_name:
                actual_capabilities['av'] = 'vnc_stream'
            else:
                actual_capabilities['av'] = theoretical_capabilities['av']  # Fallback
        
        if self._controllers.get('remote'):
            # Handle multiple remote controllers
            remote_controllers = self._controllers['remote']
            remote_implementations = []
            
            for remote_controller in remote_controllers:
                controller_name = remote_controller.__class__.__name__.lower()
                if 'phoneagent' in controller_name:
                    # features/mobile-app paired phone — must precede the generic
                    # checks so it never reads as an ADB remote.
                    remote_implementations.append('phone_agent')
                elif 'androidmobile' in controller_name:
                    remote_implementations.append('android_mobile')
                elif 'androidtv' in controller_name:
                    remote_implementations.append('android_tv')
                elif 'appium' in controller_name:
                    remote_implementations.append('appium')
                elif 'irtrans' in controller_name:
                    # Networked IRTrans box presents as a normal IR remote to the
                    # frontend (same STB panel, same press_key flow); only the
                    # backend transport differs.
                    remote_implementations.append('ir_remote')
                elif 'irremote' in controller_name or 'infrared' in controller_name:
                    remote_implementations.append('ir_remote')
                elif 'bluetoothremote' in controller_name:
                    remote_implementations.append('bluetooth_remote')
                else:
                    # Fallback - try to get from theoretical capabilities.
                    # Note: this silently maps any unknown remote controller
                    # class to the first entry of the device model's
                    # theoretical remote list, which has historically hidden
                    # missing branches (e.g. BLE used to fall through here
                    # and report as 'ir_remote' on stb devices, causing
                    # InfraredRemote to render for a BLE-only config). Any
                    # new remote controller class MUST have an explicit
                    # branch above — don't rely on this fallback.
                    if theoretical_capabilities['remote']:
                        remote_implementations.append(theoretical_capabilities['remote'])
            
            # Set remote capability based on number of implementations
            if len(remote_implementations) == 1:
                actual_capabilities['remote'] = remote_implementations[0]
            elif len(remote_implementations) > 1:
                actual_capabilities['remote'] = remote_implementations  # Array for multiple
            else:
                actual_capabilities['remote'] = theoretical_capabilities['remote']  # Fallback
        
        if self._controllers.get('power'):
            # Get the implementation name from the first power controller
            power_controller = self._controllers['power'][0]
            controller_name = power_controller.__class__.__name__.lower()
            if 'tapo' in controller_name:
                actual_capabilities['power'] = 'tapo'
            elif 'apipower' in controller_name:
                actual_capabilities['power'] = 'api_power'
            else:
                actual_capabilities['power'] = theoretical_capabilities['power']  # Fallback
        
        # For other controller types, use theoretical capabilities as they're less critical
        actual_capabilities['desktop'] = theoretical_capabilities['desktop']
        actual_capabilities['web'] = theoretical_capabilities['web']
        
        
        # Collect available verification types and action types from controllers
        device_verification_types = self.get_available_verifications()
        device_action_types = self.get_available_actions()
        
        
        # Base device information
        device_dict = {
            'device_id': self.device_id,
            'device_name': self.device_name,  # Updated field name to match frontend expectations
            'device_model': self.device_model,  # Updated field name to match frontend expectations
            'device_ip': self.device_ip,
            'device_port': self.device_port,
            'ir_type': self.ir_type,  # IR remote type for frontend
            'device_capabilities': actual_capabilities,  # Use actual capabilities instead of theoretical
            'device_verification_types': device_verification_types,  # Simplified naming (removed 'available_' prefix)
            'device_action_types': device_action_types  # Simplified naming (removed 'available_' prefix)
        }
        
        # Include video paths needed for URL building (if available)
        # These are required by buildUrlUtils functions
        if self.video_stream_path:
            device_dict['video_stream_path'] = self.video_stream_path
        if self.video_capture_path:
            device_dict['video_capture_path'] = self.video_capture_path
        if self.video:
            device_dict['video'] = self.video

        # Per-device default userinterface/variant (only when configured).
        if self.preferred_userinterface:
            device_dict['preferred_userinterface'] = self.preferred_userinterface
        if self.preferred_variant:
            device_dict['preferred_variant'] = self.preferred_variant

        return device_dict 