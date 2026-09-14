"""
Network Utilities - Speedtest and network measurement functions

Consolidated speedtest implementation used by both backend_host and backend_server.
Uses speedtest-cli command line tool to avoid gevent/threading issues with Python library.
"""

import os
import sys
import time
import json
import tempfile
import subprocess
import threading
from datetime import datetime, timezone
from typing import Dict, Any, Optional

# Platform-specific file locking
if sys.platform == 'win32':
    import msvcrt
    def lock_file(f, exclusive=False):
        msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK if exclusive else msvcrt.LK_LOCK, 1)
    def unlock_file(f):
        try:
            msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
        except:
            pass
else:
    import fcntl
    def lock_file(f, exclusive=False):
        fcntl.flock(f.fileno(), fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH)
    def unlock_file(f):
        fcntl.flock(f.fileno(), fcntl.LOCK_UN)

# Speedtest shared cache - platform-specific path
if sys.platform == 'win32':
    SPEEDTEST_CACHE = os.path.join(os.environ.get('TEMP', 'C:\\Windows\\Temp'), 'speedtest_cache.json')
else:
    SPEEDTEST_CACHE = '/tmp/speedtest_cache.json'

# Cross-process run-lock: ensures only ONE speedtest executes at a time across
# every process on the box (e.g. co-located backend_host + backend_server, where
# the shared cache wasn't enough — both metric loops would race past a stale
# cache and each kick off their own test). Held only for the duration of the
# subprocess call; the cache file is the canonical result store.
SPEEDTEST_RUN_LOCK = SPEEDTEST_CACHE + '.runlock'

CACHE_DURATION = 600  # 10 minutes

# Prevent multiple simultaneous background speedtests
_background_speedtest_running = False
_background_speedtest_lock = threading.Lock()


def _try_acquire_run_lock():
    """
    Try to acquire the cross-process speedtest run-lock (non-blocking, exclusive).

    Returns:
        Open file handle on success, None if another process already holds it.
        Caller MUST pass the returned handle to `_release_run_lock` when done.
    """
    try:
        fh = open(SPEEDTEST_RUN_LOCK, 'a+')
    except OSError as e:
        print(f"⚠️ [SPEEDTEST] Could not open run-lock file {SPEEDTEST_RUN_LOCK}: {e}")
        return None
    try:
        if sys.platform == 'win32':
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        return fh
    except (IOError, OSError, BlockingIOError):
        # Lock held elsewhere — another process is running the test
        try:
            fh.close()
        except Exception:
            pass
        return None


def _release_run_lock(fh):
    if fh is None:
        return
    try:
        if sys.platform == 'win32':
            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    except Exception:
        pass
    try:
        fh.close()
    except Exception:
        pass


def _read_fresh_cache():
    """
    Read the shared cache and return the formatted result dict if it's still
    fresh (within CACHE_DURATION) and values are valid; otherwise return None.
    Used both on the cold path (before running a test) and after acquiring the
    run-lock (to absorb results another process just produced).
    """
    if not os.path.exists(SPEEDTEST_CACHE):
        return None
    try:
        with open(SPEEDTEST_CACHE, 'r') as f:
            lock_file(f, exclusive=False)
            try:
                cache = json.load(f)
            finally:
                unlock_file(f)
    except (json.JSONDecodeError, KeyError, OSError):
        return None
    age = time.time() - cache.get('timestamp', 0)
    if age >= CACHE_DURATION:
        return None
    download = cache.get('download_mbps')
    upload = cache.get('upload_mbps')
    if not download or not upload:
        return None
    return {
        'download_mbps': download,
        'upload_mbps': upload,
        'speedtest_last_run': datetime.fromtimestamp(cache['timestamp'], tz=timezone.utc).isoformat(),
        'speedtest_age_seconds': int(age)
    }


def _write_cache(download_mbps, upload_mbps):
    """Write a measured result to the shared cache. Silent on permission errors."""
    try:
        with open(SPEEDTEST_CACHE, 'w') as f:
            lock_file(f, exclusive=True)
            try:
                json.dump({
                    'timestamp': time.time(),
                    'download_mbps': download_mbps,
                    'upload_mbps': upload_mbps
                }, f)
            finally:
                unlock_file(f)
    except (PermissionError, OSError) as perm_error:
        print(f"⚠️ [SPEEDTEST] Cannot write cache (permission denied): {perm_error}")


