"""
Lightweight Browser Manager for Playwright

Supports Firefox and WebKit browsers with remote debugging capabilities.
These are lighter alternatives to Chrome/Chromium for testing.
"""

import os
import time
import subprocess
import socket
import asyncio
from typing import Dict, Any, Tuple, Optional


def resolve_user_data_dir(user_data_dir: str) -> str:
    """Resolve user_data_dir to absolute path from project root."""
    if os.path.isabs(user_data_dir):
        return user_data_dir
    
    # Simple: go up 3 levels from /shared/lib/utils to project root
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
    return os.path.abspath(os.path.join(project_root, user_data_dir.lstrip('./')))


class FirefoxManager:
    """Manages Firefox process lifecycle for remote debugging."""
    
    @staticmethod
    def find_firefox_executable() -> str:
        """Find Firefox executable on Linux system."""
        possible_paths = [
            '/usr/bin/firefox',
            '/usr/bin/firefox-esr', 
            '/snap/bin/firefox',
            '/opt/firefox/firefox',
            '/usr/local/bin/firefox'
        ]
        for path in possible_paths:
            if os.path.exists(path):
                return path
        raise ValueError('No Firefox executable found in common Linux paths')
    
    @staticmethod
    def get_firefox_flags(debug_port: int = 9223, profile_dir: str = "./backend_host/config/firefox_profile") -> list:
        """
        Get Firefox launch flags for remote debugging.
        
        Args:
            debug_port: Debug port for remote debugging
            profile_dir: Firefox profile directory
        """
        return [
            '--headless',  # Run headless for lighter resource usage
            f'--remote-debugging-port={debug_port}',
            f'--profile={profile_dir}',
            '--no-first-run',
            '--disable-default-browser-check',
            '--disable-background-updates',
            '--disable-background-networking',
            '--disable-sync',
            '--disable-translate',
            '--disable-extensions',
            '--disable-component-update',
            '--disable-background-timer-throttling',
            '--disable-client-side-phishing-detection',
            '--disable-default-apps',
            '--disable-hang-monitor',
            '--disable-prompt-on-repost',
            '--disable-domain-reliability',
            '--no-crash-upload',
            '--disable-features=TranslateUI,BlinkGenPropertyTrees'
        ]
    
    @classmethod
    async def launch_firefox_with_remote_debugging(cls, debug_port: int = 9223, 
                                           profile_dir: str = "./backend_host/config/firefox_profile") -> subprocess.Popen:
        """
        Launch Firefox with remote debugging.
        
        Args:
            debug_port: Port for remote debugging
            profile_dir: Firefox profile directory
        """
        # Kill any existing Firefox processes on this port
        cls._kill_processes_on_port(debug_port)
        
        # Find Firefox executable
        executable_path = cls.find_firefox_executable()
        print(f'[FirefoxManager] Launching Firefox with remote debugging: {executable_path}')
        
        # Prepare profile directory
        resolved_profile_dir = resolve_user_data_dir(profile_dir)
        os.makedirs(resolved_profile_dir, exist_ok=True)
        print(f'[FirefoxManager] Using profile: {resolved_profile_dir}')
        
        firefox_flags = cls.get_firefox_flags(debug_port, resolved_profile_dir)
        
        # Log flags
        print(f'[FirefoxManager] Firefox flags:')
        for i, flag in enumerate(firefox_flags, 1):
            print(f'[FirefoxManager]   {i}. {flag}')
        
        # Construct Firefox command
        firefox_cmd = [executable_path] + firefox_flags
        
        # Set environment
        env = os.environ.copy()
        env["DISPLAY"] = os.environ.get("DISPLAY", ":1")
        env["MOZ_HEADLESS"] = "1"  # Ensure headless mode
        
        # Launch Firefox
        process = subprocess.Popen(firefox_cmd, env=env)
        print(f'[FirefoxManager] Firefox launched with PID: {process.pid}')
        
        # Wait for Firefox to be ready
        await cls._wait_for_browser_ready(debug_port, "Firefox")
        
        return process
    
    @staticmethod
    def _kill_processes_on_port(port: int):
        """Kill processes using the specified port."""
        if FirefoxManager._is_port_in_use(port):
            print(f'[FirefoxManager] Port {port} is in use. Killing processes...')
            try:
                result = subprocess.run(['lsof', '-ti', f':{port}'], 
                                      capture_output=True, text=True, timeout=5)
                if result.returncode == 0 and result.stdout.strip():
                    pids = result.stdout.strip().split('\n')
                    for pid in pids:
                        if pid.strip():
                            subprocess.run(['kill', '-9', pid.strip()], timeout=3)
                            print(f'[FirefoxManager] Killed process {pid.strip()}')
            except Exception as e:
                print(f'[FirefoxManager] Error killing processes: {e}')
            time.sleep(1)
    
    @staticmethod
    def _is_port_in_use(port: int) -> bool:
        """Check if a port is in use."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            try:
                s.bind(('127.0.0.1', port))
                return False
            except socket.error:
                return True
    
    @staticmethod
    async def _wait_for_browser_ready(debug_port: int, browser_name: str, max_wait: int = 30):
        """Wait for browser to be ready on the debug port."""
        print(f'[{browser_name}Manager] Waiting up to {max_wait} seconds for {browser_name} on port {debug_port}...')
        
        start_time = time.time()
        port_open = False
        
        while time.time() - start_time < max_wait:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(1)
                s.connect(('127.0.0.1', debug_port))
                s.close()
                port_open = True
                elapsed = time.time() - start_time
                print(f'[{browser_name}Manager] {browser_name} ready! Port {debug_port} open after {elapsed:.2f}s')
                time.sleep(2)  # Ensure browser is fully initialized
                break
            except (socket.timeout, socket.error):
                time.sleep(1)
        
        if not port_open:
            print(f'[{browser_name}Manager] WARNING: Timed out waiting for {browser_name} port {debug_port}')


class WebKitManager:
    """Manages WebKit process lifecycle for remote debugging (lightest option)."""
    
    @staticmethod
    def find_webkit_executable() -> str:
        """Find WebKit executable (usually through playwright)."""
        # WebKit is typically installed via Playwright
        import subprocess
        try:
            # Try to find playwright webkit
            result = subprocess.run(['which', 'playwright'], capture_output=True, text=True)
            if result.returncode == 0:
                return 'playwright'
            
            # Alternative: check for system webkit
            webkit_paths = [
                '/usr/bin/webkit2gtk-4.0',
                '/usr/bin/MiniBrowser'
            ]
            for path in webkit_paths:
                if os.path.exists(path):
                    return path
                    
        except Exception:
            pass
            
        raise ValueError('No WebKit executable found. Install with: playwright install webkit')
    
    @classmethod
    async def launch_webkit_with_remote_debugging(cls, debug_port: int = 9224) -> subprocess.Popen:
        """
        Launch WebKit with remote debugging (lightest browser option).
        
        Args:
            debug_port: Port for remote debugging
        """
        # Kill any existing processes on this port
        FirefoxManager._kill_processes_on_port(debug_port)
        
        print(f'[WebKitManager] Launching WebKit with remote debugging on port {debug_port}')
        
        # WebKit launch via Playwright (lightest option)
        webkit_cmd = [
            'playwright', 'open', 
            '--browser=webkit',
            f'--remote-debugging-port={debug_port}',
            '--headless',
            'about:blank'
        ]
        
        # Set environment
        env = os.environ.copy()
        env["DISPLAY"] = os.environ.get("DISPLAY", ":1")
        
        # Launch WebKit
        process = subprocess.Popen(webkit_cmd, env=env)
        print(f'[WebKitManager] WebKit launched with PID: {process.pid}')
        
        # Wait for WebKit to be ready
        await FirefoxManager._wait_for_browser_ready(debug_port, "WebKit")
        
        return process


class LightweightPlaywrightConnection:
    """Manages Playwright connections to lightweight browsers via CDP/remote debugging."""
    
    @staticmethod
    async def connect_to_firefox(cdp_url: str = 'http://localhost:9223') -> Tuple[Any, Any, Any, Any]:
        """Connect to Firefox via remote debugging."""
        from playwright.async_api import async_playwright
        
        try:
            print(f'[LightweightConnection] Connecting to Firefox at {cdp_url}')
            playwright = await async_playwright().start()
            
            # Connect to Firefox via CDP
            browser = await playwright.firefox.connect_over_cdp(cdp_url)
            print(f'[LightweightConnection] Successfully connected to Firefox')
            
            # Create context and page
            if len(browser.contexts) == 0:
                context = await browser.new_context()
                page = await context.new_page()
                print(f'[LightweightConnection] Created new Firefox context')
            else:
                context = browser.contexts[0]
                page = context.pages[0] if context.pages else await context.new_page()
                print(f'[LightweightConnection] Using existing Firefox context')
            
            return playwright, browser, context, page
            
        except Exception as e:
            print(f'[LightweightConnection] Firefox connection failed: {e}')
            raise Exception(f"Firefox CDP connection failed: {str(e)}")
    
    @staticmethod
    async def connect_to_webkit(cdp_url: str = 'http://localhost:9224') -> Tuple[Any, Any, Any, Any]:
        """Connect to WebKit via remote debugging."""
        from playwright.async_api import async_playwright
        
        try:
            print(f'[LightweightConnection] Connecting to WebKit at {cdp_url}')
            playwright = await async_playwright().start()
            
            # Connect to WebKit via CDP
            browser = await playwright.webkit.connect_over_cdp(cdp_url)
            print(f'[LightweightConnection] Successfully connected to WebKit')
            
            # Create context and page
            if len(browser.contexts) == 0:
                context = await browser.new_context()
                page = await context.new_page()
                print(f'[LightweightConnection] Created new WebKit context')
            else:
                context = browser.contexts[0]
                page = context.pages[0] if context.pages else await context.new_page()
                print(f'[LightweightConnection] Using existing WebKit context')
            
            return playwright, browser, context, page
            
        except Exception as e:
            print(f'[LightweightConnection] WebKit connection failed: {e}')
            raise Exception(f"WebKit CDP connection failed: {str(e)}")
    
    @staticmethod
    async def cleanup_connection(playwright, browser):
        """Clean up connection."""
        if browser:
            await browser.close()
        if playwright:
            await playwright.stop()


class LightweightBrowserManager:
    """Main manager for lightweight browsers (Firefox and WebKit)."""
    
    def __init__(self, browser_type: str = "webkit", debug_port: Optional[int] = None):
        """
        Initialize lightweight browser manager.
        
        Args:
            browser_type: "firefox" or "webkit" (webkit is lightest)
            debug_port: Debug port (auto-assigned if None)
        """
        self.browser_type = browser_type.lower()
        
        if self.browser_type == "firefox":
            self.debug_port = debug_port or 9223
            self.manager = FirefoxManager()
        elif self.browser_type == "webkit":
            self.debug_port = debug_port or 9224
            self.manager = WebKitManager()
        else:
            raise ValueError("browser_type must be 'firefox' or 'webkit'")
        
        self.connection = LightweightPlaywrightConnection()
        self.process = None
        
        print(f'[LightweightBrowserManager] Initialized for {browser_type} on port {self.debug_port}')
    
    async def launch_browser(self) -> subprocess.Popen:
        """Launch the lightweight browser with remote debugging."""
        if self.browser_type == "firefox":
            self.process = await self.manager.launch_firefox_with_remote_debugging(self.debug_port)
        elif self.browser_type == "webkit":
            self.process = await self.manager.launch_webkit_with_remote_debugging(self.debug_port)
        
        return self.process
    
    async def connect_to_browser(self):
        """Connect to the launched browser."""
        cdp_url = f'http://localhost:{self.debug_port}'
        
        if self.browser_type == "firefox":
            return await self.connection.connect_to_firefox(cdp_url)
        elif self.browser_type == "webkit":
            return await self.connection.connect_to_webkit(cdp_url)
    
    def kill_browser(self):
        """Kill the browser process."""
        if self.process:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
                print(f'[LightweightBrowserManager] {self.browser_type.title()} process terminated')
            except subprocess.TimeoutExpired:
                print(f'[LightweightBrowserManager] Force killing {self.browser_type} process...')
                self.process.kill()
                self.process.wait()


# Convenience functions
def create_lightweight_firefox_manager(debug_port: int = 9223) -> LightweightBrowserManager:
    """Create a Firefox manager (moderate resource usage)."""
    return LightweightBrowserManager("firefox", debug_port)


def create_lightweight_webkit_manager(debug_port: int = 9224) -> LightweightBrowserManager:
    """Create a WebKit manager (lightest resource usage)."""
    return LightweightBrowserManager("webkit", debug_port)


# Async execution helper
class AsyncExecutor:
    """Handles async execution in sync contexts."""
    
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
