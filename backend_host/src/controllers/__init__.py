"""
VirtualPyTest Controllers Package

This package provides a flexible controller system where each controller type
(Remote, AV, Verification, Power) can be implemented independently for different devices.

The factory system allows you to select specific controller implementations
for each device type, providing maximum flexibility.
"""

from typing import Dict, Any, Type
from .base_controller import (
    BaseController,
    RemoteControllerInterface,
    AVControllerInterface,
    VerificationControllerInterface,
    PowerControllerInterface
)

# Import AV implementations
from .audiovideo.hdmi_stream import HDMIStreamController
from .audiovideo.vnc_stream import VNCStreamController
from .audiovideo.camera_stream import CameraStreamController

# Import real implementations
from .remote.android_tv import AndroidTVRemoteController
from .remote.android_mobile import AndroidMobileRemoteController
from .remote.appium_remote import AppiumRemoteController
from .remote.infrared import IRRemoteController
from .remote.irtrans import IRTransRemoteController
from .remote.bluetooth import BluetoothRemoteController

# Import desktop implementations
from .desktop.bash import BashDesktopController
from .desktop.pyautogui import PyAutoGUIDesktopController

# Import web implementations
from .web.playwright import PlaywrightWebController

# Import power implementations
from .power.tapo_power import TapoPowerController
from .power.api_power import APIPowerController

# Import verification implementations
from .verification.image import ImageVerificationController
from .verification.text import TextVerificationController
from .verification.color import ColorVerificationController
from .verification.adb import ADBVerificationController
from .verification.appium import AppiumVerificationController
from .verification.video import VideoVerificationController
from .verification.audio import AudioVerificationController

# Controller type registry
CONTROLLER_REGISTRY = {
    'remote': {
        'android_tv': AndroidTVRemoteController,  # Real SSH+ADB-based Android TV controller
        'android_mobile': AndroidMobileRemoteController,  # Real SSH+ADB-based Android Mobile controller
        'appium_remote': AppiumRemoteController,  # Universal Appium WebDriver controller for iOS/Android
        'ir_remote': IRRemoteController,     # IR remote with classic TV/STB buttons (local lirc/ir-ctl)
        'irtrans_remote': IRTransRemoteController,  # IR remote via networked IRTrans box (UDP)
        'bluetooth_remote': BluetoothRemoteController,  # Bluetooth HID remote
    },
    'av': {
        'hdmi_stream': HDMIStreamController, # HDMI stream URL controller
        'vnc_stream': VNCStreamController,   # VNC stream URL controller
        'camera_stream': CameraStreamController, # Camera stream URL controller
    },
    'verification': {
        'ocr': TextVerificationController,   # OCR-based text verification using Tesseract
        'text': TextVerificationController,  # OCR-based text verification using Tesseract
        'image': ImageVerificationController, # Template matching-based image verification using OpenCV
        'audio': AudioVerificationController, # Audio analysis and verification
        'video': VideoVerificationController, # Video analysis and motion detection
        'adb': ADBVerificationController,    # Direct ADB element verification using ADBcommands
        'appium': AppiumVerificationController, # Cross-platform element verification using Appium WebDriver
        'web': PlaywrightWebController,      # Web element verification using Playwright
        'ai': TextVerificationController,    # Use text verification until AI implementation is available
    },
    'power': {
        'tapo': TapoPowerController,           # Tapo power control via Tapo API
        'api_power': APIPowerController,       # Power control via custom client REST API
    },
    'desktop': {
        'bash': BashDesktopController,      # Bash desktop controller for executing commands
        'pyautogui': PyAutoGUIDesktopController,      # PyAutoGUI cross-platform GUI automation controller
    },
    'web': {
        'playwright': PlaywrightWebController,  # Playwright web automation controller
    }
}


