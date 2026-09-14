"""
Lightweight WebKit Browser Utilities for Playwright

Minimal implementation using WebKit (Safari engine) - the lightest browser option.
Supports debug mode connections like Chrome but with much lower resource usage.
"""

import os
import time
import subprocess
import socket
import asyncio
import platform
from typing import Dict, Any, Tuple

from shared.src.lib.utils.browser_window_utils import build_window_flags, detect_primary_display_bounds

WEBKIT_LAUNCH_READY_TIMEOUT_SECONDS = 12


def resolve_user_data_dir(user_data_dir: str) -> str:
    """Resolve user_data_dir to absolute path from project root."""
    if os.path.isabs(user_data_dir):
        return user_data_dir

    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
    return os.path.abspath(os.path.join(project_root, user_data_dir.lstrip('./')))


class WebKitManager:
    """Manages WebKit process lifecycle for remote debugging - lightweight alternative to Chrome."""

    @staticmethod
    def _is_windows() -> bool:
        return platform.system() == "Windows"

    @staticmethod
    def _windows_browser_candidates() -> list:
        local_app_data = os.environ.get('LOCALAPPDATA', '')
        program_files = os.environ.get('PROGRAMFILES', r'C:\Program Files')
        program_files_x86 = os.environ.get('PROGRAMFILES(X86)', r'C:\Program Files (x86)')
        return [
            (os.path.join(program_files, 'Google', 'Chrome', 'Application', 'chrome.exe'), 'chrome'),
            (os.path.join(program_files_x86, 'Google', 'Chrome', 'Application', 'chrome.exe'), 'chrome'),
            (os.path.join(local_app_data, 'Google', 'Chrome', 'Application', 'chrome.exe'), 'chrome'),
            (os.path.join(program_files, 'Microsoft', 'Edge', 'Application', 'msedge.exe'), 'msedge'),
            (os.path.join(program_files_x86, 'Microsoft', 'Edge', 'Application', 'msedge.exe'), 'msedge'),
            (os.path.join(local_app_data, 'Microsoft', 'Edge', 'Application', 'msedge.exe'), 'msedge'),
            (os.path.join(program_files, 'Chromium', 'Application', 'chrome.exe'), 'chromium'),
            (os.path.join(program_files_x86, 'Chromium', 'Application', 'chrome.exe'), 'chromium'),
        ]

    @classmethod
    def get_launch_diagnostics(cls, debug_port: int = 9223, user_data_dir: str = "./backend_host/config/webkit_user_data") -> Dict[str, Any]:
        diagnostics: Dict[str, Any] = {
            'platform': platform.system(),
            'debug_port': debug_port,
            'user_data_dir': user_data_dir,
            'cwd': os.getcwd(),
            'display': os.environ.get('DISPLAY', ''),
            'host_type': os.getenv('HOST_TYPE', ''),
            'port_in_use': False,
            'candidates': [],
        }
        try:
            diagnostics['port_in_use'] = cls.is_port_in_use(debug_port)
        except Exception as exc:
            diagnostics['port_check_error'] = str(exc)

        if cls._is_windows():
            candidates = cls._windows_browser_candidates()
        else:
            candidates = [
                ('/Applications/Safari.app/Contents/MacOS/Safari', 'safari'),
                ('/usr/bin/chromium', 'chromium-webkit'),
                ('/usr/bin/chromium-browser', 'chromium-webkit'),
                ('/usr/bin/google-chrome', 'chrome-webkit'),
                ('/usr/bin/firefox', 'firefox'),
            ]
        for path, browser_type in candidates:
            diagnostics['candidates'].append({
                'path': path,
                'browser_type': browser_type,
                'exists': bool(path and os.path.exists(path)),
            })

        try:
            resolved_path, browser_type = cls.find_webkit_executable()
            diagnostics['resolved_executable'] = resolved_path
            diagnostics['resolved_browser_type'] = browser_type
        except Exception as exc:
            diagnostics['resolve_error'] = str(exc)
        return diagnostics

    @classmethod
    def _kill_existing_browser_processes(cls, browsers_to_kill: list) -> None:
        if cls._is_windows():
            for browser in browsers_to_kill:
                image_name = f'{browser}.exe'
                try:
                    result = subprocess.run(
                        ['taskkill', '/F', '/IM', image_name, '/T'],
                        capture_output=True,
                        text=True,
                        timeout=10,
                    )
                    if result.returncode == 0:
                        print(f'[WebKitManager] Killed existing {image_name} processes')
                except Exception:
                    pass
            return

        for browser in browsers_to_kill:
            try:
                result = subprocess.run(['pkill', '-9', browser], capture_output=True, timeout=5)
                if result.returncode == 0:
                    print(f'[WebKitManager] Killed existing {browser} processes')
            except Exception:
                pass

    @classmethod
    def _kill_processes_on_port(cls, debug_port: int) -> None:
        if not cls.is_port_in_use(debug_port):
            return

        print(f'[WebKitManager] Port {debug_port} is in use. Killing processes...')
        if cls._is_windows():
            try:
                result = subprocess.run(
                    ['netstat', '-ano'],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if result.returncode == 0 and result.stdout:
                    killed = set()
                    for line in result.stdout.splitlines():
                        if f':{debug_port}' not in line or 'LISTENING' not in line.upper():
                            continue
                        parts = [part for part in line.split() if part]
                        if not parts:
                            continue
                        pid = parts[-1]
                        if pid in killed:
                            continue
                        subprocess.run(['taskkill', '/F', '/PID', pid, '/T'], timeout=5)
                        killed.add(pid)
                        print(f'[WebKitManager] Killed process {pid} using port {debug_port}')
            except Exception as e:
                print(f'[WebKitManager] Error killing processes on port {debug_port}: {e}')
            return

        try:
            result = subprocess.run(['lsof', '-ti', f':{debug_port}'],
                                  capture_output=True, text=True, timeout=5)
            if result.returncode == 0 and result.stdout.strip():
                pids = result.stdout.strip().split('\n')
                for pid in pids:
                    if pid.strip():
                        subprocess.run(['kill', '-9', pid.strip()], timeout=3)
                        print(f'[WebKitManager] Killed process {pid.strip()} using port {debug_port}')
        except Exception as e:
            print(f'[WebKitManager] Error killing processes on port {debug_port}: {e}')

    @staticmethod
    def find_webkit_executable() -> tuple:
        """Find WebKit/Safari executable on system. Returns (path, browser_type)."""
        if WebKitManager._is_windows():
            for path, browser_type in WebKitManager._windows_browser_candidates():
                if path and os.path.exists(path):
                    if browser_type in ('chrome', 'chromium', 'msedge'):
                        return (path, 'chrome-webkit')
                    return (path, browser_type)
            raise ValueError('No suitable Windows browser found. Install Google Chrome, Microsoft Edge, or Chromium.')

        # On macOS, use Safari
        if os.path.exists('/Applications/Safari.app/Contents/MacOS/Safari'):
            return ('/Applications/Safari.app/Contents/MacOS/Safari', 'safari')
        
        # On Linux, try to find webkit-based browsers with debug support
        webkit_browsers = [
            ('/usr/bin/chromium', 'chromium-webkit'),          # Chromium (Debian/Ubuntu default)
            ('/usr/bin/chromium-browser', 'chromium-webkit'),  # Chromium with WebKit flags
            ('/usr/bin/google-chrome', 'chrome-webkit'),       # Chrome with WebKit-like flags
            ('/usr/bin/firefox', 'firefox'),                   # Firefox as lightweight alternative
        ]
        
        for path, browser_type in webkit_browsers:
            if os.path.exists(path):
                return (path, browser_type)
                
        raise ValueError('No suitable lightweight browser found. Install chromium-browser, google-chrome, or firefox')
    
    @staticmethod
    def get_webkit_flags(debug_port: int = 9223, browser_type: str = 'chromium-webkit', user_data_dir: str = "./backend_host/config/webkit_user_data") -> list:
        """Get browser launch flags for remote debugging based on browser type."""
        if browser_type == 'firefox':
            # Firefox remote debugging flags
            return [
                f'--remote-debugging-port={debug_port}',
                f'--profile={user_data_dir}',  # Firefox uses --profile instead of --user-data-dir
                '--headless=false',  # Keep visible
                '--new-instance',
                '--no-remote',
            ]
        elif browser_type in ['chromium-webkit', 'chrome-webkit']:
            host_type = os.getenv('HOST_TYPE', 'host_vnc')
            is_runner = host_type.startswith('runner_')
            window_bounds = detect_primary_display_bounds()
            flags = [
                f'--remote-debugging-port={debug_port}',
                f'--user-data-dir={user_data_dir}',  # Persist cache, cookies, passwords
                '--remote-debugging-address=0.0.0.0',
                '--disable-gpu',
                '--disable-crash-reporter',
                '--disable-crashpad',
                '--no-first-run',
                '--disable-breakpad',
                '--disable-dev-shm-usage',
                '--disable-gpu-compositing',
                '--disable-features=DbusService,IsolateOrigins,site-per-process',
                '--disable-background-timer-throttling',
                '--disable-renderer-backgrounding',
                '--disable-extensions',
                '--disable-session-crashed-bubble',
                '--disable-infobars',
            ]
            if is_runner:
                # Runner hosts have no X display — use Chromium headless mode
                flags.append('--headless=new')
            else:
                # Full hosts should use explicit bounds because start-maximized is unreliable with persistent profiles.
                flags.extend(build_window_flags())
                flags.append('--start-maximized')
                print(
                    '[WebKitManager] Requested window bounds: '
                    f'{window_bounds["width"]}x{window_bounds["height"]}+{window_bounds["x"]}+{window_bounds["y"]}'
                )
            return flags
        else:  # safari or other
            return [
                '--remote-debugging-port=9999',  # Safari uses different approach
                '--no-first-run'
            ]
    
    @staticmethod
    def _fix_preferences(user_data_dir: str):
        """
        Fix WebKit/Chromium preferences to prevent 'Restore pages' popup by resetting exit_type.
        This modifies the 'Preferences' file directly to set exit_type to 'Normal'.
        """
        try:
            # Try Default profile first, then root
            paths_to_check = [
                os.path.join(user_data_dir, 'Default', 'Preferences'),
                os.path.join(user_data_dir, 'Preferences')
            ]
            
            for pref_path in paths_to_check:
                if os.path.exists(pref_path):
                    try:
                        with open(pref_path, 'r', encoding='utf-8') as f:
                            content = f.read()
                        
                        # Replace exit_type "Crashed" with "Normal" to suppress restore bubble
                        if '"exit_type":"Crashed"' in content:
                            print(f'[WebKitManager] Fixing crashed exit_type in {pref_path}')
                            content = content.replace('"exit_type":"Crashed"', '"exit_type":"Normal"')
                            with open(pref_path, 'w', encoding='utf-8') as f:
                                f.write(content)
                                
                    except Exception as e:
                        print(f'[WebKitManager] Warning: Failed to fix Preferences file {pref_path}: {e}')
                        
        except Exception as e:
            print(f'[WebKitManager] Warning: Error during preferences fix: {e}')

    @staticmethod
    def is_port_in_use(port: int) -> bool:
        """Check if a port is in use."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            try:
                s.bind(('127.0.0.1', port))
                return False
            except socket.error:
                return True
    
    @classmethod
    def launch_webkit_with_debugging(cls, debug_port: int = 9223, user_data_dir: str = "./backend_host/config/webkit_user_data") -> subprocess.Popen:
        """Launch lightweight browser with remote debugging.
        
        Uses DIRECT execution approach (same as playwright_utils.py) - no bash/su wrappers.
        This matches the working manual command: docker exec ... chromium --flags
        
        IMPORTANT: Ensures all existing browser processes are killed before launching new one.
        
        Args:
            debug_port: Port for remote debugging
            user_data_dir: Browser user data directory for persistent cache/cookies/passwords
        """
        user_data_dir = resolve_user_data_dir(user_data_dir)
        print(f'[WebKitManager] Cleaning up any existing browser processes before launch...')
        
        # 1) Kill ALL browser processes (not just chromium)
        browsers_to_kill = ['chromium', 'chromium-browser', 'chrome', 'google-chrome', 'firefox', 'msedge']
        cls._kill_existing_browser_processes(browsers_to_kill)
        
        time.sleep(2)  # Give time for processes to fully terminate

        # 2) Kill any process using the debug port (critical for clean launch)
        if cls.is_port_in_use(debug_port):
            cls._kill_processes_on_port(debug_port)

            # Wait for port to be released (up to 5 seconds)
            for i in range(3):
                time.sleep(1)
                if not cls.is_port_in_use(debug_port):
                    print(f'[WebKitManager] Port {debug_port} released after {i+1}s')
                    break
        
        # 3) Final check - warn but DON'T block launch
        if cls.is_port_in_use(debug_port):
            print(f'[WebKitManager] ⚠️ Port {debug_port} still in use, proceeding anyway')
            # Don't raise - let Chrome fail if port truly blocked
        
        print(f'[WebKitManager] ✓ All existing browsers cleaned up, port {debug_port} is free')

        # 4) Prepare user data directory and clean crash files (keep cache/cookies/passwords)
        os.makedirs(user_data_dir, exist_ok=True)
        
        # Clean up crash detection files and locks
        import glob
        import shutil
        
        crash_patterns = ['Crash Reports', 'chrome_debug.log', 'Singleton*', 'Singelton*']
        for pattern in crash_patterns:
            full_pattern = os.path.join(user_data_dir, pattern)
            for crash_path in glob.glob(full_pattern):
                try:
                    if os.path.isfile(crash_path) or os.path.islink(crash_path):
                        os.remove(crash_path)
                    elif os.path.isdir(crash_path):
                        shutil.rmtree(crash_path)
                except Exception as e:
                    pass  # Ignore cleanup errors
        
        # Fix preferences to prevent "Restore pages" popup
        cls._fix_preferences(user_data_dir)
        
        print(f'[WebKitManager] Using persistent profile: {user_data_dir}')

        # 5) Find executable and get flags
        executable_path, browser_type = cls.find_webkit_executable()
        print(f'[WebKitManager] Launching {browser_type} browser: {executable_path}')

        browser_flags = cls.get_webkit_flags(debug_port, browser_type, user_data_dir)

        # 6) Build command as LIST (not string!) - same as playwright_utils.py
        cmd_line = [executable_path] + browser_flags
        
        # 7) Set environment with DISPLAY (skip for runner hosts — they use --headless=new)
        env = os.environ.copy()
        host_type = os.getenv('HOST_TYPE', 'host_vnc')
        if not cls._is_windows() and not host_type.startswith('runner_'):
            env['DISPLAY'] = ':1'
        
        # Log command for debugging
        print(f'[WebKitManager] Command: {" ".join(cmd_line)}')
        print(f'[WebKitManager] Environment DISPLAY: {env.get("DISPLAY")}')
        
        # 8) Launch directly with subprocess.Popen (NO BASH, NO SU!)
        # Use DEVNULL and start_new_session to fully detach from Flask's process group
        process = subprocess.Popen(
            cmd_line,  # LIST of arguments (not a string!)
            env=env,
            stdout=subprocess.DEVNULL,  # Use subprocess constant instead of file handle
            stderr=subprocess.DEVNULL,  # Use subprocess constant instead of file handle
            start_new_session=not cls._is_windows()
        )
        
        print(f'[WebKitManager] Chromium launched with PID: {process.pid}')

        # 9) Wait for Chrome to be ready
        cls._wait_for_webkit_ready(debug_port, max_wait=30)

        # 10) Optional diagnostics
        try:
            if cls._is_windows():
                result = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq chrome.exe'], capture_output=True, text=True)
                if 'chrome.exe' in result.stdout.lower():
                    print('[WebKitManager] Chrome processes detected')
                else:
                    edge_result = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq msedge.exe'], capture_output=True, text=True)
                    if 'msedge.exe' in edge_result.stdout.lower():
                        print('[WebKitManager] Edge processes detected')
                    else:
                        print('[WebKitManager] Browser processes: 0')
            else:
                result = subprocess.run(['pgrep', 'chromium'], capture_output=True, text=True)
                if result.stdout.strip():
                    pids = [p for p in result.stdout.strip().split('\n') if p]
                    print(f'[WebKitManager] Chromium processes: {len(pids)} ({", ".join(pids[:5])})')
                else:
                    print('[WebKitManager] Chromium processes: 0')
        except Exception as e:
            print(f'[WebKitManager] Browser process check failed: {e}')

        try:
            if cls._is_windows():
                result = subprocess.run(['netstat', '-ano'], capture_output=True, text=True)
            else:
                result = subprocess.run(['netstat', '-tuln'], capture_output=True, text=True)
            if f':{debug_port}' in result.stdout:
                print(f'[WebKitManager] ✓ Port {debug_port} LISTENING')
            else:
                print(f'[WebKitManager] ✗ Port {debug_port} NOT listening')
        except Exception as e:
            print(f'[WebKitManager] netstat check failed: {e}')

        return process
    
    @staticmethod
    def _wait_for_webkit_ready(debug_port: int, max_wait: int = WEBKIT_LAUNCH_READY_TIMEOUT_SECONDS):
        """Wait for WebKit to be ready on the debug port."""
        print(f'[WebKitManager] Waiting for WebKit on port {debug_port}...')
        
        start_time = time.time()
        while time.time() - start_time < max_wait:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(1)
                s.connect(('127.0.0.1', debug_port))
                s.close()
                elapsed = time.time() - start_time
                print(f'[WebKitManager] WebKit ready after {elapsed:.2f}s')
                time.sleep(1)  # Brief pause for full initialization
                return
            except (socket.timeout, socket.error):
                time.sleep(1)
        
        print(f'[WebKitManager] WARNING: Timeout waiting for WebKit port {debug_port}')


class WebKitConnection:
    """Manages Playwright connections to lightweight browsers via debug protocol."""
    
    @staticmethod
    async def connect_to_webkit(cdp_url: str = 'http://127.0.0.1:9223') -> Tuple[Any, Any, Any, Any]:
        """Connect to lightweight browser via debug protocol and return playwright, browser, context, page."""
        from playwright.async_api import async_playwright
        
        try:
            print(f'[WebKitConnection] Connecting to lightweight browser at {cdp_url}')
            playwright = await async_playwright().start()
            
            # Since we're actually using Chromium/Chrome with lightweight flags, use chromium engine
            # This provides the same lightweight benefits but with proper CDP support
            browser = await playwright.chromium.connect_over_cdp(cdp_url)
            print(f'[WebKitConnection] Connected to lightweight browser successfully')
            
            # Get or create context and page
            if len(browser.contexts) == 0:
                context = await browser.new_context()
                page = await context.new_page()
                print(f'[WebKitConnection] Created new lightweight browser context')
            else:
                context = browser.contexts[0]
                if len(context.pages) == 0:
                    page = await context.new_page()
                else:
                    page = context.pages[0]
                print(f'[WebKitConnection] Using existing lightweight browser context')
            
            return playwright, browser, context, page
            
        except Exception as e:
            print(f'[WebKitConnection] Connection failed: {e}')
            raise Exception(f"Lightweight browser connection failed: {str(e)}")


class WebKitUtils:
    """Lightweight WebKit utility class - minimal resource usage alternative to Chrome."""
    
    def __init__(self, debug_port: int = 9223, user_data_dir: str = "./backend_host/config/webkit_user_data"):
        """Initialize WebKit utils with minimal configuration.
        
        Args:
            debug_port: Port for remote debugging
            user_data_dir: Browser user data directory for persistent cache/cookies/passwords
        """
        self.debug_port = debug_port
        self.user_data_dir = resolve_user_data_dir(user_data_dir)
        self.webkit_manager = WebKitManager()
        self.connection = WebKitConnection()
        print(f'[WebKitUtils] Initialized lightweight WebKit browser on port {debug_port} with persistent data: {user_data_dir}')
    
    def launch_webkit(self) -> subprocess.Popen:
        """Launch lightweight browser with remote debugging and persistent data."""
        return self.webkit_manager.launch_webkit_with_debugging(self.debug_port, self.user_data_dir)
    
    def launch_chrome(self) -> subprocess.Popen:
        """Compatibility method - launches lightweight browser (same as launch_webkit)."""
        return self.launch_webkit()
    
    async def connect_to_webkit(self, target_url: str = None):
        """Connect to lightweight browser via debug protocol."""
        cdp_url = f'http://127.0.0.1:{self.debug_port}'  # Use IPv4 explicitly to avoid IPv6 issues
        return await self.connection.connect_to_webkit(cdp_url)
    
    async def connect_to_chrome(self, target_url: str = None):
        """Compatibility method - connects to lightweight browser (same as connect_to_webkit)."""
        return await self.connect_to_webkit(target_url)
    
    def normalize_url(self, url: str) -> str:
        """Normalize URL by adding protocol if missing (compatibility method)."""
        if not url:
            return url
        
        url = url.strip()
        if len(url) >= 2 and url[0] == url[-1] and url[0] in ('"', "'"):
            url = url[1:-1].strip()
        
        # If URL already has a protocol, return as-is
        if url.startswith(('http://', 'https://', 'ftp://', 'file://')):
            return url
        
        # Special cases for local URLs
        if url.startswith(('localhost', '127.0.0.1', '0.0.0.0')) or ':' in url.split('.')[0]:
            return f'http://{url}'
        
        # For all other URLs, default to https
        return f'https://{url}'
    
    def kill_chrome(self, chrome_process=None):
        """Compatibility method - terminates any running lightweight browser process."""
        try:
            # If specific process provided, kill it first
            if chrome_process and chrome_process.poll() is None:
                try:
                    chrome_process.terminate()
                    chrome_process.wait(timeout=3)
                    print(f'[WebKitUtils] Terminated process {chrome_process.pid}')
                except Exception as e:
                    print(f'[WebKitUtils] Error terminating process: {e}')
            
            # Kill any process using the debug port
            if self.webkit_manager.is_port_in_use(self.debug_port):
                print(f'[WebKitUtils] Killing processes on port {self.debug_port}...')
                self.webkit_manager._kill_processes_on_port(self.debug_port)
                time.sleep(1)
        except Exception as e:
            print(f'[WebKitUtils] Error killing browser: {e}')

    def get_launch_diagnostics(self) -> Dict[str, Any]:
        return self.webkit_manager.get_launch_diagnostics(self.debug_port, self.user_data_dir)
    
    @staticmethod
    def run_async(coro):
        """
        Run async coroutine in sync context with proper event loop handling.
        
        Key scenarios:
        1. Main thread with no loop: create one with asyncio.run()
        2. Main thread with stopped loop: use run_until_complete()
        3. Background thread (like async execution): create new loop with asyncio.run()
        4. Already in async context (loop running): ERROR - should use await instead
        """
        import threading
        
        # Check if we're in the main thread
        is_main_thread = threading.current_thread() is threading.main_thread()
        
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                raise RuntimeError("Cannot run async code in already-running event loop. Use await instead.")
            
            # Loop exists but not running
            if is_main_thread:
                return loop.run_until_complete(coro)
            else:
                # In background thread, create new loop
                return asyncio.run(coro)
        except RuntimeError:
            return asyncio.run(coro)


# Convenience functions
def create_webkit_utils(debug_port: int = 9223, user_data_dir: str = "./backend_host/config/webkit_user_data") -> WebKitUtils:
    """Create a lightweight WebKit utils instance."""
    return WebKitUtils(debug_port=debug_port, user_data_dir=user_data_dir)


def launch_webkit_for_debugging(debug_port: int = 9223, user_data_dir: str = "./backend_host/config/webkit_user_data") -> subprocess.Popen:
    """Quick function to launch WebKit with remote debugging and persistent data."""
    return WebKitManager.launch_webkit_with_debugging(debug_port, user_data_dir)
