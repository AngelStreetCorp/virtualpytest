"""
PyAutoGUI Desktop Controller Implementation

This controller provides PyAutoGUI cross-platform GUI automation functionality.
Works on Windows, Linux, and ARM (Raspberry Pi) - assumes PyAutoGUI is installed on the system.

SECURITY: This controller includes protections against dangerous operations:
- Blocked commands and patterns (file deletion, system commands, etc.)
- Restricted file/directory access (config files, system paths, etc.)
- Application launch restrictions
"""

from typing import Dict, Any, List, Optional
import time
import re
from ..base_controller import DesktopControllerInterface

# Import basic modules at module level
import os
import sys

# Global flag to track availability - will be set during first controller instantiation
PYAUTOGUI_AVAILABLE = None
pyautogui = None

# =====================================================
# SECURITY CONFIGURATION
# =====================================================

# Dangerous command patterns that should be blocked
BLOCKED_COMMAND_PATTERNS = [
    # File operations
    r'\brm\b.*-rf',
    r'\brm\b.*-fr',
    r'\brm\s+-[a-zA-Z]*r[a-zA-Z]*f',
    r'\brm\s+-[a-zA-Z]*f[a-zA-Z]*r',
    r'\brmdir\b',
    r'\bdel\b.*\/[sS]',
    r'\brd\b.*\/[sS]',
    
    # System commands
    r'\bshutdown\b',
    r'\breboot\b',
    r'\binit\s+[06]',
    r'\bpoweroff\b',
    r'\bhalt\b',
    r'\bkillall\b',
    r'\bpkill\b',
    
    # User/permission changes
    r'\bsudo\b',
    r'\bsu\s',
    r'\bchmod\b.*777',
    r'\bchown\b',
    r'\buseradd\b',
    r'\busermod\b',
    r'\buserdel\b',
    
    # Package management
    r'\bapt\s+remove',
    r'\bapt\s+purge',
    r'\byum\s+remove',
    r'\bdnf\s+remove',
    r'\bpip\s+uninstall',
    r'\bnpm\s+uninstall',
    
    # Process manipulation
    r'\bkill\s+-9',
    r'\bkill\s+-KILL',
    
    # Network/firewall
    r'\biptables\b',
    r'\bufw\b',
    r'\bfirewall-cmd\b',
    
    # Disk operations
    r'\bdd\b.*if=',
    r'\bmkfs\b',
    r'\bfdisk\b',
    r'\bparted\b',
    
    # Archive extraction in root
    r'\btar\b.*-x.*\s+/',
    r'\bunzip\b.*\s+/',
    
    # Command chaining (to bypass other checks)
    r'[;&|]\s*rm\b',
    r'[;&|]\s*sudo\b',
    r'`.*rm\b',
    r'\$\(.*rm\b',
]

# Sensitive file patterns to block
BLOCKED_FILE_PATTERNS = [
    r'\.env',
    r'\.env\.',
    r'password',
    r'passwd',
    r'shadow',
    r'secret',
    r'credentials',
    r'\.ssh',
    r'id_rsa',
    r'\.pem',
    r'\.key',
    r'\.cert',
    r'\.crt',
    r'config\.json',
    r'\.aws',
    r'\.kube',
    r'/etc/passwd',
    r'/etc/shadow',
    r'/etc/sudoers',
]

# Sensitive directories to block
BLOCKED_DIRECTORIES = [
    '/etc',
    '/sys',
    '/proc',
    '/dev',
    '/boot',
    '/root',
    '~/.ssh',
    '~/.aws',
    '~/.kube',
    '/var/lib',
    '/usr/bin',
    '/usr/sbin',
    '/sbin',
    'C:\\Windows\\System32',
    'C:\\Windows\\SysWOW64',
]