class ControllerFactory:
    """
    Factory class for creating controller instances.
    
    Allows flexible selection of controller implementations based on
    device type and controller type.
    """
    
    @staticmethod
    def create_remote_controller(
        device_type: str = "android_tv",
        device_name: str = "Unknown Device",
        **kwargs
    ) -> RemoteControllerInterface:
        """
        Create a remote controller instance.
        
        Args:
            device_type: Type of device/implementation (android_tv, apple_tv, etc.)
            device_name: Name of the device for logging
            **kwargs: Additional parameters for the controller
        
        Returns:
            RemoteControllerInterface: Controller instance
        """
        controller_class = CONTROLLER_REGISTRY['remote'].get(device_type)
        if not controller_class:
            raise ValueError(f"Unknown remote controller type: {device_type}")
        
        return controller_class(device_name=device_name, device_type=device_type, **kwargs)
    
    @staticmethod
    def create_av_controller(
        capture_type: str = "hdmi_stream",
        device_name: str = "Unknown Device",
        capture_source: str = "HDMI",
        **kwargs
    ) -> AVControllerInterface:
        """
        Create an AV controller instance.
        
        Args:
            capture_type: Type of capture implementation (hdmi, adb, camera, etc.)
            device_name: Name of the device for logging
            capture_source: Source for capture (HDMI, Network, Tapo, etc.)
            **kwargs: Additional parameters for the controller
        
        Returns:
            AVControllerInterface: Controller instance
        """
        controller_class = CONTROLLER_REGISTRY['av'].get(capture_type)
        if not controller_class:
            raise ValueError(f"Unknown AV controller type: {capture_type}")
        
        return controller_class(device_name=device_name, capture_source=capture_source, **kwargs)
    
    @staticmethod
    def create_verification_controller(
        verification_type: str = "ocr",
        **kwargs
    ) -> VerificationControllerInterface:
        """
        Create a verification controller instance.
        
        Args:
            verification_type: Type of verification implementation (ocr, text, image, audio, video, adb, ai)
            **kwargs: Parameters required by the specific controller (varies by type):
                - ADB: device_ip, device_port (required)
                - Others: av_controller (required)
        
        Returns:
            VerificationControllerInterface: Controller instance
        """
        controller_class = CONTROLLER_REGISTRY['verification'].get(verification_type)
        if not controller_class:
            raise ValueError(f"Unknown verification controller type: {verification_type}")
        
        # Remove verification_type from kwargs before passing to constructor
        filtered_kwargs = {k: v for k, v in kwargs.items() if k != 'verification_type'}
        
        try:
            return controller_class(**filtered_kwargs)
        except Exception as e:
            raise ValueError(f"Failed to create {verification_type} controller: {e}")
    
    @staticmethod
    def create_power_controller(
        power_type: str = "tapo",
        device_name: str = "Unknown Device",
        **kwargs
    ) -> PowerControllerInterface:
        """
        Create a power controller instance.
        
        Args:
            power_type: Type of power implementation (smart_plug, network, adb, etc.)
            device_name: Name of the device for logging
            **kwargs: Additional parameters for the controller
        
        Returns:
            PowerControllerInterface: Controller instance
        """
        controller_class = CONTROLLER_REGISTRY['power'].get(power_type)
        if not controller_class:
            raise ValueError(f"Unknown power controller type: {power_type}")
        
        return controller_class(device_name=device_name, power_type=power_type, **kwargs)
    
    @staticmethod
    def register_controller(
        controller_type: str,
        implementation_name: str,
        controller_class: Type[BaseController]
    ) -> None:
        """
        Register a new controller implementation.
        
        Args:
            controller_type: Type of controller (remote, av, verification, power)
            implementation_name: Name for this implementation
            controller_class: Controller class to register
        """
        if controller_type not in CONTROLLER_REGISTRY:
            CONTROLLER_REGISTRY[controller_type] = {}
        
        CONTROLLER_REGISTRY[controller_type][implementation_name] = controller_class
        print(f"Registered {controller_type} controller: {implementation_name}")
    
    @staticmethod
    def list_available_controllers() -> Dict[str, list]:
        """
        List all available controller implementations.
        
        Returns:
            Dict mapping controller types to available implementations
        """
        return {
            controller_type: list(implementations.keys())
            for controller_type, implementations in CONTROLLER_REGISTRY.items()
        }

# Export main classes and functions
__all__ = [
    'BaseController',
    'RemoteControllerInterface',
    'AVControllerInterface',
    'VerificationControllerInterface',
    'PowerControllerInterface',
    'ControllerFactory',
    'CONTROLLER_REGISTRY'
]