def get_network_speed_cached(skip_if_no_cache=False, return_zeros_on_failure=False):
    """
    Get network speed with shared cache - consolidated implementation.

    The shared file cache (SPEEDTEST_CACHE) is the canonical store: on a box
    running both backend_host and backend_server (e.g. host1 = rpitest), both
    processes consult the same cache so one measurement powers both metrics
    streams. The cross-process run-lock (SPEEDTEST_RUN_LOCK) guarantees that
    when the cache expires only one process actually executes the subprocess.

    Args:
        skip_if_no_cache: If True, return empty dict if cache doesn't exist (for startup optimization)
        return_zeros_on_failure: If True, return {'download_mbps': 0, 'upload_mbps': 0} on failure
                                If False, return {'download_mbps': None, 'upload_mbps': None} on failure

    Returns:
        Dict with speedtest results or empty dict on failure
    """
    # Allow disabling speedtest via env var (useful for runner hosts to avoid subprocess/gunicorn conflicts)
    if os.getenv('SKIP_SPEEDTEST', '').lower() in ('true', '1', 'yes'):
        return {}
    try:
        # Fast path: fresh shared cache
        cached = _read_fresh_cache()
        if cached is not None:
            return cached

        # Skip speedtest if requested (for startup optimization)
        if skip_if_no_cache:
            print("🌐 [SPEEDTEST] Skipping initial speedtest (will run in background)")
            # Check if background speedtest is already running in THIS process
            global _background_speedtest_running
            with _background_speedtest_lock:
                if not _background_speedtest_running:
                    _background_speedtest_running = True
                    print("🚀 [SPEEDTEST] Starting new background speedtest thread")
                    # Start async speedtest in background thread; cross-process
                    # dedup happens inside _run_speedtest_async via the run-lock.
                    thread = threading.Thread(target=_run_speedtest_async, daemon=True)
                    thread.start()
                else:
                    print("⏳ [SPEEDTEST] Background speedtest already running in this process - skipping duplicate")
            return {}

        # Cache expired/missing - try to claim the cross-process run-lock and test.
        # If another process is already running the test, don't queue behind it;
        # return empty so this metric tick records no value and the next 1-min
        # tick can hit the freshly-written cache.
        lock_fh = _try_acquire_run_lock()
        if lock_fh is None:
            print("⏳ [SPEEDTEST] Another process is running the test - skipping this tick")
            # Best-effort re-read: a writer might have just released the cache.
            cached = _read_fresh_cache()
            return cached if cached is not None else {}

        try:
            # Re-check cache under the lock: another process might have just
            # finished a test moments before we acquired (write-then-release
            # ordering). Reuse their result instead of running our own.
            cached = _read_fresh_cache()
            if cached is not None:
                return cached

            result = measure_network_speed()
            if not result or result.get('download_mbps') is None:
                failure_msg = "⚠️ [SPEEDTEST] Test failed - skipping cache and metrics storage"
                if return_zeros_on_failure:
                    failure_msg += " (returning zeros)"
                print(failure_msg)
                return {}

            _write_cache(result['download_mbps'], result['upload_mbps'])
            return {
                'download_mbps': result['download_mbps'],
                'upload_mbps': result['upload_mbps'],
                'speedtest_last_run': datetime.now(timezone.utc).isoformat(),
                'speedtest_age_seconds': 0
            }
        finally:
            _release_run_lock(lock_fh)
    except Exception as e:
        print(f"⚠️ [SPEEDTEST] Error: {e}")
        return {}  # Fail gracefully


