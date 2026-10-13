"""
Playwright Utilities

Chrome process management for Playwright web automation using SYNC API.
Includes cookie management for automatic consent cookie injection.
Extracted from PlaywrightWebController to improve maintainability.

Uses Playwright sync_api for simplicity and thread safety (no async complexity).
"""

import os
import signal
import time
import subprocess
import socket
from typing import Dict, Any, Optional, Tuple

# SIGKILL does not exist on Windows; the host only ever runs Chrome on Linux, but the
# module must still import (unit tests, the Windows host build).
_SIGKILL = getattr(signal, 'SIGKILL', 9)

from shared.src.lib.utils.browser_window_utils import build_window_flags, detect_primary_display_bounds

# Import the cookie utils from shared library
try:
    from shared.src.lib.utils.cookie_utils import CookieManager, auto_accept_cookies
except ImportError:
    print("Warning: Cookie utilities not available. Cookie management will be limited.")
    # Create dummy classes to prevent import errors
    class CookieManager:
        def __init__(self, *args, **kwargs): pass
        def auto_accept_cookies(self, *args, **kwargs): return False
    def auto_accept_cookies(*args, **kwargs): return False


PLAYWRIGHT_STOP_TIMEOUT_SECONDS = 5.0

# Launch readiness. A launched Chromium is ready for a CDP attach once its debug endpoint lists
# a page target (the startup tab). That used to be three fixed 2 s sleeps after the port
# opened (launcher, connect(), connect_browser()) on top of a port poll every 1 s: ~7 s of an
# ~8.5 s start measured on host-clone-3 (2026-09-29). Now it is polled every CHROME_READY_POLL_S
# and gives up after CHROME_PAGE_READY_MAX_WAIT_S, the sum of those sleeps, and carries on as
# the sleeps did, so a browser that never lists its tab is never waited on for longer than before.
CHROME_READY_POLL_S = 0.1
CHROME_PAGE_READY_MAX_WAIT_S = 6.0


async def stop_playwright(playwright, timeout: float = PLAYWRIGHT_STOP_TIMEOUT_SECONDS) -> None:
    """Stop a Playwright instance so its Node driver process exits (BUG-0191).

    Every `async_playwright().start()` spawns one driver (`ps` shows it as `MainThread`, the
    name Node gives its main thread) that lives until `stop()`. One that is dropped without
    stopping lives as long as vpt-host: about 30 MB each, ~20 an hour, 8 GB in half a day.
    When `stop()` does not return in time, the driver is killed through its pipe transport.
    """
    if playwright is None:
        return
    import asyncio
    try:
        await asyncio.wait_for(playwright.stop(), timeout=timeout)
        return
    except Exception as e:
        print(f'[PlaywrightConnection] Playwright stop did not complete ({type(e).__name__}: {e}); killing its driver')
    try:
        proc = playwright._impl_obj._connection._transport._proc
        if proc.returncode is None:
            proc.kill()
    except Exception as e:
        print(f'[PlaywrightConnection] Could not kill the Playwright driver: {type(e).__name__}: {e}')


def resolve_user_data_dir(user_data_dir: str) -> str:
    """Resolve user_data_dir to absolute path from project root."""
    if os.path.isabs(user_data_dir):
        return user_data_dir
    
    # Simple: go up 3 levels from /shared/lib/utils to project root
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
    return os.path.abspath(os.path.join(project_root, user_data_dir.lstrip('./')))


