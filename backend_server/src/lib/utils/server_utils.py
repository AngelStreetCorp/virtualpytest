"""
Server Utilities

Host registration and management for the backend server.
Handles tracking of registered hosts without device controller dependencies.
"""

import threading
import time
import os
import sys
import psutil
import subprocess
import json
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
from shared.src.lib.utils.system_monitoring_utils import _get_load_average, get_cpu_temperature
from shared.src.lib.utils.build_url_utils import call_host

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

# Speedtest functionality moved to shared network_utils

# Speedtest functions moved to shared/src/lib/utils/network_utils.py
from shared.src.lib.utils.network_utils import get_network_speed_cached

# All speedtest functions moved to shared/src/lib/utils/network_utils.py

HOST_REGISTRY_STATE_FILE = os.getenv('HOST_REGISTRY_STATE_FILE', '/var/tmp/vpt_registered_hosts.json')
HOST_RESTORE_HEALTHCHECK_TIMEOUT_SECONDS = 5


class HostManager:
    """Host storage and management (no locking - use lock_utils for that)"""
    
    def __init__(self):
        # Thread-safe storage for hosts
        self._hosts: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.RLock()
        self._load_hosts_from_disk()

    def _persist_hosts_to_disk(self) -> None:
        """Persist host registry to disk so server restarts can recover it."""
        try:
            state_dir = os.path.dirname(HOST_REGISTRY_STATE_FILE)
            if state_dir:
                os.makedirs(state_dir, exist_ok=True)

            tmp_path = f"{HOST_REGISTRY_STATE_FILE}.tmp"
            payload = {
                'saved_at': datetime.now(timezone.utc).isoformat(),
                'hosts': self._hosts,
            }

            with open(tmp_path, 'w', encoding='utf-8') as handle:
                lock_file(handle, exclusive=True)
                json.dump(payload, handle, ensure_ascii=True)
                handle.flush()
                os.fsync(handle.fileno())
                unlock_file(handle)

            os.replace(tmp_path, HOST_REGISTRY_STATE_FILE)
        except Exception as e:
            print(f"⚠️ [HostManager] Failed to persist host registry: {e}")

    def _load_hosts_from_disk(self) -> None:
        """Restore host registry after server restart."""
        try:
            if not os.path.isfile(HOST_REGISTRY_STATE_FILE):
                return

            with open(HOST_REGISTRY_STATE_FILE, 'r', encoding='utf-8') as handle:
                lock_file(handle, exclusive=False)
                payload = json.load(handle)
                unlock_file(handle)

            hosts = payload.get('hosts', {}) if isinstance(payload, dict) else {}
            if not isinstance(hosts, dict):
                print("⚠️ [HostManager] Ignoring invalid host registry state file")
                return

            now = time.time()
            restored_count = 0
            for host_name, host_data in hosts.items():
                if not isinstance(host_data, dict) or not host_name:
                    continue
                host_copy = dict(host_data)
                host_copy['status'] = host_copy.get('status') or 'unknown'
                host_copy['restored_from_disk'] = True
                host_copy['validation_pending'] = True
                host_copy['restored_at'] = now
                self._hosts[host_name] = host_copy
                restored_count += 1

            if restored_count:
                print(f"♻️ [HostManager] Restored {restored_count} host(s) from {HOST_REGISTRY_STATE_FILE}")
        except Exception as e:
            print(f"⚠️ [HostManager] Failed to restore host registry: {e}")

    def validate_restored_hosts(self) -> None:
        """Check restored hosts against their live /health endpoint before treating them as online.

        Health checks fan out concurrently via a gevent pool so the total wait is bounded
        by HOST_RESTORE_HEALTHCHECK_TIMEOUT_SECONDS regardless of host count.
        """
        host_names_to_check = []
        with self._lock:
            for host_name, host_data in self._hosts.items():
                if host_data.get('validation_pending'):
                    host_names_to_check.append(host_name)

        if not host_names_to_check:
            return

        def _check(host_name: str):
            try:
                host_snapshot = self.get_host(host_name)
                if not host_snapshot:
                    return host_name, None, None, None
                response_data, status_code = call_host(
                    host_snapshot,
                    '/health',
                    method='GET',
                    timeout=HOST_RESTORE_HEALTHCHECK_TIMEOUT_SECONDS,
                )
                return host_name, response_data, status_code, None
            except Exception as exc:
                return host_name, None, None, exc

        try:
            from gevent.pool import Pool
            pool = Pool(min(len(host_names_to_check), 32))
            results = list(pool.imap_unordered(_check, host_names_to_check))
        except ImportError:
            # No gevent (e.g. Windows dev) — fall back to sequential.
            results = [_check(name) for name in host_names_to_check]

        any_persisted = False
        for host_name, response_data, status_code, exc in results:
            with self._lock:
                current_host = self._hosts.get(host_name)
                if not current_host:
                    continue

                current_host['last_health_check_at'] = time.time()
                current_host['validation_pending'] = False

                if exc is not None:
                    current_host['status'] = 'offline'
                    current_host['health_check_status'] = 'offline'
                    current_host['health_check_error'] = str(exc)
                    print(f"⚠️ [HostManager] Health validation failed for restored host {host_name}: {exc}")
                elif status_code == 200:
                    current_host['status'] = 'online'
                    current_host['restored_from_disk'] = False
                    current_host['health_check_status'] = 'online'
                    print(f"✅ [HostManager] Restored host is reachable: {host_name}")
                else:
                    current_host['status'] = 'offline'
                    current_host['health_check_status'] = 'offline'
                    current_host['health_check_error'] = response_data.get('error') if isinstance(response_data, dict) else None
                    print(f"⚠️ [HostManager] Restored host is not reachable: {host_name} (status={status_code})")
                any_persisted = True

        if any_persisted:
            with self._lock:
                self._persist_hosts_to_disk()
    
    def register_host(self, host_name: str, host_data: Dict[str, Any]) -> bool:
        """Register or update a host"""
        with self._lock:
            try:
                # Ensure required fields
                if not host_name or not host_data.get('host_url'):
                    return False
                
                # Add metadata
                current_time = time.time()
                host_data['last_seen'] = current_time
                host_data['status'] = 'online'
                host_data['validation_pending'] = False
                host_data['restored_from_disk'] = False
                host_data['last_health_check_at'] = current_time
                host_data.pop('health_check_error', None)
                
                # If updating existing host, preserve registration time
                if host_name in self._hosts:
                    existing_host = self._hosts[host_name]
                    host_data['registered_at'] = existing_host.get('registered_at', datetime.now().isoformat())
                    host_data['reconnected_at'] = datetime.now().isoformat()
                    print(f"🔄 [HostManager] Updating existing host: {host_name}")
                else:
                    host_data['registered_at'] = datetime.now().isoformat()
                    print(f"✅ [HostManager] Registering new host: {host_name}")
                
                self._hosts[host_name] = host_data
                self._persist_hosts_to_disk()
                return True
                
            except Exception as e:
                print(f"❌ [HostManager] Error registering host {host_name}: {e}")
                return False
    
    def unregister_host(self, host_name: str) -> bool:
        """Unregister a host"""
        with self._lock:
            try:
                if host_name in self._hosts:
                    del self._hosts[host_name]
                    print(f"🗑️ [HostManager] Unregistered host: {host_name}")
                    self._persist_hosts_to_disk()
                    return True
                else:
                    print(f"⚠️ [HostManager] Host not found for unregistration: {host_name}")
                    return False
                    
            except Exception as e:
                print(f"❌ [HostManager] Error unregistering host {host_name}: {e}")
                return False
    
    def get_host(self, host_name: str) -> Optional[Dict[str, Any]]:
        """Get host data by name"""
        with self._lock:
            return self._hosts.get(host_name)
    
    def get_all_hosts(self) -> Dict[str, Dict[str, Any]]:
        """Get all registered hosts"""
        with self._lock:
            return self._hosts.copy()
    
    def update_host_ping(self, host_name: str, ping_data: Dict[str, Any] = None) -> bool:
        """Update host's last seen time (for ping responses)"""
        with self._lock:
            if host_name in self._hosts:
                self._hosts[host_name]['last_seen'] = time.time()
                self._hosts[host_name]['status'] = 'online'
                self._hosts[host_name]['validation_pending'] = False
                self._hosts[host_name]['restored_from_disk'] = False
                self._hosts[host_name]['last_health_check_at'] = time.time()
                self._hosts[host_name].pop('health_check_error', None)
                # Optionally update additional ping data if provided
                if ping_data:
                    # Store relevant ping data (system stats, device metrics, etc.)
                    self._hosts[host_name]['last_ping_data'] = ping_data
                    
                    # Update system_stats if provided in ping (for real-time display)
                    if 'system_stats' in ping_data:
                        self._hosts[host_name]['system_stats'] = ping_data['system_stats']
                    
                    # Update device deployment status if provided
                    if 'devices' in ping_data:
                        for updated_device in ping_data['devices']:
                            device_id = updated_device.get('device_id')
                            if device_id and 'devices' in self._hosts[host_name]:
                                # Refresh device metadata from host pings so the registry does not keep stale
                                # values like ir_type/device_name after a host-side config change.
                                for existing_device in self._hosts[host_name]['devices']:
                                    if existing_device.get('device_id') == device_id:
                                        for field in (
                                            'device_name',
                                            'device_model',
                                            'device_ip',
                                            'device_port',
                                            'ir_type',
                                            'video_stream_path',
                                            'video_capture_path',
                                            'video',
                                            'video_fps',
                                            'device_capabilities',
                                            'device_verification_types',
                                            'device_action_types',
                                            'has_running_deployment',
                                        ):
                                            if field in updated_device:
                                                existing_device[field] = updated_device.get(field)
                                        if 'has_running_deployment' not in updated_device:
                                            existing_device['has_running_deployment'] = False
                                        break
                self._persist_hosts_to_disk()
                return True
            return False
    
    def cleanup_stale_hosts(self, timeout_seconds: int = 180) -> List[str]:
        """Remove hosts that haven't been seen for timeout_seconds (default 3 minutes).
        Called lazily from getAllHosts — no background thread needed."""
        with self._lock:
            current_time = time.time()
            stale_hosts = []

            for host_name, host_data in self._hosts.items():
                last_seen = host_data.get('last_seen', 0)
                time_since_seen = current_time - last_seen
                if time_since_seen > timeout_seconds:
                    stale_hosts.append(host_name)
                    print(f"🧹 [HostManager] Host '{host_name}' is stale (last seen {time_since_seen:.1f}s ago, timeout {timeout_seconds}s)")

            for host_name in stale_hosts:
                del self._hosts[host_name]
                print(f"🧹 [HostManager] Removed stale host: {host_name}")

            if stale_hosts:
                self._persist_hosts_to_disk()

            return stale_hosts
    
    def get_host_count(self) -> int:
        """Get total number of registered hosts"""
        with self._lock:
            return len(self._hosts)
    
    def is_host_registered(self, host_name: str) -> bool:
        """Check if a host is registered"""
        with self._lock:
            return host_name in self._hosts