# Blocked applications (dangerous to launch)
BLOCKED_APPLICATIONS = [
    'sudo',
    'su',
    'passwd',
    'shutdown',
    'reboot',
    'init',
    'systemctl',
    'service',
    'rm',
    'dd',
    'fdisk',
    'mkfs',
    'iptables',
    'ufw',
    'firewall-cmd',
]


class PyAutoGUIDesktopController(DesktopControllerInterface):
    """PyAutoGUI desktop controller for cross-platform GUI automation."""
    
    def __init__(self, **kwargs):
        """Initialize the PyAutoGUI desktop controller."""
        super().__init__("PyAutoGUI Desktop", "pyautogui")
        
        # Command execution state
        self.last_command_output = ""
        self.last_command_error = ""
        self.last_exit_code = 0
        
        # Initialize PyAutoGUI on first controller instantiation - wrapped in try-catch
        try:
            self._initialize_pyautogui()
        except Exception as e:
            global PYAUTOGUI_AVAILABLE
            PYAUTOGUI_AVAILABLE = False
            print(f"[@controller:PyAutoGUIDesktop] WARNING: PyAutoGUI initialization exception: {e}")
            print(f"[@controller:PyAutoGUIDesktop] Controller created but PyAutoGUI unavailable")
            return  # Exit early but don't crash
        
        if not PYAUTOGUI_AVAILABLE:
            print(f"[@controller:PyAutoGUIDesktop] WARNING: PyAutoGUI module not available. Please install pyautogui")
        else:
            print(f"[@controller:PyAutoGUIDesktop] Initialized for cross-platform GUI automation")
            print(f"[@controller:PyAutoGUIDesktop] Security protections enabled")
    
    def _validate_text_input(self, text: str) -> tuple[bool, str]:
        """
        Validate text input for security concerns.
        
        Args:
            text: Text to validate
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        if not text:
            return True, ""
        
        # Check for dangerous command patterns
        for pattern in BLOCKED_COMMAND_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                error_msg = f"SECURITY BLOCK: Text contains blocked command pattern: {pattern}"
                print(f"[@controller:PyAutoGUIDesktop] {error_msg}")
                return False, error_msg
        
        # Check for sensitive file patterns
        for pattern in BLOCKED_FILE_PATTERNS:
            if re.search(pattern, text, re.IGNORECASE):
                error_msg = f"SECURITY BLOCK: Text references blocked file pattern: {pattern}"
                print(f"[@controller:PyAutoGUIDesktop] {error_msg}")
                return False, error_msg
        
        # Check for sensitive directory patterns
        for blocked_dir in BLOCKED_DIRECTORIES:
            if blocked_dir.lower() in text.lower():
                error_msg = f"SECURITY BLOCK: Text references blocked directory: {blocked_dir}"
                print(f"[@controller:PyAutoGUIDesktop] {error_msg}")
                return False, error_msg
        
        return True, ""
    
    def _validate_application(self, app_name: str) -> tuple[bool, str]:
        """
        Validate application launch for security concerns.
        
        Args:
            app_name: Application name to validate
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        if not app_name:
            return False, "Application name is required"
        
        # Extract base command name (without path or arguments)
        base_app = os.path.basename(app_name).split()[0].lower()
        
        # Check against blocked applications
        for blocked_app in BLOCKED_APPLICATIONS:
            if blocked_app.lower() in base_app:
                error_msg = f"SECURITY BLOCK: Application '{app_name}' is blocked for security reasons"
                print(f"[@controller:PyAutoGUIDesktop] {error_msg}")
                return False, error_msg
        
        # Additional check for shell commands
        if base_app in ['bash', 'sh', 'zsh', 'fish', 'cmd', 'powershell', 'pwsh']:
            error_msg = f"SECURITY BLOCK: Shell/terminal applications are blocked: {app_name}"
            print(f"[@controller:PyAutoGUIDesktop] {error_msg}")
            return False, error_msg
        
        return True, ""
    
    def _validate_image_path(self, image_path: str) -> tuple[bool, str]:
        """
        Validate image path for security concerns.
        
        Args:
            image_path: Image path to validate
            
        Returns:
            Tuple of (is_valid, error_message)
        """
        if not image_path:
            return False, "Image path is required"
        
        # Check for directory traversal
        if '..' in image_path:
            error_msg = f"SECURITY BLOCK: Directory traversal detected in path: {image_path}"
            print(f"[@controller:PyAutoGUIDesktop] {error_msg}")
            return False, error_msg
        
        # Check for sensitive directories
        for blocked_dir in BLOCKED_DIRECTORIES:
            if image_path.startswith(blocked_dir):
                error_msg = f"SECURITY BLOCK: Image path in blocked directory: {blocked_dir}"
                print(f"[@controller:PyAutoGUIDesktop] {error_msg}")
                return False, error_msg
        
        return True, ""
    
    def _initialize_pyautogui(self):
        """Initialize PyAutoGUI module - only called once per controller instantiation."""
        global PYAUTOGUI_AVAILABLE, pyautogui
        
        # Skip if already initialized
        if PYAUTOGUI_AVAILABLE is not None:
            return
        
        try:
            # On Linux, check if a display is available before importing
            if sys.platform.startswith('linux'):
                display = os.environ.get('DISPLAY')
                
                # If no DISPLAY set, try to set :1 for VNC
                if not display:
                    print(f"[@controller:PyAutoGUIDesktop] Setting DISPLAY to :1 for VNC environment")
                    os.environ['DISPLAY'] = ':1'
                    display = ':1'
                
                # Verify the display actually exists by trying to connect
                try:
                    import subprocess
                    # Quick check if X server is accessible (timeout after 2 seconds)
                    result = subprocess.run(
                        ['xdpyinfo', '-display', display],
                        capture_output=True,
                        timeout=2
                    )
                    if result.returncode != 0:
                        print(f"[@controller:PyAutoGUIDesktop] WARNING: Display {display} not accessible (xdpyinfo failed)")
                        print(f"[@controller:PyAutoGUIDesktop] Skipping PyAutoGUI - no working display")
                        PYAUTOGUI_AVAILABLE = False
                        return
                except FileNotFoundError:
                    # xdpyinfo not installed, try a different method
                    print(f"[@controller:PyAutoGUIDesktop] xdpyinfo not found, attempting direct import...")
                except subprocess.TimeoutExpired:
                    print(f"[@controller:PyAutoGUIDesktop] WARNING: Display {display} check timed out")
                    print(f"[@controller:PyAutoGUIDesktop] Skipping PyAutoGUI - display not responding")
                    PYAUTOGUI_AVAILABLE = False
                    return
                except Exception as e:
                    print(f"[@controller:PyAutoGUIDesktop] Display check error: {e}, attempting import anyway...")
            
            # IMPORTANT: Mock mouseinfo module BEFORE importing pyautogui to avoid tkinter requirement
            # MouseInfo is optional and causes "NOTE: You must install tkinter" messages that can crash
            try:
                # Create a dummy mouseinfo module to prevent pyautogui from trying to import it
                import types
                dummy_mouseinfo = types.ModuleType('mouseinfo')
                dummy_mouseinfo.MouseInfoWindow = None
                sys.modules['mouseinfo'] = dummy_mouseinfo
                print(f"[@controller:PyAutoGUIDesktop] Disabled MouseInfo to avoid tkinter dependency")
            except Exception as mock_err:
                print(f"[@controller:PyAutoGUIDesktop] Could not mock mouseinfo: {mock_err}")
            
            import pyautogui as _pyautogui
            
            # Configure PyAutoGUI safety features
            _pyautogui.FAILSAFE = True  # Move mouse to corner to abort
            _pyautogui.PAUSE = 0.1      # Short pause between actions
            
            # Set global variables
            pyautogui = _pyautogui
            PYAUTOGUI_AVAILABLE = True
            print(f"[@controller:PyAutoGUIDesktop] PyAutoGUI initialized successfully with DISPLAY={os.environ.get('DISPLAY')}")
        except ImportError as e:
            PYAUTOGUI_AVAILABLE = False
            print(f"[@controller:PyAutoGUIDesktop] WARNING: PyAutoGUI module not available: {e}")
        except Exception as e:
            print(f"[@controller:PyAutoGUIDesktop] WARNING: PyAutoGUI initialization failed: {e}")
            PYAUTOGUI_AVAILABLE = False
    
    def connect(self) -> bool:
        """Connect to PyAutoGUI service (always true for local execution)."""
        if not PYAUTOGUI_AVAILABLE:
            print(f"Desktop[{self.desktop_type.upper()}]: ERROR - PyAutoGUI not available")
            return False
        
        print(f"Desktop[{self.desktop_type.upper()}]: Cross-platform GUI automation ready")
        return True
            
    def disconnect(self) -> bool:
        """Disconnect from PyAutoGUI service (always true for local execution)."""
        print(f"Desktop[{self.desktop_type.upper()}]: Cross-platform GUI automation disconnected")
        return True
            
    def execute_command(self, command: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """
        Execute PyAutoGUI command for GUI automation.
        
        Args:
            command: Command type (click, rightclick, doubleclick, keypress, type, screenshot, locate)
            params: Command parameters containing PyAutoGUI-specific arguments
            
        Returns:
            Dict: Command execution result
        """
        if params is None:
            params = {}
        
        if not PYAUTOGUI_AVAILABLE:
            return {
                'success': False,
                'output': '',
                'error': 'PyAutoGUI module not available',
                'exit_code': -1,
                'execution_time': 0
            }
        
        print(f"Desktop[{self.desktop_type.upper()}]: Executing command '{command}' with params: {params}")
        
        start_time = time.time()
        
        try:
            if command == 'execute_ldtp_click' or command == 'execute_pyautogui_click':
                x = params.get('x')
                y = params.get('y')
                
                if x is None or y is None:
                    return self._error_result('Missing x or y coordinates for click', start_time)
                
                print(f"Desktop[{self.desktop_type.upper()}]: Clicking at coordinates ({x}, {y})")
                pyautogui.click(x, y)
                return self._success_result(f"Click executed at ({x}, {y})", start_time)
                
            elif command == 'execute_ldtp_rightclick' or command == 'execute_pyautogui_rightclick':
                x = params.get('x')
                y = params.get('y')
                
                if x is None or y is None:
                    return self._error_result('Missing x or y coordinates for rightclick', start_time)
                
                print(f"Desktop[{self.desktop_type.upper()}]: Right-clicking at coordinates ({x}, {y})")
                pyautogui.rightClick(x, y)
                return self._success_result(f"Right-click executed at ({x}, {y})", start_time)
                
            elif command == 'execute_ldtp_doubleclick' or command == 'execute_pyautogui_doubleclick':
                x = params.get('x')
                y = params.get('y')
                
                if x is None or y is None:
                    return self._error_result('Missing x or y coordinates for doubleclick', start_time)
                
                print(f"Desktop[{self.desktop_type.upper()}]: Double-clicking at coordinates ({x}, {y})")
                pyautogui.doubleClick(x, y)
                return self._success_result(f"Double-click executed at ({x}, {y})", start_time)
                
            elif command == 'execute_ldtp_keypress' or command == 'execute_pyautogui_keypress':
                key = params.get('key')
                keys = params.get('keys')  # For key combinations
                
                if key:
                    # Map user-friendly key names to PyAutoGUI format (lowercase)
                    # PyAutoGUI expects lowercase key names
                    key_mapping = {
                        'BACK': 'esc',
                        'ESC': 'esc',
                        'ESCAPE': 'esc',
                        'OK': 'enter',
                        'ENTER': 'enter',
                        'RETURN': 'enter',
                        'HOME': 'home',
                        'END': 'end',
                        'UP': 'up',
                        'DOWN': 'down',
                        'LEFT': 'left',
                        'RIGHT': 'right',
                        'TAB': 'tab',
                        'SPACE': 'space',
                        'DELETE': 'delete',
                        'DEL': 'delete',
                        'BACKSPACE': 'backspace',
                        'PAGEUP': 'pageup',
                        'PAGEDOWN': 'pagedown',
                        'PGUP': 'pageup',
                        'PGDN': 'pagedown',
                        'INSERT': 'insert',
                        'PAUSE': 'pause',
                        'PRINTSCREEN': 'printscreen',
                        'PRTSC': 'printscreen',
                        'CTRL': 'ctrl',
                        'ALT': 'alt',
                        'SHIFT': 'shift',
                        'WIN': 'win',
                        'WINLEFT': 'winleft',
                        'WINRIGHT': 'winright',
                        'COMMAND': 'command',
                        'CMD': 'command',
                        'CAPSLOCK': 'capslock',
                        'NUMLOCK': 'numlock',
                        'SCROLLLOCK': 'scrolllock',
                        'F1': 'f1', 'F2': 'f2', 'F3': 'f3', 'F4': 'f4',
                        'F5': 'f5', 'F6': 'f6', 'F7': 'f7', 'F8': 'f8',
                        'F9': 'f9', 'F10': 'f10', 'F11': 'f11', 'F12': 'f12'
                    }
                    
                    # Normalize key to PyAutoGUI format
                    pyautogui_key = key_mapping.get(key.upper(), key.lower())
                    
                    print(f"Desktop[{self.desktop_type.upper()}]: Pressing key: {key} -> {pyautogui_key}")
                    try:
                        pyautogui.press(pyautogui_key)
                        return self._success_result(f"Key pressed: {key} -> {pyautogui_key}", start_time)
                    except Exception as e:
                        # Return raw PyAutoGUI error for easier debugging
                        error_msg = f"PyAutoGUI error for key '{pyautogui_key}': {str(e)}"
                        print(f"Desktop[{self.desktop_type.upper()}]: ERROR - {error_msg}")
                        return self._error_result(error_msg, start_time)
                elif keys:
                    print(f"Desktop[{self.desktop_type.upper()}]: Pressing key combination: {keys}")
                    try:
                        # Map each key in combination
                        key_mapping = {
                            'CTRL': 'ctrl', 'ALT': 'alt', 'SHIFT': 'shift',
                            'WIN': 'win', 'COMMAND': 'command', 'CMD': 'command'
                        }
                        mapped_keys = [key_mapping.get(k.upper(), k.lower()) for k in keys]
                        pyautogui.hotkey(*mapped_keys)
                        return self._success_result(f"Key combination pressed: {keys} -> {mapped_keys}", start_time)
                    except Exception as e:
                        # Return raw PyAutoGUI error for easier debugging
                        error_msg = f"PyAutoGUI error for keys {keys}: {str(e)}"
                        print(f"Desktop[{self.desktop_type.upper()}]: ERROR - {error_msg}")
                        return self._error_result(error_msg, start_time)
                else:
                    return self._error_result('Missing key or keys for keypress', start_time)
                
            elif command == 'execute_ldtp_enterstring' or command == 'execute_pyautogui_type':
                text = params.get('text')
                interval = params.get('interval', 0.0)  # Delay between keystrokes
                
                if text is None:
                    return self._error_result('Missing text for type', start_time)
                
                # SECURITY: Validate text input
                is_valid, error_msg = self._validate_text_input(text)
                if not is_valid:
                    return self._error_result(error_msg, start_time)
                
                print(f"Desktop[{self.desktop_type.upper()}]: Typing text: '{text}'")
                pyautogui.typewrite(text, interval=interval)
                return self._success_result(f"Text typed: {text}", start_time)
                
            elif command == 'execute_pyautogui_screenshot':
                filename = params.get('filename')
                region = params.get('region')  # (left, top, width, height)
                
                print(f"Desktop[{self.desktop_type.upper()}]: Taking screenshot")
                if region:
                    screenshot = pyautogui.screenshot(region=region)
                else:
                    screenshot = pyautogui.screenshot()
                
                if filename:
                    screenshot.save(filename)
                    return self._success_result(f"Screenshot saved to: {filename}", start_time)
                else:
                    return self._success_result(f"Screenshot taken (not saved)", start_time)
                
            elif command == 'execute_pyautogui_locate':
                image_path = params.get('image_path')
                confidence = params.get('confidence', 0.9)
                region = params.get('region')  # (left, top, width, height)
                
                if not image_path:
                    return self._error_result('Missing image_path for locate', start_time)
                
                # SECURITY: Validate image path
                is_valid, error_msg = self._validate_image_path(image_path)
                if not is_valid:
                    return self._error_result(error_msg, start_time)
                
                print(f"Desktop[{self.desktop_type.upper()}]: Locating image: {image_path}")
                try:
                    if region:
                        location = pyautogui.locateOnScreen(image_path, confidence=confidence, region=region)
                    else:
                        location = pyautogui.locateOnScreen(image_path, confidence=confidence)
                    
                    if location:
                        return self._success_result(f"Image found at: {location}", start_time)
                    else:
                        return self._error_result(f"Image not found: {image_path}", start_time)
                except pyautogui.ImageNotFoundException:
                    return self._error_result(f"Image not found: {image_path}", start_time)
                
            elif command == 'execute_pyautogui_locate_and_click':
                image_path = params.get('image_path')
                confidence = params.get('confidence', 0.9)
                region = params.get('region')  # (left, top, width, height)
                
                if not image_path:
                    return self._error_result('Missing image_path for locate_and_click', start_time)
                
                # SECURITY: Validate image path
                is_valid, error_msg = self._validate_image_path(image_path)
                if not is_valid:
                    return self._error_result(error_msg, start_time)
                
                print(f"Desktop[{self.desktop_type.upper()}]: Locating and clicking image: {image_path}")
                try:
                    if region:
                        location = pyautogui.locateOnScreen(image_path, confidence=confidence, region=region)
                    else:
                        location = pyautogui.locateOnScreen(image_path, confidence=confidence)
                    
                    if location:
                        center = pyautogui.center(location)
                        pyautogui.click(center)
                        return self._success_result(f"Image found and clicked at: {center}", start_time)
                    else:
                        return self._error_result(f"Image not found: {image_path}", start_time)
                except pyautogui.ImageNotFoundException:
                    return self._error_result(f"Image not found: {image_path}", start_time)
                
            elif command == 'execute_pyautogui_move':
                x = params.get('x')
                y = params.get('y')
                duration = params.get('duration', 0.0)
                
                if x is None or y is None:
                    return self._error_result('Missing x or y coordinates for move', start_time)
                
                print(f"Desktop[{self.desktop_type.upper()}]: Moving mouse to ({x}, {y})")
                pyautogui.moveTo(x, y, duration=duration)
                return self._success_result(f"Mouse moved to ({x}, {y})", start_time)
                
            elif command == 'execute_pyautogui_scroll':
                clicks = params.get('clicks', 1)
                x = params.get('x')
                y = params.get('y')
                
                if x is not None and y is not None:
                    print(f"Desktop[{self.desktop_type.upper()}]: Scrolling {clicks} clicks at ({x}, {y})")
                    pyautogui.scroll(clicks, x=x, y=y)
                else:
                    print(f"Desktop[{self.desktop_type.upper()}]: Scrolling {clicks} clicks at current position")
                    pyautogui.scroll(clicks)
                return self._success_result(f"Scrolled {clicks} clicks", start_time)
                
            elif command == 'execute_pyautogui_launch':
                app_name = params.get('app_name')
                
                if not app_name:
                    return self._error_result('Missing app_name for launch', start_time)
                
                # SECURITY: Validate application name
                is_valid, error_msg = self._validate_application(app_name)
                if not is_valid:
                    return self._error_result(error_msg, start_time)
                
                print(f"Desktop[{self.desktop_type.upper()}]: Launching application: {app_name}")
                
                # Use subprocess to launch applications on Windows
                import subprocess
                import sys
                
                try:
                    if sys.platform.startswith('win'):
                        # Windows - try common methods
                        if app_name.lower() in ['notepad', 'calc', 'mspaint']:
                            subprocess.Popen([app_name])
                        else:
                            # Try to run as command (shell=False is safer)
                            subprocess.Popen([app_name])
                    else:
                        # Linux/Mac - use which to find the application
                        subprocess.Popen([app_name])
                    
                    return self._success_result(f"Application launched: {app_name}", start_time)
                except Exception as e:
                    return self._error_result(f"Failed to launch {app_name}: {e}", start_time)
                
            else:
                print(f"Desktop[{self.desktop_type.upper()}]: Unknown command: {command}")
                return {
                    'success': False,
                    'output': '',
                    'error': f'Unknown PyAutoGUI command: {command}',
                    'exit_code': -1,
                    'execution_time': int((time.time() - start_time) * 1000)
                }
                
        except Exception as e:
            execution_time = int((time.time() - start_time) * 1000)
            error_msg = f"PyAutoGUI command execution error: {e}"
            print(f"Desktop[{self.desktop_type.upper()}]: {error_msg}")
            
            return {
                'success': False,
                'output': '',
                'error': error_msg,
                'exit_code': -1,
                'execution_time': execution_time
            }
    
    def _success_result(self, output: str, start_time: float) -> Dict[str, Any]:
        """Helper to create success result."""
        execution_time = int((time.time() - start_time) * 1000)
        
        # Store last command results
        self.last_command_output = output
        self.last_command_error = ""
        self.last_exit_code = 0
        
        print(f"Desktop[{self.desktop_type.upper()}]: {output} - SUCCESS")
        
        return {
            'success': True,
            'output': output,
            'error': '',
            'exit_code': 0,
            'execution_time': execution_time
        }
    
    def _error_result(self, error: str, start_time: float) -> Dict[str, Any]:
        """Helper to create error result."""
        execution_time = int((time.time() - start_time) * 1000)
        
        # Store last command results
        self.last_command_output = ""
        self.last_command_error = error
        self.last_exit_code = -1
        
        print(f"Desktop[{self.desktop_type.upper()}]: {error} - FAILED")
        
        return {
            'success': False,
            'output': '',
            'error': error,
            'exit_code': -1,
            'execution_time': execution_time
        }
    
    def get_available_actions(self) -> Dict[str, Any]:
        """Get available actions for PyAutoGUI desktop controller."""
        return {
            'Desktop': [
                # Click actions
                {
                    'id': 'pyautogui_click',
                    'label': 'Click Coordinates',
                    'command': 'execute_pyautogui_click',
                    'action_type': 'desktop',
                    'params': {},
                    'description': 'Click at specific screen coordinates',
                    'requiresInput': True,
                    'inputLabel': 'Coordinates (x,y)',
                    'inputPlaceholder': '100,200'
                },
                {
                    'id': 'pyautogui_rightclick',
                    'label': 'Right Click Coordinates',
                    'command': 'execute_pyautogui_rightclick',
                    'action_type': 'desktop',
                    'params': {},
                    'description': 'Right-click at specific screen coordinates',
                    'requiresInput': True,
                    'inputLabel': 'Coordinates (x,y)',
                    'inputPlaceholder': '100,200'
                },
                {
                    'id': 'pyautogui_doubleclick',
                    'label': 'Double Click Coordinates',
                    'command': 'execute_pyautogui_doubleclick',
                    'action_type': 'desktop',
                    'params': {},
                    'description': 'Double-click at specific screen coordinates',
                    'requiresInput': True,
                    'inputLabel': 'Coordinates (x,y)',
                    'inputPlaceholder': '100,200'
                },
                # Keyboard actions
                {
                    'id': 'pyautogui_keypress',
                    'label': 'Press Key',
                    'command': 'execute_pyautogui_keypress',
                    'action_type': 'desktop',
                    'params': {},
                    'description': 'Press keyboard key',
                    'requiresInput': True,
                    'inputLabel': 'Key',
                    'inputPlaceholder': 'down',
                    'options': ['enter', 'space', 'tab', 'esc', 'backspace', 'delete', 'up', 'down', 'left', 'right', 'home', 'end', 'pageup', 'pagedown', 'ctrl', 'alt', 'shift', 'f1', 'f2', 'f3', 'f4', 'f5', 'f6', 'f7', 'f8', 'f9', 'f10', 'f11', 'f12']
                },
                {
                    'id': 'pyautogui_type',
                    'label': 'Type Text',
                    'command': 'execute_pyautogui_type',
                    'action_type': 'desktop',
                    'params': {},
                    'description': 'Type text at current cursor position',
                    'requiresInput': True,
                    'inputLabel': 'Text to type',
                    'inputPlaceholder': 'Hello World'
                },
                # Mouse actions
                {
                    'id': 'pyautogui_move',
                    'label': 'Move Mouse',
                    'command': 'execute_pyautogui_move',
                    'action_type': 'desktop',
                    'params': {},
                    'description': 'Move mouse to specific coordinates',
                    'requiresInput': True,
                    'inputLabel': 'Coordinates (x,y)',
                    'inputPlaceholder': '100,200'
                },
                {
                    'id': 'pyautogui_scroll',
                    'label': 'Scroll',
                    'command': 'execute_pyautogui_scroll',
                    'action_type': 'desktop',
                    'params': {},
                    'description': 'Scroll up (positive) or down (negative)',
                    'requiresInput': True,
                    'inputLabel': 'Scroll clicks (positive=up, negative=down)',
                    'inputPlaceholder': '3'
                },
                # Image-based actions
                {
                    'id': 'pyautogui_locate',
                    'label': 'Locate Image',
                    'command': 'execute_pyautogui_locate',
                    'action_type': 'desktop',
                    'params': {},
                    'description': 'Find an image on screen',
                    'requiresInput': True,
                    'inputLabel': 'Image file path',
                    'inputPlaceholder': '/path/to/image.png'
                },
                {
                    'id': 'pyautogui_locate_and_click',
                    'label': 'Locate and Click Image',
                    'command': 'execute_pyautogui_locate_and_click',
                    'action_type': 'desktop',
                    'params': {},
                    'description': 'Find an image on screen and click it',
                    'requiresInput': True,
                    'inputLabel': 'Image file path',
                    'inputPlaceholder': '/path/to/image.png'
                },
                # App launch action
                {
                    'id': 'pyautogui_launch',
                    'label': 'Launch Application',
                    'command': 'execute_pyautogui_launch',
                    'action_type': 'desktop',
                    'params': {},
                    'description': 'Launch an application',
                    'requiresInput': True,
                    'inputLabel': 'Application name',
                    'inputPlaceholder': 'notepad, calc, firefox'
                },
                # Screenshot action
                {
                    'id': 'pyautogui_screenshot',
                    'label': 'Take Screenshot',
                    'command': 'execute_pyautogui_screenshot',
                    'action_type': 'desktop',
                    'params': {},
                    'description': 'Take a screenshot',
                    'requiresInput': False
                }
            ]
        } 