def _run_speedtest_async():
    """Run speedtest in background and save to cache.

    Claims the cross-process run-lock so a sibling process (e.g. vpt-server
    while we're vpt-host on the same Pi) doesn't fire its own subprocess in
    parallel. If the lock is held elsewhere, we simply exit — the other
    process will write the cache and both metric loops will pick it up.
    """
    lock_fh = None
    try:
        print("🌐 [SPEEDTEST] Starting background speedtest...")

        # If someone else just wrote a fresh cache between our scheduling and
        # now, don't bother running.
        if _read_fresh_cache() is not None:
            print("✅ [SPEEDTEST] Cache already fresh - background test skipped")
            return

        lock_fh = _try_acquire_run_lock()
        if lock_fh is None:
            print("⏳ [SPEEDTEST] Another process is running the test - background test skipped")
            return

        # Re-check under the lock (avoids racing with a writer that just finished).
        if _read_fresh_cache() is not None:
            print("✅ [SPEEDTEST] Cache turned fresh while acquiring lock - background test skipped")
            return

        result = measure_network_speed()

        if result:
            download = result.get('download_mbps')
            upload = result.get('upload_mbps')
            print(f"📊 [SPEEDTEST] Background test result: Download={download} Mbps, Upload={upload} Mbps")
        else:
            print("📊 [SPEEDTEST] Background test result: None (failed)")

        if not result or result.get('download_mbps') is None or result.get('upload_mbps') is None:
            print("⚠️ [SPEEDTEST] Background test failed - skipping cache")
        else:
            _write_cache(result['download_mbps'], result['upload_mbps'])
            print("✅ [SPEEDTEST] Background test completed and cached")

    except Exception as e:
        print(f"⚠️ [SPEEDTEST] Background test error: {e}")
    finally:
        _release_run_lock(lock_fh)
        # Always reset the in-process flag when done
        with _background_speedtest_lock:
            global _background_speedtest_running
            _background_speedtest_running = False
            print("🔄 [SPEEDTEST] Background speedtest thread completed")


def _detect_speedtest_variant(speedtest_cmd):
    """
    Detect whether the speedtest binary is Ookla CLI or Python speedtest-cli.

    Returns:
        'ookla' or 'python-cli'
    """
    try:
        result = subprocess.run(
            [speedtest_cmd, '--version'],
            capture_output=True,
            text=True,
            timeout=10
        )
        output = (result.stdout + result.stderr).lower()
        # Ookla CLI prints "Speedtest by Ookla" in its version output
        if 'ookla' in output:
            return 'ookla'
    except Exception:
        pass
    return 'python-cli'