# Global instance for server
_host_manager = HostManager()


def get_host_manager() -> HostManager:
    """Get the global host manager instance for server"""
    global _host_manager
    return _host_manager





def get_server_system_stats(skip_speedtest=False):
    """
    Get comprehensive system statistics for the server
    
    Args:
        skip_speedtest: If True, skip speedtest if no cache exists (for startup optimization)
    """
    try:
        # Get server name from environment
        server_name = os.getenv('SERVER_NAME') or 'server'
        
        # Get disk path based on platform
        disk_path = 'C:\\' if sys.platform == 'win32' else '/'
        
        # Get platform info
        if sys.platform == 'win32':
            import platform
            platform_name = 'Windows'
            architecture = platform.machine()
        else:
            platform_name = os.uname().sysname
            architecture = os.uname().machine
        
        stats = {
            'cpu_percent': psutil.cpu_percent(interval=1),
            'memory_percent': psutil.virtual_memory().percent,
            'disk_percent': psutil.disk_usage(disk_path).percent,
            'uptime_seconds': int(time.time() - psutil.boot_time()),
            'platform': platform_name,
            'architecture': architecture,
            'timestamp': datetime.now().isoformat(),
            'server_name': server_name  # Add server name for grouping
        }
        
        # Add disk I/O write speed tracking
        try:
            disk_io = psutil.disk_io_counters()
            if disk_io:
                # Store current counters for next calculation
                if hasattr(get_server_system_stats, '_last_disk_io'):
                    last_io = get_server_system_stats._last_disk_io
                    # Calculate MB written per second (uses cpu_percent's 1-sec interval)
                    bytes_written = disk_io.write_bytes - last_io.write_bytes
                    stats['disk_write_mb_per_sec'] = round(bytes_written / 1024 / 1024, 2)
                else:
                    stats['disk_write_mb_per_sec'] = 0  # First run baseline
                
                # Store for next call
                get_server_system_stats._last_disk_io = disk_io
        except Exception:
            stats['disk_write_mb_per_sec'] = 0
        
        # Add load average (1, 5, 15 minute) - Unix with /proc/loadavg fallback on Linux
        if hasattr(os, 'getloadavg') or sys.platform.startswith('linux'):
            load_avg = _get_load_average()
            stats['load_average_1m'] = round(load_avg[0], 2)
            stats['load_average_5m'] = round(load_avg[1], 2)
            stats['load_average_15m'] = round(load_avg[2], 2)
        else:
            # Windows: use CPU percent as approximation
            stats['load_average_1m'] = stats['cpu_percent'] / 100.0
            stats['load_average_5m'] = stats['cpu_percent'] / 100.0
            stats['load_average_15m'] = stats['cpu_percent'] / 100.0
        
        # Add CPU temperature if available
        cpu_temp = get_cpu_temperature()
        if cpu_temp is not None:
            stats['cpu_temperature_celsius'] = round(cpu_temp, 1)
        
        # Add network speed (cached) - skip speedtest during startup if requested
        # Backend_server returns zeros on failure for graceful degradation
        network_speed = get_network_speed_cached(skip_if_no_cache=skip_speedtest, return_zeros_on_failure=True)
        stats.update(network_speed)
        
        return stats
    except Exception as e:
        print(f"❌ Error getting server system stats: {e}")
        return {
            'cpu_percent': 0,
            'memory_percent': 0,
            'disk_percent': 0,
            'uptime_seconds': 0,
            'platform': 'unknown',
            'architecture': 'unknown',
            'timestamp': datetime.now().isoformat(),
            'load_average_1m': 0,
            'load_average_5m': 0,
            'load_average_15m': 0
        }