class ChromeManager:
    """Manages Chrome process lifecycle for remote debugging."""
    
    # ------------------------------------------------------------------
    # Shutdown. Three layers, each one a hard guarantee for the one before:
    #   1. the Popen we launched (its whole process group: Chrome is launched
    #      as a session leader, so the zygote/renderers/gpu helpers go with it),
    #   2. whatever still LISTENS on the debug port (a browser we only attached
    #      to, or one left by a run that died) - never a CDP client (BUG-0114),
    #   3. wait for the port to actually be free.
    # The graceful CDP `Browser.close` is sent by the controller over its
    # Playwright connection before this runs; there is no HTTP endpoint for it.
    # ------------------------------------------------------------------

    @staticmethod
    def _pgid(pid: int) -> Optional[int]:
        try:
            return os.getpgid(pid)
        except Exception:
            return None

    @staticmethod
    def _signal(pid: int, sig: int, whole_group: bool) -> None:
        if whole_group:
            os.killpg(pid, sig)
        else:
            os.kill(pid, sig)

    @classmethod
    def _terminate_pid(cls, pid: int, timeout: float, is_alive) -> bool:
        """SIGTERM then SIGKILL `pid`. The whole process group when `pid` leads one
        (our own launches always do); a process that lives in someone else's group -
        typically the vpt-host service's - is signalled alone so the kill can never
        reach that service. Returns True when `is_alive()` turns False in time."""
        whole_group = cls._pgid(pid) == pid
        what = f'process group {pid}' if whole_group else f'process {pid}'
        for sig, label in ((signal.SIGTERM, 'SIGTERM'), (_SIGKILL, 'SIGKILL')):
            try:
                cls._signal(pid, sig, whole_group)
            except ProcessLookupError:
                return True
            except Exception as e:
                print(f'[ChromeManager] {label} to {what} failed: {type(e).__name__}: {e}')
                return not is_alive()
            deadline = time.time() + timeout
            while time.time() < deadline:
                if not is_alive():
                    print(f'[ChromeManager] {what} exited after {label}')
                    return True
                time.sleep(0.1)
            print(f'[ChromeManager] {what} still alive {timeout:.0f}s after {label}')
        return not is_alive()

    @staticmethod
    def listener_pid(debug_port: int) -> Optional[int]:
        """PID of the process LISTENING on the debug port, or None. `-sTCP:LISTEN` is
        what keeps this from ever matching a Playwright driver connected to it."""
        try:
            result = subprocess.run(['lsof', '-t', '-sTCP:LISTEN', '-i', f':{debug_port}'],
                                    capture_output=True, text=True, timeout=5)
        except Exception as e:
            print(f'[ChromeManager] lsof on port {debug_port} failed: {type(e).__name__}: {e}')
            return None
        for line in result.stdout.split():
            if line.strip().isdigit():
                return int(line.strip())
        return None

    @classmethod
    def shutdown_chrome(cls, debug_port: int = 9222, chrome_process=None, timeout: float = 5.0) -> bool:
        """Take the debug port back. Terminates the browser this process launched (if any),
        then whatever is still listening on the port, and returns True once nothing is."""
        if chrome_process is not None and chrome_process.poll() is None:
            print(f'[ChromeManager] Terminating launched Chrome (PID {chrome_process.pid})')
            cls._terminate_pid(chrome_process.pid, timeout, lambda: chrome_process.poll() is None)
        elif chrome_process is not None:
            print(f'[ChromeManager] Launched Chrome (PID {chrome_process.pid}) already exited (code {chrome_process.returncode})')

        pid = cls.listener_pid(debug_port)
        if pid is not None:
            print(f'[ChromeManager] Port {debug_port} still has a listener (PID {pid}) - terminating it')
            cls._terminate_pid(pid, timeout, lambda: cls.listener_pid(debug_port) == pid)

        # "Free" means no listener. A bind() probe would also see the TIME_WAIT sockets
        # the dead browser's CDP connections leave on the port for a minute.
        deadline = time.time() + 3
        while cls.listener_pid(debug_port) is not None:
            if time.time() > deadline:
                print(f'[ChromeManager] Port {debug_port} STILL has a listener after shutdown')
                return False
            time.sleep(0.2)
        print(f'[ChromeManager] Port {debug_port} is free')
        return True

    @staticmethod
    def _fix_preferences(user_data_dir: str):
        """
        Fix Chrome preferences to prevent 'Restore pages' popup by resetting exit_type.
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
                            print(f'[ChromeManager] Fixing crashed exit_type in {pref_path}')
                            content = content.replace('"exit_type":"Crashed"', '"exit_type":"Normal"')
                            with open(pref_path, 'w', encoding='utf-8') as f:
                                f.write(content)
                                
                    except Exception as e:
                        print(f'[ChromeManager] Warning: Failed to fix Preferences file {pref_path}: {e}')
                        
        except Exception as e:
            print(f'[ChromeManager] Warning: Error during preferences fix: {e}')

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
    
    @staticmethod
    def cdp_healthy(debug_port: int = 9222, timeout: float = 2.0) -> bool:
        """True when a live Chrome DevTools endpoint answers on the port."""
        try:
            import requests
            return requests.get(f'http://127.0.0.1:{debug_port}/json/version', timeout=timeout).status_code == 200
        except Exception:
            return False

    @staticmethod
    def port_listening(debug_port: int = 9222, timeout: float = 0.25) -> bool:
        """True when something accepts TCP connections on 127.0.0.1:<port>.

        A connect, not a bind (is_port_in_use binds, i.e. briefly takes the port a browser is
        about to listen on). Refused answers at once, so a free port costs ~1 ms."""
        try:
            with socket.create_connection(('127.0.0.1', debug_port), timeout=timeout):
                return True
        except OSError:
            return False

    @staticmethod
    def cdp_page_ready(debug_port: int = 9222, timeout: float = 1.0) -> bool:
        """True when the DevTools endpoint lists at least one page target (the startup tab).

        /json/version answers as soon as the port opens; the tab a CDP attach adopts as the
        persistent page comes a little later. Attaching before it exists makes Playwright open
        a second tab, which is not the one on screen."""
        try:
            import requests
            response = requests.get(f'http://127.0.0.1:{debug_port}/json/list', timeout=timeout)
            if response.status_code != 200:
                return False
            return any(isinstance(t, dict) and t.get('type') == 'page' for t in response.json())
        except Exception:
            return False

    @classmethod
    def wait_for_cdp_page(cls, debug_port: int = 9222, max_wait: float = CHROME_PAGE_READY_MAX_WAIT_S,
                          interval: float = CHROME_READY_POLL_S) -> Tuple[bool, int]:
        """Poll cdp_page_ready until it holds or max_wait passes. Returns (ready, polls)."""
        deadline = time.monotonic() + max_wait
        polls = 0
        while True:
            polls += 1
            if cls.cdp_page_ready(debug_port):
                return True, polls
            if time.monotonic() >= deadline:
                return False, polls
            time.sleep(interval)
    
    @staticmethod
    def find_chrome_executable() -> str:
        """Find Chrome executable on Linux system."""
        possible_paths = [
            '/usr/bin/chromium',           # Debian/Ubuntu chromium package
            '/usr/bin/chromium-browser',   # Alternative chromium name
            '/usr/bin/google-chrome',      # Google Chrome
            '/usr/bin/google-chrome-stable'
        ]
        for path in possible_paths:
            if os.path.exists(path):
                return path
        raise ValueError('No Chrome executable found in common Linux paths')
    
    @staticmethod
    def get_chrome_flags(debug_port: int = 9222, user_data_dir: str = "./backend_host/config/user_data") -> list:
        """
        Get Chrome launch flags for remote debugging with persistent data.
        
        Args:
            debug_port: Debug port for remote debugging
            user_data_dir: Chrome user data directory (relative to project root)
        """
        window_bounds = detect_primary_display_bounds()
        flags = [
            f'--remote-debugging-port={debug_port}',
            f'--user-data-dir={user_data_dir}',
            '--no-first-run',
            '--no-default-browser-check',
            '--disable-crashpad',
            # ONE --disable-features flag only: Chrome keeps just the last occurrence, so a second
            # one (password features, below) silently re-enabled Translate — the FR→EN bubble.
            '--disable-features=Translate,TranslateUI,InfiniteSessionRestore,TabRestore,MediaRouter,'
            'PasswordCheck,PasswordLeakDetection,AutofillServerCommunication',
            '--disable-extensions',
            '--disable-session-crashed-bubble',  # Disable restore session popup
            '--disable-infobars',  # Disable info bars including restore prompts
            '--disable-background-timer-throttling',  # Prevent background issues
            '--disable-backgrounding-occluded-windows',  # Prevent window management issues
            '--disable-renderer-backgrounding',  # Keep renderer active
            '--disable-ipc-flooding-protection',  # Prevent IPC issues
            '--hide-crashed-bubble',  # Hide crash bubbles
            '--disable-component-extensions-with-background-pages',  # Disable background extensions
            '--disable-popup-blocking',  # Disable popup blocking (for automation)
            '--disable-prompt-on-repost',  # Disable repost confirmation prompts
            '--disable-hang-monitor',  # Disable hang detection
            '--disable-client-side-phishing-detection',  # Disable phishing detection popups
            '--disable-default-apps',  # Disable default app prompts
            '--password-store=basic',  # Don't show password save popup
            '--disable-save-password-bubble',  # Suppress "Save password?" dialog
            '--enable-features=PasswordImport',  # Prevent password manager popups
            '--disable-autofill',  # Disable autofill/autocomplete suggestions in all fields including omnibox
            '--disable-search-engine-choice-screen',  # Skip search engine choice
            '--omnibox-autocomplete-off',  # Disable omnibox autocomplete suggestions
            '--disable-domain-reliability',  # Disable domain reliability reporting
            '--disable-background-networking',  # Disable background networking
            '--metrics-recording-only',  # Only record metrics, don't send
            '--no-crash-upload',  # Don't upload crash reports
            '--hide-crash-restore-bubble',  # Hide crash restore bubble
            '--disable-dev-shm-usage',  # Overcome limited resource problems on Pi
            '--memory-pressure-off',  # Disable memory pressure system
            '--max_old_space_size=512',  # Limit V8 heap size to 512MB
            '--enable-unsafe-swiftshader',  # Enable unsafe SwiftShader for GPU acceleration
            '--disable-gpu',  # Disable GPU acceleration to prevent GPU-related crashes
            '--force-fieldtrials=*BackgroundTracing/default/',  # Disable background tracing
            '--disable-crash-reporter',  # Disable crash reporter
            '--disable-logging',  # Disable logging that tracks crashes
            '--silent-debugger-extension-api',  # Silence debugger extension API
        ]
        flags.extend(build_window_flags())
        flags.append('--start-maximized')
        print(
            '[ChromeManager] Requested window bounds: '
            f'{window_bounds["width"]}x{window_bounds["height"]}+{window_bounds["x"]}+{window_bounds["y"]}'
        )
        return flags
    
    @classmethod
    def launch_chrome_with_remote_debugging(cls, debug_port: int = 9222, user_data_dir: str = "./backend_host/config/user_data", 
                                          use_cgroup: bool = True, cpu_quota: str = "100%", memory_max: str = "4G", memory_high: str = "3G") -> subprocess.Popen:
        """
        Launch Chrome with remote debugging and persistent data.
        
        Args:
            debug_port: Port for remote debugging
            user_data_dir: Chrome user data directory (relative to project root)
            use_cgroup: Whether to use systemd-run with cgroup v2 resource limits
            cpu_quota: CPU quota limit (e.g., "50%" for 50% of one core)
            memory_max: Maximum memory limit (e.g., "1G", "512M")
            memory_high: Memory high limit for early pressure (e.g., "768M")
        """
        # Whatever still listens on the debug port is an orphan (the device lock guarantees
        # no other run is driving it): take the port, listener only, never a CDP client (BUG-0114).
        if cls.listener_pid(debug_port) is not None:
            print(f'[ChromeManager] Port {debug_port} has a listener - taking it over')
            from shared.src.lib.utils.phase_timing import t0 as _phase_t0, log_phase as _log_phase
            _t = _phase_t0()
            cls.shutdown_chrome(debug_port)
            _log_phase('chrome.shutdown_orphan_listener', _t)

        # Find Chrome executable
        executable_path = cls.find_chrome_executable()
        print(f'[ChromeManager] Launching Chrome with remote debugging: {executable_path}')
        
        # Prepare Chrome flags and user data directory (path should already be resolved)
        os.makedirs(user_data_dir, exist_ok=True)
        
        # Clean up crash detection files and locks
        import glob
        import shutil
        
        crash_patterns = ['Crash Reports', 'chrome_debug.log', 'Singleton*', 'Singelton*']  # Handle both spellings just in case
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
        
        print(f'[ChromeManager] Using persistent profile: {user_data_dir}')
        
        chrome_flags = cls.get_chrome_flags(debug_port, user_data_dir)
        
        # Log all flags being applied
        print(f'[ChromeManager] Chrome flags being applied:')
        for i, flag in enumerate(chrome_flags, 1):
            print(f'[ChromeManager]   {i}. {flag}')
        
        # Construct Chrome command
        chrome_cmd = [executable_path] + chrome_flags
        
        # Build final command with optional cgroup v2 support
        if use_cgroup:
            print(f'[ChromeManager] Using cgroup v2 SOFT resource limits: CPUWeight=100, MemoryHigh={memory_high}, MemorySwapMax={memory_max}')
            
            # Build systemd-run command with cgroup v2 SOFT resource limits (throttle, don't kill)
            cmd_line = [
                'systemd-run',
                '--scope',
                '--user',
                f'-p=CPUWeight=100',          # Relative CPU priority (default weight)
                f'-p=MemoryHigh={memory_high}',  # Soft memory limit - throttles but doesn't kill
                f'-p=MemorySwapMax={memory_max}', # Allow swap usage up to memory_max
                f'-p=OOMScoreAdjust=500',     # Make less likely to be killed by OOM killer
                '--property=KillMode=mixed',  # Allow proper cleanup
                '--property=Type=forking',    # Handle Chrome's forking behavior
                '--slice=user-chrome.slice'   # Put in dedicated slice for better management
            ] + chrome_cmd
            
            print(f'[ChromeManager] Full systemd-run command: {" ".join(cmd_line)}')
        else:
            cmd_line = chrome_cmd
            print(f'[ChromeManager] Full Chrome command: {" ".join(cmd_line)}')
        
        # Set environment
        env = os.environ.copy()
        env["DISPLAY"] = os.environ.get("DISPLAY", ":1")
        
        # Launch Chrome (with or without cgroup limits) - capture stderr to detect errors.
        # start_new_session makes Chrome a session/group leader, so shutdown_chrome can
        # killpg() the browser together with its zygote/renderer/gpu helpers.
        process = subprocess.Popen(cmd_line, env=env, stderr=subprocess.PIPE, stdout=subprocess.PIPE,
                                   start_new_session=(os.name != 'nt'))
        print(f'[ChromeManager] Chrome launched with PID: {process.pid}')
        
        # Add process monitoring for debugging
        print(f'[ChromeManager] Chrome command line: {" ".join(cmd_line)}')
        print(f'[ChromeManager] Environment DISPLAY: {env.get("DISPLAY", "not set")}')
        
        # Wait for Chrome to be ready - pass process to check for early failures
        cls._wait_for_chrome_ready(debug_port, process)
        
        return process
    
    @staticmethod
    def _wait_for_chrome_ready(debug_port: int, process: subprocess.Popen = None, max_wait: int = 30):
        """
        Wait for Chrome to be ready on the debug port.
        
        Args:
            debug_port: Port to check
            process: Chrome process to monitor for early failures
            max_wait: Maximum seconds to wait
            
        Raises:
            RuntimeError: If Chrome process fails to start
        """
        print(f'[ChromeManager] Waiting up to {max_wait} seconds for Chrome on port {debug_port}...')
        from shared.src.lib.utils.phase_timing import t0 as _phase_t0, log_phase as _log_phase

        start_time = time.time()
        _t_port = _phase_t0()
        port_open = False
        
        while time.time() - start_time < max_wait:
            # Check if process has exited early (indicates failure)
            if process:
                poll_result = process.poll()
                if poll_result is not None:
                    # Process has exited - get stderr output
                    try:
                        _, stderr = process.communicate(timeout=1)
                        stderr_text = stderr.decode('utf-8', errors='replace').strip() if stderr else ''
                    except Exception as e:
                        stderr_text = f'(failed to read stderr: {e})'
                    
                    error_msg = f'Chrome process exited prematurely with code {poll_result}'
                    if stderr_text:
                        error_msg += f'\nStderr: {stderr_text}'
                    
                    # Check for common errors
                    if 'not found' in stderr_text.lower():
                        error_msg += '\n\nChromium executable not found. Please install chromium-browser.'
                    
                    print(f'[ChromeManager] ERROR: {error_msg}')
                    raise RuntimeError(error_msg)
            
            # Try to connect to debug port
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.settimeout(1)
                s.connect(('127.0.0.1', debug_port))
                s.close()
                port_open = True
                elapsed = time.time() - start_time
                print(f'[ChromeManager] Chrome ready! Port {debug_port} open after {elapsed:.2f}s')
                _log_phase('chrome.wait_for_debug_port', _t_port, f'polled every {CHROME_READY_POLL_S} s')
                # The port answers before the startup tab exists: wait for the tab, not a clock.
                _t_page = _phase_t0()
                page_ready, polls = ChromeManager.wait_for_cdp_page(debug_port)
                _log_phase('chrome.wait_for_cdp_page', _t_page, f'ready={page_ready} polls={polls}')
                if not page_ready:
                    print(f'[ChromeManager] No page target on port {debug_port} after '
                          f'{CHROME_PAGE_READY_MAX_WAIT_S}s - continuing, as the fixed sleeps did')
                break
            except (socket.timeout, socket.error):
                time.sleep(CHROME_READY_POLL_S)
        
        if not port_open:
            error_msg = f'Timed out waiting for Chrome port {debug_port} after {max_wait} seconds'
            
            # If process is still running but port never opened
            if process and process.poll() is None:
                error_msg += '\nChrome process is still running but debug port is not accessible.'
            
            print(f'[ChromeManager] ERROR: {error_msg}')
            raise RuntimeError(error_msg)


# Restore AsyncExecutor
class AsyncExecutor:
    """Executor for running async coroutines in dedicated threads."""
    
    def run_async(self, coro):
        """Run async coroutine in a dedicated thread with new event loop."""
        import asyncio
        import threading
        def run_in_thread():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                return loop.run_until_complete(coro)
            finally:
                loop.close()
        
        thread = threading.Thread(target=run_in_thread)
        thread.start()
        thread.join()
        # Note: To get return value, we'd need a queue or future, but for simplicity assume void or adjust as needed


class PlaywrightConnection:
    """Manages Playwright connections to Chrome via CDP using SYNC API."""
    
    @staticmethod
    async def connect_to_chrome(cdp_url: str = 'http://127.0.0.1:9222') -> Tuple[Any, Any, Any, Any]:
        """Connect to Chrome via CDP and return playwright, browser, context, page."""
        from playwright.async_api import async_playwright
        import asyncio
        import threading
        
        print(f'[PlaywrightConnection] Thread: {threading.current_thread().name}')

        playwright = None
        try:
            print(f'[PlaywrightConnection] Starting Playwright and connecting to Chrome at {cdp_url}')
            playwright = await async_playwright().start()
            print(f'[PlaywrightConnection] Playwright started, attempting CDP connection...')
            browser = await playwright.chromium.connect_over_cdp(cdp_url)
            print(f'[PlaywrightConnection] Successfully connected to Chrome via CDP')
            
            if len(browser.contexts) == 0:
                print(f'[PlaywrightConnection] No existing contexts, creating new context...')
                context = await browser.new_context()
                page = await context.new_page()
                print(f'[PlaywrightConnection] Created new context with browser default viewport')
            else:
                print(f'[PlaywrightConnection] Found {len(browser.contexts)} existing contexts, using first one...')
                context = browser.contexts[0]
                if len(context.pages) == 0:
                    print(f'[PlaywrightConnection] No pages in context, creating new page...')
                    page = await context.new_page()
                else:
                    print(f'[PlaywrightConnection] Found {len(context.pages)} pages in context, using first one...')
                    page = context.pages[0]
                print(f'[PlaywrightConnection] Using existing context with browser default viewport')
            
            print(f'[PlaywrightConnection] Connection established successfully')
            return playwright, browser, context, page
            
        except BaseException as e:
            # The driver started before the CDP attach: nobody gets a handle to stop it, so stop
            # it here. This is the common path - connect_browser() probes before Chrome runs.
            await stop_playwright(playwright)
            if not isinstance(e, Exception):
                raise
            error_type = type(e).__name__
            print(f'[PlaywrightConnection] Connection failed - {error_type}: {str(e)}')
            print(f'[PlaywrightConnection] CDP URL: {cdp_url}')
            
            # Check if it's a connection refused error
            if 'ECONNREFUSED' in str(e) or 'Connection refused' in str(e):
                print(f'[PlaywrightConnection] Chrome is not running or not accepting connections on {cdp_url}')
            elif 'timeout' in str(e).lower():
                print(f'[PlaywrightConnection] Connection timeout - Chrome may be starting up or overloaded')
            
            raise Exception(f"CDP connection failed ({error_type}): {str(e)}")
    
    @staticmethod
    async def cleanup_connection(playwright, browser):
        """Clean up Playwright connection."""
        if browser:
            await browser.close()
        if playwright:
            playwright.stop()  # Note: stop is sync, adjust if needed


class PlaywrightUtils:
    """Main utility class combining Chrome management, Playwright operations, and cookie management using SYNC API."""
    
    def __init__(self, auto_accept_cookies: bool = True, user_data_dir: str = "./config/user_data",
                 use_cgroup: bool = False, cpu_quota: str = "100%", memory_max: str = "4G", memory_high: str = "3G",
                 debug_port: int = 9222):
        """
        Initialize PlaywrightUtils with auto-sizing browser.

        Args:
            auto_accept_cookies: Whether to automatically inject consent cookies
            user_data_dir: Chrome user data directory for persistent sessions
            use_cgroup: Whether to use systemd-run with cgroup v2 resource limits
            cpu_quota: CPU quota limit (e.g., "50%" for 50% of one core)
            memory_max: Maximum memory limit (e.g., "1G", "512M")
            memory_high: Memory high limit for early pressure (e.g., "768M")
            debug_port: Chrome remote-debugging port (one per host: see BUG-0114 "Not fixed here")
        """
        self.chrome_manager = ChromeManager()
        self.connection = PlaywrightConnection()
        self.cookie_manager = CookieManager() if auto_accept_cookies else None
        self.auto_accept_cookies = auto_accept_cookies
        self.user_data_dir = resolve_user_data_dir(user_data_dir)
        self.debug_port = debug_port
        
        # Cgroup v2 resource limits
        self.use_cgroup = use_cgroup
        self.cpu_quota = cpu_quota
        self.memory_max = memory_max
        self.memory_high = memory_high
        
        cgroup_status = f"cgroup={use_cgroup}" if use_cgroup else "cgroup=disabled"
        if use_cgroup:
            cgroup_status += f" (CPU={cpu_quota}, Mem={memory_max}/{memory_high})"
        
        print(f'[PlaywrightUtils] Initialized with auto_accept_cookies={auto_accept_cookies}, viewport=auto (browser default), user_data_dir={self.user_data_dir}, {cgroup_status}, SYNC API')
    
    def normalize_url(self, url: str) -> str:
        """
        Normalize URL by adding protocol if missing.
        
        Args:
            url: Input URL that may be missing protocol
            
        Returns:
            Normalized URL with https:// prefix if needed
        """
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
    
    def launch_chrome(self, debug_port: Optional[int] = None) -> subprocess.Popen:
        """Launch Chrome with remote debugging and persistent data."""
        # Launch Chrome maximized with persistent user data directory and optional cgroup limits
        return self.chrome_manager.launch_chrome_with_remote_debugging(
            debug_port if debug_port is not None else self.debug_port,
            user_data_dir=self.user_data_dir,
            use_cgroup=self.use_cgroup,
            cpu_quota=self.cpu_quota,
            memory_max=self.memory_max,
            memory_high=self.memory_high
        )
    
    def kill_chrome(self, chrome_process=None) -> bool:
        """Terminate the browser on the debug port: the one we launched, or whatever we attached to.
        Returns True once the port has no listener."""
        return self.chrome_manager.shutdown_chrome(self.debug_port, chrome_process=chrome_process)

    async def connect_to_chrome(self, cdp_url: Optional[str] = None, target_url: str = None):
        """
        Connect to Chrome via CDP with automatic cookie injection.
        
        Args:
            cdp_url: Chrome debug protocol URL
            target_url: URL that will be visited (for auto-cookie detection)
            
        Returns:
            Tuple of (playwright, browser, context, page)
        """
        # Connect with browser default viewport
        if cdp_url is None:
            cdp_url = f'http://localhost:{self.debug_port}'
        playwright, browser, context, page = await self.connection.connect_to_chrome(cdp_url)
        
        # Auto-inject cookies if enabled and target URL provided
        if self.auto_accept_cookies and self.cookie_manager and target_url:
            try:
                # Note: Cookie manager may need to be updated to sync if it uses async
                # For now, we'll try to inject cookies synchronously
                # If cookie_manager has async methods, we may need to skip this or update it
                print(f'[PlaywrightUtils] Cookie auto-injection available for {target_url}')
                # await self.cookie_manager.auto_accept_cookies_for_url(context, target_url)
                # print(f'[PlaywrightUtils] Auto-injected cookies for {target_url}')
            except Exception as e:
                print(f'[PlaywrightUtils] Warning: Failed to inject cookies for {target_url}: {e}')
        
        return playwright, browser, context, page
    
    async def cleanup_connection(self, playwright, browser):
        """Clean up connection."""
        await self.connection.cleanup_connection(playwright, browser)
    

    
    def inject_cookies_for_sites(self, context, sites: list):
        """
        Manually inject cookies for specific sites.
        
        Args:
            context: Playwright browser context
            sites: List of site names (e.g., ['youtube', 'google'])
        """
        if self.cookie_manager:
            # Note: Cookie manager may need sync update if it uses async
            print(f'[PlaywrightUtils] Cookie injection requested for sites: {sites}')
            # await self.cookie_manager.inject_cookies(context, sites)
        else:
            print('[PlaywrightUtils] Warning: Cookie manager not initialized')
    
    def get_available_cookie_configs(self) -> list:
        """Get list of available cookie configurations."""
        if self.cookie_manager:
            return self.cookie_manager.get_available_configs()
        return []


# Convenience functions for external use
def create_playwright_utils(auto_accept_cookies: bool = True, user_data_dir: str = "./config/user_data",
                           use_cgroup: bool = False, cpu_quota: str = "100%", memory_max: str = "4G", memory_high: str = "3G") -> PlaywrightUtils:
    """Create a PlaywrightUtils instance."""
    return PlaywrightUtils(auto_accept_cookies=auto_accept_cookies, user_data_dir=user_data_dir,
                          use_cgroup=use_cgroup, cpu_quota=cpu_quota, memory_max=memory_max, memory_high=memory_high)


def launch_chrome_for_debugging(debug_port: int = 9222, user_data_dir: str = "./config/user_data",
                               use_cgroup: bool = False, cpu_quota: str = "100%", memory_max: str = "4G", memory_high: str = "3G") -> subprocess.Popen:
    """Quick function to launch Chrome with remote debugging and persistent data."""
    resolved_user_data_dir = resolve_user_data_dir(user_data_dir)
    return ChromeManager.launch_chrome_with_remote_debugging(debug_port, user_data_dir=resolved_user_data_dir,
                                                            use_cgroup=use_cgroup, cpu_quota=cpu_quota, 
                                                            memory_max=memory_max, memory_high=memory_high)


# run_async_playwright removed - no longer needed with sync API!


def get_available_cookie_sites() -> list:
    """Quick function to get available cookie sites."""
    manager = CookieManager()
    return manager.get_available_configs()


# Browser-use compatibility functions
def get_playwright_context_with_cookies(target_url: str = None):
    """
    Get a Playwright context with auto-injected cookies for browser-use compatibility.
    
    Args:
        target_url: URL to inject cookies for
        
    Returns:
        Tuple of (playwright, browser, context, page)
    """
    utils = PlaywrightUtils(auto_accept_cookies=True)
    return utils.connect_to_chrome(target_url=target_url) 