def measure_network_speed():
    """
    Run speedtest using CLI tool (supports both Ookla CLI and Python speedtest-cli)

    This avoids gevent/threading issues with the Python library by using
    a separate subprocess that works reliably in our environment.

    Returns:
        Dict with 'download_mbps' and 'upload_mbps' keys, or None values on failure
    """
    import shutil

    print("🌐 [SPEEDTEST] Running network speed test using CLI...")

    # Find speedtest executable
    speedtest_cmd = shutil.which('speedtest')
    if not speedtest_cmd:
        # Try common virtual environment and system paths (Linux + Windows)
        if sys.platform == 'win32':
            venv_paths = [
                os.path.join(os.environ.get('VIRTUALPYTEST_ROOT', r'C:\virtualpytest\virtualpytest'), 'venv', 'Scripts', 'speedtest.exe'),
                r'.\venv\Scripts\speedtest.exe',
                os.path.join(sys.prefix, 'Scripts', 'speedtest.exe'),
            ]
        else:
            venv_paths = [
                '/opt/virtualpytest/venv/bin/speedtest',
                './venv/bin/speedtest',
                '/usr/local/bin/speedtest',
                '/usr/bin/speedtest',
            ]
        print(f"   - PATH (via shutil.which): not found")
        for path in venv_paths:
            exists = os.path.exists(path)
            print(f"   - {path}: {'found' if exists else 'not found'}")
            if exists and (sys.platform == 'win32' or os.access(path, os.X_OK)):
                speedtest_cmd = path
                break

    if not speedtest_cmd:
        print("❌ [SPEEDTEST] speedtest not found in PATH or common locations")
        print("   💡 Install with: pip install speedtest-cli  OR  apt install speedtest")
        return {'download_mbps': None, 'upload_mbps': None}

    # Detect which speedtest variant is installed
    variant = _detect_speedtest_variant(speedtest_cmd)
    print(f"🚀 [SPEEDTEST] Found speedtest at: {speedtest_cmd} (variant: {variant})")

    try:
        if variant == 'ookla':
            # Ookla Speedtest CLI: uses --format=json, returns bytes/sec directly
            cmd = [speedtest_cmd, '--format=json', '--accept-license', '--accept-gdpr']
            print(f"🚀 [SPEEDTEST] Executing: {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=75)
        else:
            # Python speedtest-cli: uses --json, returns bits/sec
            cmd = [speedtest_cmd, '--json', '--timeout', '120']
            print(f"🚀 [SPEEDTEST] Executing: {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=75)

        if result.returncode == 0 and result.stdout:
            try:
                if variant == 'ookla':
                    # Ookla CLI outputs JSONL (multiple JSON lines): log lines + result line
                    # Find the line with "type":"result" which contains the actual speeds
                    data = None
                    for line in result.stdout.strip().splitlines():
                        try:
                            parsed = json.loads(line)
                            if parsed.get('type') == 'result':
                                data = parsed
                                break
                        except json.JSONDecodeError:
                            continue
                    if not data:
                        print("❌ [SPEEDTEST] No result line found in Ookla JSONL output")
                        print(f"   📄 Raw output: {result.stdout[:300]}...")
                        return {'download_mbps': None, 'upload_mbps': None}

                    # Ookla CLI: bandwidth is in bytes/sec under 'download'/'upload' objects
                    download_bw = data.get('download', {}).get('bandwidth', 0)
                    upload_bw = data.get('upload', {}).get('bandwidth', 0)
                    # Convert bytes/sec to Mbps: bytes * 8 / 1_000_000
                    download_mbps = round(download_bw * 8 / 1_000_000, 2)
                    upload_mbps = round(upload_bw * 8 / 1_000_000, 2)
                else:
                    # Python speedtest-cli: single JSON object, values in bits/sec
                    data = json.loads(result.stdout)
                    download_mbps = round(data['download'] / 1_000_000, 2)
                    upload_mbps = round(data['upload'] / 1_000_000, 2)

                print(f"✅ [SPEEDTEST] CLI Results - Download: {download_mbps} Mbps, Upload: {upload_mbps} Mbps")

                # Validate results
                if download_mbps == 0.0 or upload_mbps == 0.0:
                    print("❌ [SPEEDTEST] CRITICAL: CLI returned 0.0 Mbps!")
                    print(f"   📊 Raw results: Download={download_mbps}, Upload={upload_mbps}")
                    return {'download_mbps': None, 'upload_mbps': None}

                return {'download_mbps': download_mbps, 'upload_mbps': upload_mbps}

            except (json.JSONDecodeError, KeyError) as parse_error:
                print(f"❌ [SPEEDTEST] Failed to parse CLI JSON output: {parse_error}")
                print(f"   📄 Raw output: {result.stdout[:300]}...")
                return {'download_mbps': None, 'upload_mbps': None}

        else:
            # CLI command failed
            print(f"❌ [SPEEDTEST] CLI command failed (exit code: {result.returncode})")
            if result.stderr:
                print(f"   🚨 STDERR: {result.stderr[:300]}")
            if result.stdout:
                print(f"   📄 STDOUT: {result.stdout[:300]}")
            return {'download_mbps': None, 'upload_mbps': None}

    except subprocess.TimeoutExpired:
        print("⏰ [SPEEDTEST] CLI command timed out (75s total)")
        return {'download_mbps': None, 'upload_mbps': None}

    except Exception as e:
        error_msg = str(e)
        if '403' in error_msg or 'Forbidden' in error_msg:
            print("🚫 [SPEEDTEST] Blocked by network/ISP (403 Forbidden)")
        elif 'timeout' in error_msg.lower():
            print("⏰ [SPEEDTEST] Timeout during speed test")
        else:
            print(f"💥 [SPEEDTEST] Unexpected error: {error_msg}")

        return {'download_mbps': None, 'upload_mbps': None}
