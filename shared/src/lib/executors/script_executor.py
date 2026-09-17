"""
Unified Script Executor for VirtualPyTest

Complete script execution system that handles:
- Context preparation (device setup, navigation loading)
- Python script execution with real-time output streaming
- Screenshot/video capture and report generation
- Database tracking and cleanup

Usage:
    executor = ScriptExecutor("script_name", "Description")
    context = executor.prepare_context(args)
    result = executor.execute_script_with_context(context)
"""

import sys
import argparse
import time
import os
import signal
import subprocess
import uuid
import glob
import select
import shlex
import threading
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple

# Import required modules for context preparation
from shared.src.lib.utils.app_utils import load_environment_variables
from shared.src.lib.utils.report_generation_utils import generate_and_upload_script_report
from shared.src.lib.database.script_results_db import record_script_execution_start, update_script_execution_result
from shared.src.lib.utils.script_identity_utils import (
    normalize_script_ref,
    resolve_script_identity,
    script_ref_from_path,
)
from .cli_arg_utils import str_to_bool

DEFAULT_TEAM_ID = '7fdeb4bb-3639-4ec3-959f-b54769a219ce'

_VALID_TRIGGER_TYPES = {"api", "mcp", "scheduler", "campaign", "cli", "host", "ai"}


def resolve_virtual_script_libs(root_source: str, fetch_source) -> Dict[str, str]:
    """Recursively resolve a virtual script's `_script_libs` into {name: source}.

    A virtual script may declare `_script_libs = ["a", "b"]` — names of OTHER
    virtual scripts (same team) to make importable. A library may itself declare
    `_script_libs`, so resolution is recursive; names are de-duplicated and cycles
    are guarded (a name already visited is never fetched or walked again).

    `fetch_source(name)` must return the library's source string, or None if the
    named script does not exist (missing libraries are skipped, not fatal —
    keeping resolution best-effort like the other metadata extractors).

    Pure function (no I/O of its own) so it can be unit-tested with a fake
    fetcher. Returns an insertion-ordered dict mapping library name -> source.
    """
    from shared.src.lib.utils.script_target_rules_utils import extract_script_libs

    resolved: Dict[str, str] = {}
    visited: set = set()

    def _walk(source: str) -> None:
        for name in extract_script_libs(source):
            if name in visited:
                continue
            visited.add(name)
            lib_source = fetch_source(name)
            if lib_source is None:
                print(f"[@script_executor] _script_libs: library '{name}' not found — skipped")
                continue
            resolved[name] = lib_source
            _walk(lib_source)

    _walk(root_source or '')
    return resolved


def _normalize_trigger(trigger: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Coerce an incoming trigger dict into {type, caller_ip, caller_user}.

    Falls back to env vars VPT_TRIGGER_TYPE / VPT_CALLER_IP / VPT_CALLER_USER so
    child processes inherit the provenance automatically.
    """
    source = trigger if isinstance(trigger, dict) else {}
    raw_type = (source.get("type") or os.getenv("VPT_TRIGGER_TYPE") or "").strip().lower()
    if raw_type not in _VALID_TRIGGER_TYPES:
        raw_type = "host"
    caller_ip = source.get("caller_ip") or os.getenv("VPT_CALLER_IP") or None
    caller_user = source.get("caller_user") or os.getenv("VPT_CALLER_USER") or None
    return {
        "type": raw_type,
        "caller_ip": caller_ip or None,
        "caller_user": caller_user or None,
    }

_VALID_ENVIRONMENTS = {"dev", "test", "prod"}


def _normalize_environment(environment: Optional[str]) -> str:
    """Coerce an incoming environment value to dev/test/prod.

    Falls back to env var VPT_ENVIRONMENT so child processes (e.g. campaign
    children) inherit the parent's environment automatically. Unlike
    trigger.type, an unspecified/invalid value defaults to 'prod' — an
    untagged run is assumed real so it isn't silently excluded from prod
    KPIs/dashboards.
    """
    raw = (environment or os.getenv("VPT_ENVIRONMENT") or "").strip().lower()
    return raw if raw in _VALID_ENVIRONMENTS else "prod"

_running_processes_by_device: Dict[str, Dict[str, Any]] = {}
_running_processes_lock = threading.Lock()


def _register_running_process(device_id: str, process: subprocess.Popen, script_name: str):
    """Track currently running script process for a device.

    The key MUST be the real device_id: abort_running_script() looks the process up by
    the device_id the server holds in the lock. A placeholder key here means the script
    is unkillable — force take-control will silently fail to stop it.
    """
    if not device_id or device_id == 'unknown-device':
        print(
            f"⚠️ [@script_executor] Launching '{script_name}' with device_id={device_id!r} — "
            f"this process will NOT be abortable (check ScriptExecutor was constructed with "
            f"device_id=...)"
        )
        return
    with _running_processes_lock:
        _running_processes_by_device[device_id] = {
            'process': process,
            'script_name': script_name,
            'started_at': time.time(),
        }


def _unregister_running_process(device_id: str, process: subprocess.Popen):
    """Remove tracked process if it matches the registered one."""
    if not device_id:
        return
    with _running_processes_lock:
        current = _running_processes_by_device.get(device_id)
        if current and current.get('process') is process:
            _running_processes_by_device.pop(device_id, None)


def _kill_process_tree(process: subprocess.Popen, timeout: float = 5.0) -> None:
    """Kill a script process and every child it spawned.

    On POSIX the script runs as `bash -c "source venv && python …"`, so process.pid
    is the bash wrapper: signalling that pid alone orphans the python child, which
    keeps driving the device after the abort reports success. The Popen is started
    with start_new_session=True, so the whole tree (bash, python, anything the
    script itself spawned) shares one process group we can kill atomically.
    """
    if os.name == 'nt':
        subprocess.run(
            ['taskkill', '/PID', str(process.pid), '/T', '/F'],
            capture_output=True,
        )
        process.wait(timeout=timeout)
        return

    try:
        pgid = os.getpgid(process.pid)
    except ProcessLookupError:
        pgid = process.pid

    try:
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        return

    try:
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        print(f"[@script_executor] Process group {pgid} did not terminate in time, sending SIGKILL")
        try:
            os.killpg(pgid, signal.SIGKILL)
        except ProcessLookupError:
            return
        process.wait(timeout=timeout)


def _normalize_windows_param_parts(parameters: str) -> List[str]:
    """Split Windows CLI parameters while stripping surrounding quotes from values."""
    if not parameters or not parameters.strip():
        return []

    parts = shlex.split(parameters.strip(), posix=False)
    normalized: List[str] = []
    for part in parts:
        if len(part) >= 2 and part[0] == part[-1] and part[0] in ("'", '"'):
            normalized.append(part[1:-1])
        else:
            normalized.append(part)
    return normalized


def abort_running_script(device_id: str) -> Dict[str, Any]:
    """Abort any running script process for the specified device."""
    if not device_id:
        return {
            'success': False,
            'aborted': False,
            'error': 'device_id is required'
        }

    with _running_processes_lock:
        current = _running_processes_by_device.get(device_id)

    if not current:
        return {
            'success': True,
            'aborted': False,
            'message': f'No running script found for device {device_id}'
        }

    process = current.get('process')
    script_name = current.get('script_name', 'unknown')
    pid = getattr(process, 'pid', None)

    if process is None:
        return {
            'success': True,
            'aborted': False,
            'message': f'No active process found for device {device_id}'
        }

    if process.poll() is not None:
        _unregister_running_process(device_id, process)
        return {
            'success': True,
            'aborted': False,
            'message': f'Process already finished for device {device_id}'
        }

    try:
        print(f"[@script_executor] Aborting running script on {device_id}: {script_name} (pid={pid})")
        _kill_process_tree(process)

        return {
            'success': True,
            'aborted': True,
            'device_id': device_id,
            'script_name': script_name,
            'pid': pid,
            'message': f'Aborted running script {script_name} on {device_id}'
        }
    except Exception as e:
        return {
            'success': False,
            'aborted': False,
            'error': f'Failed to abort script on {device_id}: {str(e)}'
        }
    finally:
        _unregister_running_process(device_id, process)


class ScriptExecutionContext:
    """Context object that holds all execution state"""
    
    def __init__(self, script_name: str):
        self.script_name = script_name
        self.start_time = time.time()
        
        # Infrastructure objects
        self.host = None
        self.team_id = None
        self.selected_device = None
        self.host_only = False
        # When False, initial/final screenshots and the execution video are
        # neither captured nor uploaded to storage (set from ScriptExecutor.capture_artifacts).
        self.capture_artifacts = True
        self.userinterface_name = None  # Legacy name (backward compatibility)
        self.userinterface = None        # NEW: Canonical access (framework parameter)
        
        # Navigation objects
        self.tree_data = None
        self.tree_id = None
        self.nodes = []
        self.edges = []
        self.current_node_id = None  # Track current location for pathfinding
        
        # Execution tracking
        self.step_results = []
        self.screenshot_paths = []
        self.overall_success = False
        self.error_message = ""
        self.script_result_id = None
        
        # Recovery tracking for resilient validation
        self.failed_steps: List[Dict] = []        # Track failed steps
        self.recovery_attempts: int = 0           # Count total recovery attempts
        self.recovered_steps: int = 0             # Count successful recoveries
        
        # Global verification counter to prevent overwriting verification images
        self.global_verification_counter: int = 0
        
        # Custom data for display in final summary
        self.custom_data = {}
        
        # Builder-specific: Runtime variables (cleared after execution)
        self.variables = {}
        
        # Builder-specific: Metadata for DB storage (persisted to script_results.metadata)
        self.metadata = {}
        self.initial_metadata = {}

        # Script identity metadata loaded from test_scripts/script_identity_map.json
        self.script_identity = {}

        # Trigger provenance (who/what kicked off this run)
        # Populated by ScriptExecutor.execute_script() or campaign/scheduler/MCP callers.
        # Shape: {"type": "api|mcp|scheduler|campaign|cli|host", "caller_ip": str|None, "caller_user": str|None}
        self.trigger: Dict[str, Any] = {}
        
        # Stdout capture for log upload
        self.stdout_buffer = []
        
        # Simple sequential step counter
        self.step_counter = 0
        
        # Running log tracking (for frontend overlay)
        self.running_log_path = None
        self.total_steps = 0
        self.planned_steps: List[Dict[str, Any]] = []
        self.estimated_duration_seconds = None

        # Async task id (set by host route via VPT_TASK_ID env var). Enables the
        # script subprocess to push live progress events back through the server's
        # /system Socket.io namespace; absent when the script is run standalone.
        self.task_id = os.environ.get('VPT_TASK_ID') or None
    
    def get_execution_time_ms(self) -> int:
        """Get current execution time in milliseconds"""
        return int((time.time() - self.start_time) * 1000)
    
    @staticmethod
    def _normalize_step_timing(step_data: Dict[str, Any]) -> None:
        """Format step timing into the fields the report expects.

        The report renders `start_time`/`end_time` as `HH:MM:SS` strings and
        `execution_time_ms` as an int, falling back to N/A / 0s when absent.
        Scripts hold raw epoch floats (time.time()), so they may pass those
        directly as `start_time`/`end_time`; this converts them and derives
        `execution_time_ms`. Values already given as strings pass through
        untouched, so callers that pre-format still work.
        """
        start = step_data.get('start_time')
        end = step_data.get('end_time')
        if isinstance(start, (int, float)):
            step_data['start_time'] = time.strftime('%H:%M:%S', time.localtime(start))
        if isinstance(end, (int, float)):
            step_data['end_time'] = time.strftime('%H:%M:%S', time.localtime(end))
        if isinstance(start, (int, float)) and isinstance(end, (int, float)) and 'execution_time_ms' not in step_data:
            step_data['execution_time_ms'] = int(max(0.0, end - start) * 1000)

    def record_step_immediately(self, step_data: Dict[str, Any]) -> int:
        """Record step immediately with simple sequential numbering - returns step number"""
        self.step_counter += 1
        step_data['step_number'] = self.step_counter
        step_data['timestamp'] = time.time()
        self._normalize_step_timing(step_data)
        self.step_results.append(step_data)
        return self.step_counter

    def emit_progress(self, message: Optional[str] = None, step: Optional[Dict[str, Any]] = None) -> None:
        """
        Push a live progress update to the server so the frontend can render
        per-step state. No-op when task_id is unset (script run standalone).
        Network errors are swallowed — progress is best-effort and must never
        affect script outcome.
        """
        if not self.task_id:
            return
        try:
            from shared.src.lib.utils.build_url_utils import buildServerUrl
            import requests as _requests

            step_number = len(self.step_results)
            total = self.total_steps if self.total_steps else None
            progress = (step_number / total * 100.0) if (total and total > 0) else None

            payload: Dict[str, Any] = {
                'task_id': self.task_id,
                'step_number': step_number,
                'total_steps': total,
            }
            if progress is not None:
                payload['progress'] = progress
            if message:
                payload['message'] = message
            if step:
                payload['step'] = step

            _requests.post(
                buildServerUrl('server/script/progress'),
                json=payload,
                timeout=2,
            )
        except Exception:
            # Best-effort — never let progress emission break the script.
            pass
    
    def add_screenshot(self, screenshot_path: str):
        """Store screenshot path - auto-copy to cold if in hot storage"""
        if screenshot_path:
            # Auto-copy from hot to cold if needed (makes images survive 1 hour)
            if not screenshot_path.startswith('https://'):
                from shared.src.lib.utils.build_url_utils import convert_hot_to_cold_path, is_hot_storage_path
                if is_hot_storage_path(screenshot_path):
                    import shutil
                    cold_path = convert_hot_to_cold_path(screenshot_path)
                    if not os.path.exists(cold_path):
                        os.makedirs(os.path.dirname(cold_path), mode=0o777, exist_ok=True)
                        shutil.copy2(screenshot_path, cold_path)
                    screenshot_path = cold_path
            
            screenshot_name = os.path.basename(screenshot_path)
            print(f"📸 [Context] add_screenshot called: {screenshot_name} (total: {len(self.screenshot_paths)+1})")
            
            self.screenshot_paths.append(screenshot_path)
    
    def upload_screenshots_to_r2(self) -> Dict[str, str]:
        """
        Batch upload all local screenshots to R2 at script end.
        
        Returns:
            Dict mapping local paths to R2 URLs for report generation
        """
        url_mapping = {}  # Map local_path -> r2_url
        
        if not self.screenshot_paths:
            return url_mapping
        
        print(f"📤 [Context] Batch uploading {len(self.screenshot_paths)} screenshots to R2...")
        
        try:
            from shared.src.lib.utils.cloudflare_utils import get_cloudflare_utils
            uploader = get_cloudflare_utils()
            if self.selected_device and getattr(self.selected_device, 'device_id', None):
                device_id = self.selected_device.device_id
            elif self.host and getattr(self.host, 'host_name', None):
                device_id = f"host-{self.host.host_name}"
            else:
                device_id = 'host-unknown'
            
            # Store original paths for mapping
            original_paths = self.screenshot_paths.copy()
            
            # Separate already-uploaded URLs and local files
            already_uploaded = []
            file_mappings = []
            path_to_indices = {}  # Track ALL original indices for each file (handles duplicates)

            for idx, path in enumerate(self.screenshot_paths):
                # Skip None paths - keep as None in final result
                if not path:
                    print(f"⚠️ [Context] Skipping None screenshot at index {idx}")
                    already_uploaded.append((idx, None))  # Track the None
                    continue

                # Already R2 URL - keep as-is
                if path.startswith('https://'):
                    already_uploaded.append((idx, path))
                    continue

                # Local path - check if exists
                if not os.path.exists(path):
                    print(f"⚠️ [Context] Screenshot not found: {path}")
                    already_uploaded.append((idx, path))  # Keep original path (even if missing)
                    continue

                # Track all indices for this path (initial + final state may use same file)
                if path not in path_to_indices:
                    path_to_indices[path] = []
                    # Only add to upload batch once per unique path
                    filename = os.path.basename(path)
                    remote_path = f"script-screenshots/{device_id}/{filename}"
                    file_mappings.append({
                        'local_path': path,
                        'remote_path': remote_path
                    })
                path_to_indices[path].append(idx)
            
            # Upload all files at once with signed URLs for report assets
            if file_mappings:
                upload_result = uploader.upload_files(file_mappings, for_report_assets=True)
                
                # Build updated paths list maintaining original order
                updated_paths = [None] * len(self.screenshot_paths)
                
                # Place already uploaded URLs back
                for idx, url in already_uploaded:
                    updated_paths[idx] = url
                
                # Place successfully uploaded files and delete local copies
                for uploaded_file in upload_result['uploaded_files']:
                    # Set URL for ALL indices that referenced this path (e.g. initial + final state)
                    for original_idx in path_to_indices[uploaded_file['local_path']]:
                        updated_paths[original_idx] = uploaded_file['url']
                    # Build mapping: local -> R2 URL
                    url_mapping[uploaded_file['local_path']] = uploaded_file['url']

                    # Delete local file from cold storage after successful upload
                    local_path = uploaded_file['local_path']
                    try:
                        if os.path.exists(local_path):
                            os.remove(local_path)
                            print(f"🗑️  [Context] Deleted local file after upload: {os.path.basename(local_path)}")
                    except Exception as e:
                        print(f"⚠️ [Context] Failed to delete local file {os.path.basename(local_path)}: {e}")

                # Place failed uploads (keep original path)
                for failed_file in upload_result['failed_uploads']:
                    for original_idx in path_to_indices[failed_file['local_path']]:
                        updated_paths[original_idx] = failed_file['local_path']
                    filename = os.path.basename(failed_file['local_path'])
                    print(f"⚠️ [Context] Upload failed for {filename}: {failed_file['error']}")
                
                self.screenshot_paths = updated_paths
                uploaded_n = upload_result['uploaded_count']
                total_n = len(file_mappings)
                failed_n = total_n - uploaded_n
                if failed_n == 0:
                    print(f"✅ [Context] Uploaded {uploaded_n}/{total_n} screenshots to R2")
                elif uploaded_n == 0:
                    # Surface the first error so the cause (signing, 413, AccessDenied) lands in the log summary,
                    # not just the per-file warnings above. Report says local paths because every upload failed.
                    first_err = (upload_result['failed_uploads'][0].get('error', 'unknown')
                                 if upload_result.get('failed_uploads') else 'unknown')
                    print(f"❌ [Context] Uploaded 0/{total_n} screenshots to R2 — ALL FAILED. First error: {first_err}")
                else:
                    first_err = (upload_result['failed_uploads'][0].get('error', 'unknown')
                                 if upload_result.get('failed_uploads') else 'unknown')
                    print(f"⚠️ [Context] Uploaded {uploaded_n}/{total_n} screenshots to R2 — {failed_n} failed. First error: {first_err}")
                print(f"📋 [Context] Built mapping with {len(url_mapping)} local->R2 URL pairs")
            else:
                print(f"✅ [Context] All {len(already_uploaded)} screenshots already uploaded")
            
            return url_mapping
            
        except Exception as e:
            print(f"❌ [Context] Batch upload error: {e}")
            import traceback
            traceback.print_exc()
            return url_mapping  # Return empty mapping on error
    
    def start_stdout_capture(self):
        """Start capturing stdout for log upload"""
        import sys
        import io
        
        # Store original stdout
        self.original_stdout = sys.stdout
        
        # Create a custom stdout that captures and forwards
        class StdoutCapture:
            def __init__(self, original_stdout, buffer):
                self.original_stdout = original_stdout
                self.buffer = buffer
            
            def write(self, text):
                # Write to original stdout (so output still shows)
                self.original_stdout.write(text)
                # Capture in buffer for log upload
                self.buffer.append(text)
                return len(text)
            
            def flush(self):
                self.original_stdout.flush()
            
            def __getattr__(self, name):
                # Forward other attributes to original stdout
                return getattr(self.original_stdout, name)
        
        # Replace stdout with capturing version
        sys.stdout = StdoutCapture(self.original_stdout, self.stdout_buffer)
    
    def stop_stdout_capture(self):
        """Stop capturing stdout and restore original"""
        import sys
        if hasattr(self, 'original_stdout') and self.original_stdout:
            sys.stdout = self.original_stdout
            self.original_stdout = None
    
    def get_captured_stdout(self) -> str:
        """Get captured stdout as string"""
        return ''.join(self.stdout_buffer)
    
    def set_running_log_path(self, capture_folder: str):
        """Set the running log path for this execution"""
        from shared.src.lib.utils.storage_path_utils import get_running_log_path
        self.running_log_path = get_running_log_path(capture_folder)
    
    def set_planned_steps(self, steps: List[Dict[str, Any]]):
        """Store planned steps for display (call at script start)"""
        self.planned_steps = steps
        self.total_steps = len(steps)
    
    def write_running_log(self):
        """Write current execution state to running.log for frontend overlay - uses existing step_results"""
        if not self.running_log_path:
            return
        
        try:
            import json
            from datetime import datetime, timezone
            
            # Get current step number
            current_step_number = self.step_counter
            total_steps = self.total_steps if self.total_steps > 0 else len(self.step_results)
            
            # Build log data
            log_data = {
                "script_name": self.script_name,
                "total_steps": total_steps,
                "current_step_number": current_step_number,
                "start_time": datetime.fromtimestamp(self.start_time, tz=timezone.utc).isoformat(),
            }
            
            # Helper to extract step description from step_result
            def get_step_description(step):
                """Extract human-readable description from step_result"""
                # Try message first (navigation steps have this)
                if step.get('message'):
                    return step['message']
                # Try from_node -> to_node for navigation
                if step.get('from_node') and step.get('to_node'):
                    return f"{step['from_node']} → {step['to_node']}"
                # Try action_name
                if step.get('action_name'):
                    return step['action_name']
                # Fallback
                return step.get('step_category', 'Unknown step')
            
            def get_step_command(step):
                """Extract command/type from step_result"""
                # Try action_name first
                if step.get('action_name'):
                    return step['action_name']
                # Try step_category
                if step.get('step_category'):
                    return step['step_category']
                # Fallback
                return 'unknown'
            
            # Add all completed steps (for scrollable timeline) - user can scroll through all
            all_completed_steps = []
            if len(self.step_results) >= 2:
                # Get ALL completed steps (excluding current step which is the last one)
                for step in self.step_results[:-1]:  # All except the last (current) step
                    all_completed_steps.append({
                        "step_number": step.get('step_number'),
                        "description": get_step_description(step),
                        "command": get_step_command(step),
                        "status": "completed",
                        "actions": step.get('actions', []),
                        "verifications": step.get('verifications', []),
                    })
                log_data["completed_steps"] = all_completed_steps
            
            # LEGACY: Keep previous_step for backward compatibility
            if len(self.step_results) >= 2:
                prev_step = self.step_results[-2]
                log_data["previous_step"] = {
                    "step_number": prev_step.get('step_number'),
                    "description": get_step_description(prev_step),
                    "command": get_step_command(prev_step),
                    "status": "completed",
                    "actions": prev_step.get('actions', []),
                    "verifications": prev_step.get('verifications', []),
                }
            
            # Add current step (from step_results - last recorded step)
            if len(self.step_results) >= 1:
                current_step = self.step_results[-1]
                
                # Extract actions and verifications directly from step_result
                # Note: step_results store 'actions' and 'verifications' at the top level
                actions = current_step.get('actions', [])
                verifications = current_step.get('verifications', [])
                
                # Also check if there are retry_actions or failure_actions
                retry_actions = current_step.get('retry_actions', [])
                failure_actions = current_step.get('failure_actions', [])
                
                log_data["current_step"] = {
                    "step_number": current_step.get('step_number'),
                    "description": get_step_description(current_step),
                    "command": get_step_command(current_step),
                    "status": "current",
                    "actions": actions,
                    "verifications": verifications,
                    "retry_actions": retry_actions if retry_actions else None,
                    "failure_actions": failure_actions if failure_actions else None,
                    # Set progress to show completed count (e.g., "3/3" for all done)
                    "current_action_index": len(actions),  # All actions completed
                    "current_verification_index": len(verifications),  # All verifications completed
                }
            
            # Calculate estimated end time based on average step duration
            if len(self.step_results) >= 2:
                # Calculate average duration per step (execution_time_ms converted to seconds)
                total_duration = 0
                step_count = 0
                for step in self.step_results:
                    # Check both 'execution_time_ms' and 'duration' for compatibility
                    if step.get('execution_time_ms') is not None:
                        total_duration += step['execution_time_ms'] / 1000.0  # Convert ms to seconds
                        step_count += 1
                    elif step.get('duration') is not None:
                        total_duration += step['duration']
                        step_count += 1
                
                if step_count > 0 and total_steps > 0:
                    avg_duration = total_duration / step_count
                    remaining_steps = max(0, total_steps - current_step_number)
                    estimated_remaining = remaining_steps * avg_duration
                    estimated_end = datetime.fromtimestamp(time.time() + estimated_remaining, tz=timezone.utc).isoformat()
                    log_data["estimated_end"] = estimated_end
                    print(f"[@script_executor] Estimated end time: avg_duration={avg_duration:.1f}s, remaining_steps={remaining_steps}, estimated_remaining={estimated_remaining:.1f}s")
            
            # Fallback to historical average from deployment_scheduler
            if "estimated_end" not in log_data and self.estimated_duration_seconds:
                elapsed = time.time() - self.start_time
                remaining = max(0, self.estimated_duration_seconds - elapsed)
                estimated_end = datetime.fromtimestamp(time.time() + remaining, tz=timezone.utc).isoformat()
                log_data["estimated_end"] = estimated_end
                print(f"[@script_executor] Using historical average: total={self.estimated_duration_seconds:.1f}s, elapsed={elapsed:.1f}s, remaining={remaining:.1f}s")
            
            # Write atomically (write to temp file, then move)
            temp_path = self.running_log_path + '.tmp'
            with open(temp_path, 'w') as f:
                json.dump(log_data, f, indent=2)
            os.replace(temp_path, self.running_log_path)
            print(f"[@script_executor] Wrote running log: {self.running_log_path} (step {current_step_number}/{total_steps})")
            
        except Exception as e:
            # Log error but don't break script execution
            print(f"[@script_executor] ERROR writing running log to {self.running_log_path}: {e}")
            import traceback
            traceback.print_exc()
    
    def record_step_dict(self, step_dict: dict):
        """Record a step using dict format (backward compatible with existing reporting)"""
        # Add step number
        step_dict['step_number'] = len(self.step_results) + 1
        
        # Add to step_results (existing reporting expects this)
        self.step_results.append(step_dict)
        
        # Add screenshots to context if present
        screenshots = step_dict.get('screenshots', [])
        for screenshot in screenshots:
            if screenshot:
                self.add_screenshot(screenshot)


class ScriptExecutor:
    """
    Unified script executor that handles:
    - Context preparation (device setup, navigation loading)
    - High-level navigation with automatic step recording
    - Script execution with real-time output streaming
    - AI test case redirection
    - Report generation integration
    """
    
    def __init__(self, script_name: str = None, description: str = "", host_name: str = None, device_id: str = None, device_model: str = None, default_device: str = "host", capture_artifacts: bool = True):
        """Initialize script executor - supports both context preparation and direct execution modes"""
        # For context preparation mode (test scripts)
        self.script_name = script_name or "unknown-script"
        self.description = description
        self.default_device = default_device
        # When False, no initial/final screenshot or execution video is captured/uploaded.
        self.capture_artifacts = capture_artifacts
        
        # For direct execution mode (API routes)
        self.host_name = host_name or "unknown-host"
        self.device_id = device_id or "unknown-device"
        self.device_model = device_model or "unknown-model"
        self.current_team_id = None
    
    def set_team_id(self, team_id: str):
        """Set team_id for script execution"""
        self.current_team_id = team_id
    
    def execute_script(self, script_name: str, parameters: str = "", estimated_duration_seconds: float = None, trigger: Optional[Dict[str, Any]] = None, environment: Optional[str] = None, task_id: Optional[str] = None, script_identity_override: Optional[Dict[str, Any]] = None, versions: Optional[Dict[str, Any]] = None, device_info: Optional[Dict[str, Any]] = None, virtual_script_id: Optional[str] = None, team_id: Optional[str] = None) -> Dict[str, Any]:
        """Execute a script with parameters and real-time output streaming.

        script_identity_override: optional {'prefix': str, 'display_name': str} supplied
        by the caller (frontend/server) — propagated to the child via env vars so
        resolve_script_identity() inside the script can attach them to metadata
        without needing test_scripts/script_identity_map.json on the host.

        versions: optional {'server': str, 'frontend': str} supplied by the server
        route — the server reads its own VERSION.txt and the frontend forwards its
        build-time version. The host version is read locally (metadata.code_version).
        Forwarded to the child via env vars so it lands in the run metadata.
        """
        start_time = time.time()

        # Store estimated duration for use in setup_execution_context
        self.estimated_duration_seconds = estimated_duration_seconds

        # Normalize trigger provenance (type / caller_ip / caller_user)
        self.current_trigger = _normalize_trigger(trigger)

        # Normalize execution environment (dev/test/prod), default prod
        self.current_environment = _normalize_environment(environment)

        # Server/frontend versions forwarded by the caller (host version is read
        # locally). Only the two the host can't see itself are carried in.
        self.current_versions = versions if isinstance(versions, dict) else {}

        # Async task id from caller route (used by script subprocess to emit live progress)
        self.current_task_id = task_id

        # Identity override (prefix / display_name) forwarded as env vars to the child
        self.current_script_identity_override = script_identity_override or {}

        # Manually-provided device info (per-device, from the run UI) — carried to
        # the child as VPT_DEVICE_INFO and merged into metadata.info.
        self.current_device_info = device_info if isinstance(device_info, dict) else None
        
        # Check if this is an AI test case - redirect to ai_testcase_executor.py
        # IMPORTANT: Exclude the executor script itself to prevent infinite recursion
        if script_name.startswith("ai_testcase_") and script_name != "ai_testcase_executor":
            print(f"[@script_executor] AI test case detected: {script_name}")
            
            # Execute via ai_testcase_executor.py with SAME parameters as normal scripts
            actual_script = "ai_testcase_executor"
            
            print(f"[@script_executor] Redirecting to: {actual_script} with params: {parameters}")
            
            # Pass the original AI script name via environment so executor can find the test case
            original_env = os.environ.copy()
            os.environ['AI_SCRIPT_NAME'] = script_name
            
            # Set team_id if available in parameters (passed from route)
            if hasattr(self, 'current_team_id') and self.current_team_id:
                os.environ['TEAM_ID'] = self.current_team_id
            
            try:
                # DIRECT EXECUTION: Execute the actual script directly without recursive call
                actual_script_path = self._get_script_path(actual_script)
                
                # Execute directly using the same subprocess logic as normal scripts
                result = self._execute_script_subprocess(actual_script_path, parameters, script_name, start_time)
                
                return result
                
            finally:
                # Restore original environment
                os.environ.clear()
                os.environ.update(original_env)
        
        try:
            # Virtual script: source lives in the DB, not on disk. Materialize it
            # to a temp file in test_scripts/ and run the SAME subprocess pipeline,
            # then always clean it up. No rsync deploy needed for new/edited scripts.
            if virtual_script_id:
                resolved_team_id = team_id or getattr(self, 'current_team_id', None) or DEFAULT_TEAM_ID
                script_path, vslib_dir, _vs_cleanup = self._materialize_virtual_script(
                    virtual_script_id, resolved_team_id
                )
                try:
                    result = self._execute_script_subprocess(
                        script_path, parameters, script_name, start_time,
                        vslib_dir=vslib_dir, is_virtual=True,
                    )
                finally:
                    _vs_cleanup()
                return result

            script_path = self._get_script_path(script_name)

            # Execute normal script
            result = self._execute_script_subprocess(script_path, parameters, script_name, start_time)

            return result

        except Exception as e:
            total_execution_time = int((time.time() - start_time) * 1000)
            print(f"[@script_executor] ERROR: {str(e)}")
            
            return {
                'success': False,
                'stdout': '',
                'stderr': str(e),
                'exit_code': 1,
                'script_name': script_name,
                'device_id': self.device_id,
                'parameters': parameters,
                'execution_time_ms': total_execution_time,
                'report_url': ""
            }
    
    def get_device_info_for_report(self) -> Dict[str, Any]:
        """Get device information for report generation"""
        return {
            'device_name': self.device_id,  # Use device_id as name if no device object
            'device_model': self.device_model,
            'device_id': self.device_id
        }
    
    def get_host_info_for_report(self) -> Dict[str, Any]:
        """Get host information for report generation"""
        return {
            'host_name': self.host_name
        }
    
    # Private methods
    
    def _get_script_path(self, script_name: str) -> str:
        """Get full path to a script file in test_scripts or test_campaign."""
        base_dir, relative_name = self._resolve_script_base_and_relative(script_name)
        base_dir_abs = os.path.abspath(base_dir)

        # Handle script names that already have .py extension
        if relative_name.endswith('.py'):
            script_path = os.path.join(base_dir_abs, relative_name)
        else:
            script_path = os.path.join(base_dir_abs, f'{relative_name}.py')

        script_path = os.path.abspath(script_path)
        if not script_path.startswith(f'{base_dir_abs}{os.sep}') and script_path != base_dir_abs:
            raise ValueError(f'Invalid script path: {script_name}')

        if not os.path.exists(script_path):
            raise ValueError(f'Script not found: {script_path}')
        
        return script_path

    def _materialize_virtual_script(self, virtual_script_id: str, team_id: str = DEFAULT_TEAM_ID):
        """Fetch a DB-stored virtual script's source, write it to a temp .py file
        in the test_scripts/ root, materialize any declared shared libraries, and
        return (path, vslib_dir, cleanup_fn).

        Placement rules for the entry script:
          - test_scripts/ ROOT (not a subdir) so a script's own
            `dirname(dirname(__file__))` still resolves to project_root.
          - filename dot-prefixed ('.vs_<uuid>.py') so list_available_scripts()
            skips it (discovery excludes paths starting with '.').
          - uuid suffix so concurrent runs on the same host never collide.

        Shared libraries (`_script_libs`):
          - The entry script (and, recursively, each library) may declare
            `_script_libs = ["name_a", ...]` — names of OTHER virtual scripts in
            the same team to make importable.
          - Each resolved library is written to a fresh temp dir
            `test_scripts/.vslib_<uuid>/<name>.py` (dot-prefixed dir so discovery
            still skips it). That dir is placed on the subprocess PYTHONPATH so
            the entry script can `import name_a`.
          - vslib_dir is None when the script declares no libraries.
        """
        from shared.src.lib.database.virtual_scripts_db import (
            get_virtual_script,
            get_virtual_script_by_name,
        )
        row = get_virtual_script(virtual_script_id, team_id)
        if not row:
            raise ValueError(f'Virtual script not found: {virtual_script_id}')

        source = row.get('source') or ''
        scripts_dir = self._get_scripts_directory()
        os.makedirs(scripts_dir, exist_ok=True)
        path = os.path.join(scripts_dir, f'.vs_{uuid.uuid4().hex}.py')
        with open(path, 'w', encoding='utf-8') as handle:
            handle.write(source)
        print(f"[@script_executor] Materialized virtual script {virtual_script_id} "
              f"({row.get('name')}) -> {path}")

        # Resolve + materialize shared libraries (recursive, deduped, cycle-safe).
        vslib_dir = None
        entry_name = row.get('name')
        # Resolve libraries in the SAME environment as the entry script (a name has
        # up to 3 rows — dev/test/prod), falling back to the canonical dev row so a
        # library that was never promoted still resolves. Keeps a prod run pinned to
        # prod libs and a dev run to dev libs.
        entry_env = row.get('environment') or 'dev'

        def _fetch_lib(name: str) -> Optional[str]:
            # Never let a library shadow/re-import the entry script itself.
            if name == entry_name:
                return None
            lib_row = get_virtual_script_by_name(name, team_id, environment=entry_env)
            if not lib_row and entry_env != 'dev':
                lib_row = get_virtual_script_by_name(name, team_id, environment='dev')
            return (lib_row or {}).get('source') if lib_row else None

        libs = resolve_virtual_script_libs(source, _fetch_lib)
        if libs:
            vslib_dir = os.path.join(scripts_dir, f'.vslib_{uuid.uuid4().hex}')
            os.makedirs(vslib_dir, exist_ok=True)
            for name, lib_source in libs.items():
                lib_path = os.path.join(vslib_dir, f'{name}.py')
                with open(lib_path, 'w', encoding='utf-8') as handle:
                    handle.write(lib_source or '')
            print(f"[@script_executor] Materialized {len(libs)} shared "
                  f"lib(s) {list(libs.keys())} -> {vslib_dir}")

        def _cleanup():
            try:
                os.remove(path)
                print(f"[@script_executor] Removed temp virtual script {path}")
            except OSError:
                pass
            if vslib_dir:
                import shutil
                try:
                    shutil.rmtree(vslib_dir, ignore_errors=True)
                    print(f"[@script_executor] Removed temp vslib dir {vslib_dir}")
                except OSError:
                    pass

        return path, vslib_dir, _cleanup

    def _resolve_script_base_and_relative(self, script_name: str) -> Tuple[str, str]:
        """Resolve script name to a base directory and relative script path."""
        project_root = self._get_project_root()
        normalized_name = (script_name or '').replace('\\', '/').lstrip('/')

        if normalized_name.startswith('test_campaign/'):
            base_dir = os.path.join(project_root, 'test_campaign')
            relative_name = normalized_name[len('test_campaign/'):]
        elif normalized_name.startswith('test_scripts/'):
            base_dir = os.path.join(project_root, 'test_scripts')
            relative_name = normalized_name[len('test_scripts/'):]
        else:
            base_dir = os.path.join(project_root, 'test_scripts')
            relative_name = normalized_name

        return base_dir, relative_name
    
    def _get_scripts_directory(self) -> str:
        """Get default scripts directory path (test_scripts)."""
        return os.path.join(self._get_project_root(), 'test_scripts')

    def _get_project_root(self) -> str:
        """Get project root from current file location."""
        current_dir = os.path.dirname(os.path.abspath(__file__))  # /shared/src/lib/executors
        lib_dir = os.path.dirname(current_dir)                    # /shared/src/lib
        src_dir = os.path.dirname(lib_dir)                        # /shared/src
        shared_dir = os.path.dirname(src_dir)                     # /shared
        return os.path.dirname(shared_dir)                        # /virtualpytest
    
    def _execute_script_subprocess(self, script_path: str, parameters: str, script_name: str, start_time: float, vslib_dir: Optional[str] = None, is_virtual: bool = False) -> Dict[str, Any]:
        """Execute script using subprocess with real-time output streaming.

        vslib_dir / is_virtual: only set for VIRTUAL-script runs. When is_virtual
        is True the child's PYTHONPATH gets project_root prepended (so a
        materialized script at test_scripts/ root can `from shared...` regardless
        of its own path math) plus vslib_dir (so it can `import <lib_name>` for
        each declared `_script_libs` entry). Disk-script runs pass neither, so
        their environment is byte-for-byte unchanged.
        """
        # Use PROJECT_ROOT environment variable or detect from current script location
        project_root = os.getenv('PROJECT_ROOT')
        if not project_root:
            # Auto-detect project root
            current_dir = os.path.dirname(os.path.abspath(__file__))
            project_root = os.path.abspath(os.path.join(current_dir, '..', '..', '..', '..'))
        
        import platform
        is_windows = platform.system() == 'Windows'
        
        # Build command with parameters - platform aware
        if is_windows:
            venv_python = os.path.join(project_root, 'venv', 'Scripts', 'python.exe')
            python_exe = venv_python if os.path.exists(venv_python) else sys.executable
            
            param_parts = _normalize_windows_param_parts(parameters)
            command_array = [python_exe, script_path] + param_parts
            print(f"[@script_executor] Using python: {python_exe}")
        else:
            venv_activate = os.path.join(project_root, 'venv', 'bin', 'activate')
            
            # Auto-detect: Use venv if exists (Raspberry Pi), otherwise use system Python (Docker)
            if os.path.exists(venv_activate):
                base_command = f"source {venv_activate} && python {script_path}"
                print(f"[@script_executor] Using venv: {venv_activate}")
            else:
                base_command = f"python {script_path}"
                print(f"[@script_executor] No venv found, using system Python (Docker mode)")
            
            if parameters and parameters.strip():
                # Split parameters and properly quote each one to handle special characters
                param_parts = shlex.split(parameters.strip())
                quoted_params = ' '.join(shlex.quote(part) for part in param_parts)
                full_command = f"{base_command} {quoted_params}"
            else:
                full_command = base_command
            
            # Final bash command
            # SECURITY: Use shell=False and pass as array to prevent shell injection
            command_array = ['bash', '-c', full_command]
        
        try:
            version_path = os.path.join(project_root, 'VERSION.txt')
            if os.path.exists(version_path):
                with open(version_path, 'r', encoding='utf-8') as vf:
                    version_line = next((ln.strip() for ln in vf if ln.strip()), '')
                if version_line:
                    print(f"[@script_executor] VERSION: {version_line}")
        except Exception as version_read_error:
            print(f"[@script_executor] VERSION: unavailable ({version_read_error})")

        # Resolve trigger once for both logging and child env forwarding.
        current_trigger = getattr(self, 'current_trigger', None) or _normalize_trigger(None)

        trigger_parts = [f"type={current_trigger.get('type') or 'host'}"]
        if current_trigger.get('caller_user'):
            trigger_parts.append(f"user={current_trigger['caller_user']}")
        if current_trigger.get('caller_ip'):
            trigger_parts.append(f"ip={current_trigger['caller_ip']}")
        print(f"[@script_executor] TRIGGER: {' | '.join(trigger_parts)}")

        print(f"[@script_executor] Executing: {' '.join(command_array)}")
        print(f"[@script_executor] === SCRIPT OUTPUT START ===")

        # Pass requested script reference to child process so decorator-based scripts
        # can resolve stable identity (folder-aware) for metadata.
        child_env = os.environ.copy()
        child_env['VPT_SCRIPT_REF'] = normalize_script_ref(script_name)
        child_env['VPT_TRIGGER_TYPE'] = current_trigger.get('type') or 'host'
        if current_trigger.get('caller_ip'):
            child_env['VPT_CALLER_IP'] = str(current_trigger['caller_ip'])
        if current_trigger.get('caller_user'):
            child_env['VPT_CALLER_USER'] = str(current_trigger['caller_user'])
        child_env['VPT_ENVIRONMENT'] = getattr(self, 'current_environment', None) or _normalize_environment(None)
        current_task_id = getattr(self, 'current_task_id', None)
        if current_task_id:
            child_env['VPT_TASK_ID'] = str(current_task_id)
        # Server/frontend versions (host version is read locally by the child).
        current_versions = getattr(self, 'current_versions', None) or {}
        if current_versions.get('server'):
            child_env['VPT_SERVER_VERSION'] = str(current_versions['server'])
        if current_versions.get('frontend'):
            child_env['VPT_FRONTEND_VERSION'] = str(current_versions['frontend'])
        identity_override = getattr(self, 'current_script_identity_override', None) or {}
        if identity_override.get('prefix'):
            child_env['VPT_SCRIPT_PREFIX'] = str(identity_override['prefix'])
        if identity_override.get('display_name'):
            child_env['VPT_SCRIPT_DISPLAY_NAME'] = str(identity_override['display_name'])
        current_device_info = getattr(self, 'current_device_info', None)
        if current_device_info:
            import json
            child_env['VPT_DEVICE_INFO'] = json.dumps(current_device_info)

        # Virtual-script runs only: put project_root (for `from shared...`) and the
        # shared-libs temp dir (for `import <lib_name>`) on the child PYTHONPATH.
        # Gated on is_virtual so disk-script runs keep an unchanged environment.
        if is_virtual:
            existing_pythonpath = child_env.get('PYTHONPATH', '')
            pythonpath_parts = [project_root]
            if vslib_dir:
                pythonpath_parts.append(vslib_dir)
            if existing_pythonpath:
                pythonpath_parts.append(existing_pythonpath)
            child_env['PYTHONPATH'] = os.pathsep.join(pythonpath_parts)
            print(f"[@script_executor] Virtual-script PYTHONPATH: {child_env['PYTHONPATH']}")

        # Use streaming subprocess execution with shell=False for security.
        # cwd=project_root is required so the child can resolve `import shared.src...`
        # via implicit-CWD-on-sys.path. Without it, the child inherits whatever CWD
        # the host process was started in (on Windows that's the Scheduled Task's
        # WorkingDirectory = backend_host\scripts), and `shared` isn't importable.
        process = subprocess.Popen(
            command_array,
            shell=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,  # Merge stderr into stdout for unified streaming
            text=True,
            bufsize=1,  # Line buffered
            universal_newlines=True,
            env=child_env,
            cwd=project_root,
            # Own process group so abort/timeout can kill the whole tree — the bash
            # wrapper alone dying leaves the python child running (see _kill_process_tree).
            start_new_session=(not is_windows),
        )
        _register_running_process(self.device_id, process, script_name)
        
        try:
            # Stream output in real-time with timeout
            stdout_lines = []
            report_url = ""
            logs_url = ""
            timeout_seconds = 3600  # 1 hour timeout
            start_time_for_timeout = time.time()

            def _process_output_line(line: str):
                nonlocal report_url, logs_url
                
                # Extract report URL from cloudflare upload logs (full URL is logged directly)
                if '[@cloudflare_utils:upload_script_report] INFO: Uploaded script report:' in line:
                    try:
                        report_url = line.split('Uploaded script report: ')[1].strip()
                        print(f"📊 [Script] Report URL captured: {report_url}")
                    except Exception as e:
                        print(f"⚠️ [Script] Failed to extract report URL: {e}")
                
                # Extract logs URL from upload logs
                if '[@utils:report_utils:generate_and_upload_script_report] Logs uploaded:' in line:
                    try:
                        logs_url = line.split('Logs uploaded: ')[1].strip()
                        print(f"📝 [Script] Logs URL captured: {logs_url}")
                    except Exception as e:
                        print(f"⚠️ [Script] Failed to extract logs URL: {e}")
                
                # Stream all output with prefix
                print(f"[{script_name}] {line}")
            
            def _check_timeout(poll_result):
                current_time = time.time()
                elapsed_time = current_time - start_time_for_timeout
                if elapsed_time > timeout_seconds:
                    print(f"❌ [Script] Script execution timed out after {timeout_seconds} seconds (elapsed: {elapsed_time:.1f}s)")
                    if poll_result is None:
                        print(f"❌ [Script] Process still running, force killing...")
                        _kill_process_tree(process)
                    else:
                        print(f"❌ [Script] Process already ended but loop didn't exit properly")
                    stdout_lines.append(f"\n[TIMEOUT] Script execution timed out after {timeout_seconds} seconds\n")
                    return True, elapsed_time
                return False, elapsed_time

            if is_windows:
                import queue
                
                output_queue = queue.Queue()
                
                def _reader_thread():
                    try:
                        for line in iter(process.stdout.readline, ''):
                            output_queue.put(line)
                    finally:
                        output_queue.put(None)  # Sentinel
                
                threading.Thread(target=_reader_thread, daemon=True).start()
                
                while True:
                    try:
                        output = output_queue.get(timeout=0.5)
                    except queue.Empty:
                        output = None
                    
                    poll_result = process.poll()
                    
                    if output:
                        line = output.rstrip()
                        _process_output_line(line)
                        stdout_lines.append(output)
                    
                    # Sentinel and process ended
                    if output is None and poll_result is not None:
                        print(f"[@script_executor] LOOP EXIT: Process ended (exit code: {poll_result})")
                        break
                    
                    timed_out, elapsed_time = _check_timeout(poll_result)
                    if timed_out:
                        break
                    
                    # Log progress every 30 seconds to track long-running scripts
                    if int(elapsed_time) % 30 == 0 and int(elapsed_time) > 0:
                        poll_status = poll_result
                        if poll_status is None:
                            print(f"[@script_executor] PROGRESS: Script running for {elapsed_time:.0f}s, process still active")
                        else:
                            print(f"[@script_executor] PROGRESS: Script at {elapsed_time:.0f}s, process ended with code {poll_status} but loop still running")
            else:
                while True:
                    # Use select to wait for output with timeout
                    ready = select.select([process.stdout], [], [], 1.0)[0]  # 1 second timeout
                    
                    poll_result = process.poll()
                    
                    if ready:
                        output = process.stdout.readline()
                        if output:
                            line = output.rstrip()
                            _process_output_line(line)
                            stdout_lines.append(output)
                        elif poll_result is not None:
                            print(f"[@script_executor] LOOP EXIT: Empty output and process ended (exit code: {poll_result})")
                            break
                    elif poll_result is not None:
                        print(f"[@script_executor] LOOP EXIT: No output ready and process ended (exit code: {poll_result})")
                        break
                    
                    timed_out, elapsed_time = _check_timeout(poll_result)
                    if timed_out:
                        break
                    
                    # Log progress every 30 seconds to track long-running scripts
                    if int(elapsed_time) % 30 == 0 and int(elapsed_time) > 0:
                        poll_status = poll_result
                        if poll_status is None:
                            print(f"[@script_executor] PROGRESS: Script running for {elapsed_time:.0f}s, process still active")
                        else:
                            print(f"[@script_executor] PROGRESS: Script at {elapsed_time:.0f}s, process ended with code {poll_status} but loop still running")
            
            # Wait for process completion
            exit_code = process.wait()
            stdout = ''.join(stdout_lines)
            
            print(f"[@script_executor] === SCRIPT OUTPUT END ===")
                   
            total_execution_time = int((time.time() - start_time) * 1000)
            
            print(f"[@script_executor] PREPARE RETURN: Creating return dictionary...")
            print(f"[@script_executor] EXIT_CODE: {exit_code}, EXECUTION_TIME: {total_execution_time}ms")
            print(f"[@script_executor] REPORT_URL: {report_url}")
            
            # Extract SCRIPT_SUCCESS marker from stdout (critical for frontend result accuracy)
            script_success = None

            if stdout and 'SCRIPT_SUCCESS:' in stdout:
                import re
                success_match = re.search(r'SCRIPT_SUCCESS:(true|false)', stdout)
                if success_match:
                    script_success = success_match.group(1) == 'true'
                    print(f"[@script_executor] SCRIPT_SUCCESS extracted: {script_success}")
                else:
                    print(f"[@script_executor] DEBUG: SCRIPT_SUCCESS found but regex didn't match")
            else:
                print(f"[@script_executor] DEBUG: No SCRIPT_SUCCESS marker found in stdout")
                # Print last 500 chars of stdout to see what's there
                if stdout:
                    stdout_tail = stdout[-500:] if len(stdout) > 500 else stdout
                    print(f"[@script_executor] DEBUG: Last 500 chars of stdout: {repr(stdout_tail)}")
                else:
                    print(f"[@script_executor] DEBUG: stdout is empty or None")

            # Extract SCRIPT_RESULT_ID marker so the caller can link the
            # deployment_execution row to its script_results row without
            # relying on (script_name, host_name, time-window) heuristics —
            # those break the moment a script's @script() name diverges
            # from its filename (e.g. device_get_info.py vs @script("get_info")).
            script_result_id = None
            if stdout and 'SCRIPT_RESULT_ID:' in stdout:
                import re
                rid_match = re.search(r'SCRIPT_RESULT_ID:([a-f0-9-]+)', stdout)
                if rid_match:
                    script_result_id = rid_match.group(1)
                    print(f"[@script_executor] SCRIPT_RESULT_ID extracted: {script_result_id}")

            result = {
                'stdout': stdout,
                'stderr': '',  # We merged stderr into stdout
                'exit_code': exit_code,  # Raw exit code (0 = process success)
                'script_name': script_name,
                'device_id': self.device_id,
                'script_path': script_path,
                'parameters': parameters,
                'execution_time_ms': total_execution_time,
                'report_url': report_url,
                'logs_url': logs_url,
                'script_success': script_success,  # Extracted from SCRIPT_SUCCESS marker
                'script_result_id': script_result_id,  # Extracted from SCRIPT_RESULT_ID marker
            }
            
            print(f"[@script_executor] RETURNING: About to return result dictionary")
            return result
        finally:
            _unregister_running_process(self.device_id, process)
            # Remove the per-device running.log so the live "script running" overlay
            # (modal ScriptRunningOverlay) stops showing a finished run. The child
            # writes running.log during execution; previously only the deployment
            # scheduler cleaned it up, so ad-hoc /script/execute runs leaked it and
            # the modal kept rendering the completed run until the 12h stale cutoff.
            try:
                from shared.src.lib.utils.storage_path_utils import (
                    get_capture_folder_from_device_id,
                    get_running_log_path,
                )
                capture_folder = get_capture_folder_from_device_id(self.device_id)
                if capture_folder:
                    running_log_path = get_running_log_path(capture_folder)
                    if os.path.exists(running_log_path):
                        os.remove(running_log_path)
                        print(f"[@script_executor] Removed running log after completion: {running_log_path}")
            except Exception as cleanup_error:
                print(f"[@script_executor] Failed to remove running log after completion: {cleanup_error}")
    
    # =====================================================
    # CONTEXT PREPARATION METHODS (from script_utils.py)
    # =====================================================
    
    def create_argument_parser(self, additional_args: List[Dict] = None) -> argparse.ArgumentParser:
        """Create standard argument parser with optional additional arguments"""
        parser = argparse.ArgumentParser(description=self.description)
        
        # Standard framework arguments (always available)
        parser.add_argument('--device', help=f'Specific device to use (default: {self.default_device})')
        parser.add_argument(
            '--ui-mode',
            '--ui_mode',
            dest='ui_mode',
            choices=['dev', 'prod'],
            default='dev',
            help="Target the dev (default) or published prod version of the userinterface",
        )
        parser.add_argument(
            '--local-debug',
            '--local_debug',
            dest='local_debug',
            nargs='?',
            const=True,
            default=False,
            type=str_to_bool,
            help='Run local Playwright-only debug flow',
        )
        
        # Add additional custom arguments
        if additional_args:
            for arg in additional_args:
                parser.add_argument(arg['name'], **arg['kwargs'])
        
        return parser
    
    def setup_execution_context(self, args, enable_db_tracking: bool = False) -> ScriptExecutionContext:
        """Setup execution context with infrastructure components - NO DEVICE LOCKING"""
        context = ScriptExecutionContext(self.script_name)
        context.capture_artifacts = self.capture_artifacts

        # Make args available to helpers (e.g. _build_start_metadata which reads
        # args.variant). The decorator also assigns context.args after setup
        # finishes, but doing it here keeps both paths consistent.
        context.args = args

        # Store userinterface if script declares it (framework parameter)
        # Accept both 'userinterface' (new) and 'userinterface_name' (legacy) for compatibility
        userinterface_value = getattr(args, 'userinterface', None) or getattr(args, 'userinterface_name', None)
        context.userinterface_name = userinterface_value  # Keep for backward compatibility
        context.userinterface = userinterface_value        # NEW: Canonical access
        
        # Start capturing stdout for log upload
        context.start_stdout_capture()
        
        if context.userinterface:
            print(f"🎯 [{self.script_name}] Starting execution for: {context.userinterface}")
        else:
            print(f"🎯 [{self.script_name}] Starting execution (no UI required)")
        
        try:
            # 1. Load environment variables first
            current_dir = os.path.dirname(os.path.abspath(__file__))  # /shared/src/lib/executors
            lib_dir = os.path.dirname(current_dir)                    # /shared/src/lib
            src_dir = os.path.dirname(lib_dir)                        # /shared/src
            shared_dir = os.path.dirname(src_dir)                     # /shared
            project_root = os.path.dirname(shared_dir)                # /virtualpytest
            backend_host_src = os.path.join(project_root, 'backend_host', 'src')
            
            print(f"🔧 [{self.script_name}] Loading environment variables...")
            load_environment_variables(calling_script_dir=backend_host_src)
            
            # 2. Create host instance with specific device
            device_id_to_use = args.device or self.default_device or "host"
            print(f"🏗️ [{self.script_name}] Creating host instance with device: {device_id_to_use}...")
            try:
                # Import controller manager directly (paths set up by script)
                from backend_host.src.controllers.controller_manager import get_host
                context.host = get_host(device_ids=[device_id_to_use])
                device_count = context.host.get_device_count()
                print(f"✅ [{self.script_name}] Host created with {device_count} devices")
                
                if device_count == 0 and device_id_to_use != "host":
                    print(f"⚠️  [{self.script_name}] No '{device_id_to_use}' device found, falling back to host device...")
                    # Reset singleton so get_host recreates with host device
                    import backend_host.src.controllers.controller_manager as _cm
                    _cm._host_instance = None
                    context.host = get_host(device_ids=["host"])
                    device_count = context.host.get_device_count()
                    print(f"✅ [{self.script_name}] Host (fallback) created with {device_count} devices")
                    device_id_to_use = "host"

                if device_count == 0 and device_id_to_use == "host":
                    print(f"ℹ️ [{self.script_name}] No host device configured, continuing in host-only mode")
                    context.host_only = True
                elif device_count == 0:
                    context.error_message = "No devices configured"
                    print(f"❌ [{self.script_name}] {context.error_message}")
                    return context
                
                # Get team_id from environment (should be loaded by now)
                context.team_id = os.getenv('TEAM_ID', DEFAULT_TEAM_ID)
                
            except Exception as e:
                context.error_message = f"Failed to create host: {str(e)}"
                print(f"❌ [{self.script_name}] {context.error_message}")
                return context
            
            # Resolve stable script identity (folder-aware) plus optional prefix/display overrides
            script_ref_hint = os.getenv('VPT_SCRIPT_REF')
            if not script_ref_hint:
                script_ref_hint = script_ref_from_path(
                    sys.argv[0],
                    scripts_dir=self._get_scripts_directory(),
                )
            if not script_ref_hint:
                script_ref_hint = normalize_script_ref(self.script_name)

            # team scope lets the DB (executable_identity) act as the fallback here,
            # so a host needs no test_scripts/script_identity_map.json of its own.
            context.script_identity = resolve_script_identity(
                script_ref_hint, team_id=context.team_id
            )
            identity_meta = self._build_script_identity_metadata(context)
            if identity_meta:
                print(f"🆔 [{self.script_name}] Identity metadata: {identity_meta}")

            if context.host_only:
                self.device_id = 'host'
                self.device_model = 'host'
                if enable_db_tracking:
                    start_metadata = self._build_start_metadata(context)
                    context.initial_metadata = start_metadata.copy() if isinstance(start_metadata, dict) else {}
                    context.script_result_id = record_script_execution_start(
                        team_id=context.team_id,
                        script_name=self.script_name,
                        script_type=self.script_name,
                        userinterface_name=context.userinterface,
                        host_name=context.host.host_name,
                        device_name='host',
                        environment=getattr(self, 'current_environment', None) or _normalize_environment(None),
                        metadata=start_metadata
                    )
                    if context.script_result_id:
                        print(f"📝 [{self.script_name}] Script execution recorded with ID: {context.script_result_id}")
                        print(f"SCRIPT_RESULT_ID:{context.script_result_id}")

                print(f"✅ [{self.script_name}] Host-only execution context setup completed")
                return context

            # 3. Select device from host instance (device_id_to_use may have been updated by fallback above)
            print(f"🔍 [{self.script_name}] Selecting device: {device_id_to_use}")
            
            available_devices = [d.device_id for d in context.host.get_devices()]
            print(f"📱 [{self.script_name}] Available devices: {available_devices}")
            
            # Setup running log path for automatic progress tracking (use centralized function)
            from shared.src.lib.utils.storage_path_utils import get_capture_folder_from_device_id
            try:
                capture_folder = get_capture_folder_from_device_id(device_id_to_use)
                context.set_running_log_path(capture_folder)
                print(f"📝 [{self.script_name}] Running log enabled: {context.running_log_path}")
            except ValueError as e:
                print(f"⚠️  [{self.script_name}] Could not set running log: {e}")
                # Continue without running log
            
            # Set estimated duration from historical data (if available)
            if hasattr(self, 'estimated_duration_seconds') and self.estimated_duration_seconds:
                context.estimated_duration_seconds = self.estimated_duration_seconds
                print(f"⏱️[{self.script_name}] Estimated duration set: {self.estimated_duration_seconds:.1f}s")
            
            # Try to find the specific device by ID
            context.selected_device = next((d for d in context.host.get_devices() if d.device_id == device_id_to_use), None)
            
            if not context.selected_device:
                # If specific device not found, try to find first non-host device
                devices = [d for d in context.host.get_devices() if d.device_id != 'host']
                if devices:
                    context.selected_device = devices[0]
                    print(f"⚠️ [{self.script_name}] Device {device_id_to_use} not found, using first non-host device: {context.selected_device.device_id}")
                else:
                    # Fall back to any device if no non-host devices available
                    all_devices = context.host.get_devices()
                    if all_devices:
                        context.selected_device = all_devices[0]
                        print(f"⚠️ [{self.script_name}] No non-host devices found, using: {context.selected_device.device_id}")
                    else:
                        context.error_message = "No devices available"
                        print(f"❌ [{self.script_name}] {context.error_message}")
                        return context
            
            print(f"✅ [{self.script_name}] Selected device: {context.selected_device.device_name} ({context.selected_device.device_model})")

            # Block until the remote link is ready before the script body runs.
            # Some remotes (BLE HID) need time to wake/resume an idle link; a
            # first key fired during that window is silently lost or absorbs
            # several seconds of wake latency that skews verification timing.
            # Duck-typed so non-BLE remotes (IR) are unaffected — only a
            # controller exposing wait_for_ready participates.
            try:
                for rc in context.selected_device.get_controllers('remote'):
                    if hasattr(rc, 'wait_for_ready'):
                        print(f"⏳ [{self.script_name}] Waiting for remote link readiness...")
                        rc.wait_for_ready()
            except Exception as e:
                print(f"⚠️  [{self.script_name}] Remote readiness wait skipped: {e}")

            # --- Per-device default userinterface / variant -----------------
            # Precedence: explicit CLI flag > device .env default
            # (DEVICE{i}_USERINTERFACE / _VARIANT) > script-declared
            # _script_args default. argparse can't tell a passed value from the
            # declared default, so "explicit" = the flag literally appears in
            # argv. Variant is coupled to the UI: a device's default variant
            # only applies while the effective userinterface is the device's
            # preferred one (a different UI resets it to base).
            def _flag_in_argv(*names):
                for _tok in sys.argv[1:]:
                    for _n in names:
                        if _tok == _n or _tok.startswith(_n + '='):
                            return True
                return False

            dev = context.selected_device
            pref_ui = getattr(dev, 'preferred_userinterface', None)
            pref_variant = getattr(dev, 'preferred_variant', None)

            script_uses_ui = hasattr(args, 'userinterface') or hasattr(args, 'userinterface_name')
            if (
                script_uses_ui
                and pref_ui
                and not _flag_in_argv('--userinterface', '--userinterface_name', '--userinterface-name')
            ):
                args.userinterface = pref_ui
                if hasattr(args, 'userinterface_name'):
                    args.userinterface_name = pref_ui
                context.userinterface = pref_ui
                context.userinterface_name = pref_ui
                print(f"🧭 [{self.script_name}] userinterface: {pref_ui} (device default from .env)")

            effective_ui = getattr(args, 'userinterface', None) or getattr(args, 'userinterface_name', None)

            # Named-variant resolution (see docs/agent/ENHANCE_VARIANT.md).
            # The navigation resolver AND the validation planner read the active
            # variant from device.navigation_context. This MUST be set for every
            # run — not only DB-tracked ones — otherwise a chosen variant is
            # silently ignored and base data is used.
            nav_context = context.selected_device.navigation_context
            variant_value = getattr(args, 'variant', None)
            if isinstance(variant_value, str):
                variant_value = variant_value.strip() or None
            if hasattr(args, 'variant') and not _flag_in_argv('--variant') and not variant_value and pref_variant:
                if pref_ui and effective_ui == pref_ui:
                    variant_value = pref_variant
                    print(f"🎭 [{self.script_name}] variant: {pref_variant} (device default from .env)")
                else:
                    print(
                        f"🎭 [{self.script_name}] variant: device default "
                        f"'{pref_variant}' skipped (userinterface '{effective_ui}' "
                        f"!= device default '{pref_ui}')"
                    )
            # Canonicalize: --variant may be a single name OR a composition
            # ('active-standby+no-tvshop' or comma-separated). Collapse to the
            # sorted, '+'-joined canonical scope so the cache key and
            # execution_results.variant attribution match regardless of input
            # order. See docs/agent/navigation/VARIANT.md "Composition".
            from shared.src.lib.utils.navigation_graph import canonical_variant_name
            variant_value = canonical_variant_name(variant_value)
            args.variant = variant_value
            nav_context['variant'] = variant_value
            if variant_value:
                print(f"🎯 [{self.script_name}] variant: {variant_value}")
            else:
                print(f"🎯 [{self.script_name}] variant: (none — base only)")

            # Dev/prod userinterface mode rides the same channel as variant:
            # host-side resolvers (navigation_executor, tree_manager) read it
            # from device.navigation_context when mapping name -> root tree.
            ui_mode = getattr(args, 'ui_mode', 'dev') or 'dev'
            context.ui_mode = ui_mode
            nav_context['ui_mode'] = ui_mode
            if ui_mode != 'dev':
                print(f"🏷️ [{self.script_name}] ui-mode: {ui_mode}")

            # 4. Record script execution start in database (if enabled)
            if enable_db_tracking:
                start_metadata = self._build_start_metadata(context)
                context.initial_metadata = start_metadata.copy() if isinstance(start_metadata, dict) else {}
                context.script_result_id = record_script_execution_start(
                    team_id=context.team_id,
                    script_name=self.script_name,
                    script_type=self.script_name,
                    # Always persist the canonical userinterface value captured earlier
                    userinterface_name=context.userinterface,
                    host_name=context.host.host_name,
                    device_name=context.selected_device.device_name,
                    environment=getattr(self, 'current_environment', None) or _normalize_environment(None),
                    metadata=start_metadata
                )
                
                if context.script_result_id:
                    print(f"📝 [{self.script_name}] Script execution recorded with ID: {context.script_result_id}")
                    # Output script result ID in a format that campaign executor can parse
                    print(f"SCRIPT_RESULT_ID:{context.script_result_id}")

                    # CRITICAL: Populate device navigation_context with script tracking info
                    # This enables all executors to record with script dependency
                    nav_context = context.selected_device.navigation_context
                    nav_context['script_id'] = context.script_result_id
                    nav_context['script_name'] = self.script_name
                    nav_context['script_context'] = 'script'
                    # nav_context['variant'] is already populated above
                    # (unconditionally, right after device selection).

                    print(f"📝 [{self.script_name}] Script context populated in device navigation_context")
            
            # 5. Capture initial screenshot (stored in cold, uploaded at script end)
            if context.capture_artifacts:
                from shared.src.lib.utils.device_utils import capture_screenshot
                print(f"📸 [{self.script_name}] Capturing initial state screenshot...")
                capture_screenshot(context.selected_device, context, f"[{self.script_name}]")
            else:
                print(f"📸 [{self.script_name}] Skipping initial state screenshot (capture_artifacts=False)")

            print(f"✅ [{self.script_name}] Execution context setup completed")
            
        except Exception as e:
            context.error_message = f"Setup error: {str(e)}"
            print(f"❌ [{self.script_name}] {context.error_message}")
        
        return context

    def _build_script_identity_metadata(self, context: ScriptExecutionContext) -> Dict[str, Any]:
        """Extract script identity metadata to persist under metadata.script_identity."""
        identity = getattr(context, 'script_identity', None)
        if not isinstance(identity, dict):
            return {}

        payload = {}

        script_ref = identity.get('script_ref')
        if script_ref:
            payload['script_ref'] = script_ref

        prefix = identity.get('prefix')
        if prefix:
            payload['prefix'] = prefix

        display_name = identity.get('display_name')
        if display_name:
            payload['display_name'] = display_name

        return payload

    def _read_code_version(self) -> str:
        """Read current code version from project-root VERSION.txt (the HOST version,
        since the script runs on the host). Strips the `current:` prefix the file
        carries so metadata stores the bare build string (e.g. `debug-2026.05.27-8172`),
        matching how the frontend displays it."""
        try:
            version_path = os.path.join(self._get_project_root(), 'VERSION.txt')
            if not os.path.exists(version_path):
                return ''
            with open(version_path, 'r', encoding='utf-8') as vf:
                line = next((ln.strip() for ln in vf if ln.strip()), '')
            import re
            return re.sub(r'^current\s*:', '', line, flags=re.IGNORECASE)
        except Exception:
            return ''

    def _apply_version_metadata(self, metadata: Dict[str, Any], *, set_default: bool = False) -> None:
        """Attach host/server/frontend code versions to `metadata` in place.

        - host:     read locally from VERSION.txt (also kept as `code_version`).
        - server:   forwarded by the server route via VPT_SERVER_VERSION.
        - frontend: forwarded by the frontend (through the server) via VPT_FRONTEND_VERSION.
        """
        def _put(key: str, value: Optional[str]) -> None:
            if not value:
                return
            if set_default:
                metadata.setdefault(key, value)
            else:
                metadata[key] = value

        host_version = self._read_code_version()
        _put('code_version', host_version)   # existing field — keep for back-compat
        _put('host_version', host_version)
        _put('server_version', os.getenv('VPT_SERVER_VERSION'))
        _put('frontend_version', os.getenv('VPT_FRONTEND_VERSION'))

    def _build_start_metadata(self, context: ScriptExecutionContext) -> Dict[str, Any]:
        """Build metadata payload for record_script_execution_start."""
        if context.selected_device:
            metadata = {
                'device_id': context.selected_device.device_id,
                'device_model': context.selected_device.device_model,
            }
        else:
            metadata = {
                'device_id': self.device_id or 'host',
                'device_model': self.device_model or 'host',
            }

        identity_payload = self._build_script_identity_metadata(context)
        if identity_payload:
            metadata['script_identity'] = identity_payload

        # Host (local), server and frontend code versions.
        self._apply_version_metadata(metadata)

        # Persist the variant the run was launched with (None = base run).
        # Surfaced by validation_diff_report and similar reporting tools.
        args = getattr(context, 'args', None)
        variant_value = getattr(args, 'variant', None) if args is not None else None
        if isinstance(variant_value, str):
            variant_value = variant_value.strip() or None
        metadata['variant'] = variant_value

        trigger = getattr(self, 'current_trigger', None) or _normalize_trigger(None)
        metadata['trigger'] = trigger
        metadata['environment'] = getattr(self, 'current_environment', None) or _normalize_environment(None)
        try:
            context.trigger = trigger
        except Exception:
            pass

        return metadata

    def _read_device_info_override(self) -> Optional[Dict[str, str]]:
        """Manually-provided device info for this run, or None.

        Set per-device in the frontend (Selected Items → Device Info) and carried
        to the script subprocess as the VPT_DEVICE_INFO env var (JSON object).
        Treated as run metadata, not a script argument. Values are coerced to
        strings to match device_get_info's metadata.info shape.
        """
        raw = os.environ.get('VPT_DEVICE_INFO')
        if not raw or not raw.strip():
            return None
        import json
        try:
            obj = json.loads(raw)
        except Exception as e:
            print(f"[{self.script_name}] Invalid VPT_DEVICE_INFO: {e}")
            return None
        if not isinstance(obj, dict):
            return None
        return {str(k): ('' if v is None else str(v)) for k, v in obj.items()} or None

    def _merge_final_metadata(self, context: ScriptExecutionContext) -> Optional[Dict[str, Any]]:
        """
        Merge runtime metadata with system metadata.

        Some scripts assign context.metadata directly; this ensures device fields
        and script_identity are always persisted.
        """
        merged: Dict[str, Any] = {}
        initial_metadata = getattr(context, 'initial_metadata', None)
        if isinstance(initial_metadata, dict):
            merged.update(initial_metadata)

        runtime_metadata = getattr(context, 'metadata', None)

        if isinstance(runtime_metadata, dict):
            merged.update(runtime_metadata)
        elif runtime_metadata not in (None, ''):
            merged['script_metadata_raw'] = runtime_metadata

        # Manually-provided device info (VPT_DEVICE_INFO env). Overlays onto
        # whatever the script put in metadata.info, per-key (provided wins). Lets
        # users supply device info instead of fetching it. device_get_info is
        # excluded — it builds its own info via OCR.
        if self.script_name != 'device_get_info':
            provided_info = self._read_device_info_override()
            if provided_info:
                existing_info = merged.get('info')
                info = dict(existing_info) if isinstance(existing_info, dict) else {}
                info.update(provided_info)
                merged['info'] = info
                merged.setdefault('extraction_method', 'manual')

        if context.selected_device:
            merged.setdefault('device_id', context.selected_device.device_id)
            merged.setdefault('device_model', context.selected_device.device_model)

        identity_payload = self._build_script_identity_metadata(context)
        if identity_payload:
            existing_identity = merged.get('script_identity')
            if isinstance(existing_identity, dict):
                existing_identity.update(identity_payload)
                merged['script_identity'] = existing_identity
            else:
                merged['script_identity'] = identity_payload

        # Host (local), server and frontend code versions — don't clobber values
        # a script set on context.metadata itself.
        self._apply_version_metadata(merged, set_default=True)

        trigger = (
            getattr(self, 'current_trigger', None)
            or getattr(context, 'trigger', None)
            or _normalize_trigger(None)
        )
        if isinstance(trigger, dict) and trigger.get('type'):
            merged.setdefault('trigger', trigger)
            try:
                if not getattr(context, 'trigger', None):
                    context.trigger = trigger
            except Exception:
                pass

        merged = {k: v for k, v in merged.items() if v is not None}
        return merged or None

    def _build_verification_review_markdown(
        self,
        context: ScriptExecutionContext,
        report_result: Optional[Dict[str, Any]],
        execution_time_ms: int,
    ) -> str:
        """Build one markdown review pack for post-execution false-positive analysis."""
        report_url = ''
        logs_url = ''
        report_path = ''
        logs_path = ''
        if isinstance(report_result, dict):
            report_url = report_result.get('report_url') or ''
            logs_url = report_result.get('logs_url') or ''
            report_path = report_result.get('report_path') or ''
            logs_path = report_result.get('logs_path') or ''

        script_identity = self._build_script_identity_metadata(context)
        display_name = script_identity.get('display_name') if script_identity else None
        script_label = display_name or self.script_name
        success_text = 'PASS' if context.overall_success else 'FAIL'

        lines: List[str] = []
        lines.append('# Script Verification Review Pack')
        lines.append('')
        lines.append('## Execution Snapshot')
        lines.append(f'- script_name: `{self.script_name}`')
        lines.append(f'- script_label: `{script_label}`')
        if script_identity.get('script_ref'):
            lines.append(f'- script_ref: `{script_identity["script_ref"]}`')
        lines.append(f'- script_result_id: `{context.script_result_id or "n/a"}`')
        lines.append(f'- status: `{success_text}`')
        lines.append(f'- execution_time_ms: `{execution_time_ms}`')
        code_version = self._read_code_version()
        if code_version:
            lines.append(f'- code_version: `{code_version}`')
        trigger = getattr(self, 'current_trigger', None) or getattr(context, 'trigger', None) or {}
        if isinstance(trigger, dict) and trigger.get('type'):
            trigger_bits = [f"type={trigger.get('type')}"]
            if trigger.get('caller_user'):
                trigger_bits.append(f"user={trigger['caller_user']}")
            if trigger.get('caller_ip'):
                trigger_bits.append(f"ip={trigger['caller_ip']}")
            lines.append(f'- trigger: `{" | ".join(trigger_bits)}`')
        lines.append(f'- host_name: `{getattr(context.host, "host_name", "unknown")}`')
        lines.append(f'- device_id: `{getattr(context.selected_device, "device_id", "unknown")}`')
        lines.append(f'- device_name: `{getattr(context.selected_device, "device_name", "unknown")}`')
        lines.append(f'- device_model: `{getattr(context.selected_device, "device_model", "unknown")}`')
        lines.append('')

        lines.append('## Log Sources')
        lines.append('- Execution report (HTML):')
        lines.append(f'  - URL: {report_url or "n/a"}')
        lines.append(f'  - R2 path: `{report_path or "n/a"}`')
        lines.append('- Raw execution logs:')
        lines.append(f'  - URL: {logs_url or "n/a"}')
        lines.append(f'  - R2 path: `{logs_path or "n/a"}`')
        lines.append('- Script source:')
        lines.append(f'  - URL: {(report_result or {}).get("script_source_url") or "n/a"}')
        lines.append(f'  - R2 path: `{(report_result or {}).get("script_source_path") or "n/a"}`')
        lines.append('- Verification review markdown:')
        lines.append(f'  - URL: {(report_result or {}).get("verification_review_url") or "n/a"}')
        lines.append(f'  - R2 path: `{(report_result or {}).get("verification_review_path") or "n/a"}`')
        lines.append('- UI dump traces (what a missed selector actually searched):')
        lines.append(f'  - URL: {(report_result or {}).get("ui_dumps_url") or "n/a"}')
        lines.append('- Runtime progress log:')
        lines.append(f'  - local path: `{context.running_log_path or "n/a"}`')
        lines.append('- Captured artifacts:')
        lines.append(f'  - screenshot_count: `{len(context.screenshot_paths)}`')
        lines.append(f'  - step_count: `{len(context.step_results)}`')
        lines.append(f'  - has_execution_summary: `{bool(getattr(context, "execution_summary", ""))}`')
        lines.append('')

        lines.append('## How To Verify False Positives')
        lines.append('1. Check if the reported failure matches the final visual state in the HTML report screenshots.')
        lines.append('2. Cross-check the same moment in raw logs and confirm the failure marker appears before/after expected actions.')
        lines.append('3. Confirm action intent versus verification intent: wrong selector/timing is `SCRIPT_ISSUE`; real product break is `VALID_FAIL`.')
        lines.append('4. If the screen shows expected UI while logs say "not found", classify as `BUG` (framework mismatch, not app behavior).')
        lines.append('5. If infrastructure is broken (no signal, disconnected device, black/frozen stream), classify as `SYSTEM_ISSUE`.')
        lines.append('6. If script passed and visual + log evidence agree, classify as `VALID_PASS`.')
        lines.append('7. Record exact evidence lines/frames in `discard_comment` so the next run can learn from the decision.')
        lines.append('')

        if 'youtube_video_check' in (self.script_name or ''):
            lines.append('## YouTube Video Check Focus')
            lines.append('- Validate consent/cookie result against the visible modal state.')
            lines.append('- Confirm ad handling: skip action present/clicked or explicit ad wait branch in logs.')
            lines.append('- Verify playback progression: `currentTime` should advance during monitor window.')
            lines.append('- If playback is advancing and UI is stable but assertion failed, treat as likely script timing issue.')
            lines.append('')

        lines.append('## Suggested Classification Decision')
        lines.append('- Keep (`discard=false`): `VALID_PASS`, `VALID_FAIL`, `BUG`')
        lines.append('- Discard (`discard=true`): `SCRIPT_ISSUE`, `SYSTEM_ISSUE`')
        lines.append('')

        return '\n'.join(lines)

    def _build_final_metadata_with_review(
        self,
        context: ScriptExecutionContext,
        report_result: Optional[Dict[str, Any]],
        execution_time_ms: int,
        verification_review_upload: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Merge runtime metadata and attach verification review artifact references."""
        merged = self._merge_final_metadata(context) or {}
        review_url = ''
        review_path = ''
        if isinstance(verification_review_upload, dict):
            review_url = verification_review_upload.get('url') or ''
            review_path = verification_review_upload.get('path') or ''

        merged['verification_review'] = {
            'version': 1,
            'generated_at': datetime.utcnow().isoformat() + 'Z',
            'report_url': report_result.get('report_url') if isinstance(report_result, dict) else None,
            'logs_url': report_result.get('logs_url') if isinstance(report_result, dict) else None,
            'verification_review_url': review_url or None,
            'verification_review_path': review_path or None,
            'status': 'PASS' if context.overall_success else 'FAIL',
            'execution_time_ms': execution_time_ms,
        }
        if isinstance(report_result, dict):
            script_source_url = report_result.get('script_source_url') or None
            script_source_path = report_result.get('script_source_path') or None
            if script_source_url or script_source_path:
                merged['script_source'] = {
                    'url': script_source_url,
                    'path': script_source_path,
                }
        if review_url:
            merged['verification_review_r2_url'] = review_url
        if review_path:
            merged['verification_review_r2_path'] = review_path
        return merged
    
    def generate_report_for_context(self, context: ScriptExecutionContext, device_info: Dict[str, Any], host_info: Dict[str, Any], userinterface_name: str = "") -> Dict[str, str]:
        """
        Generate and upload report for a context (reusable by script_executor and testcase_executor).
        
        Args:
            context: Script execution context with step results and screenshots
            device_info: Device information dict
            host_info: Host information dict
            userinterface_name: Optional userinterface name
            
        Returns:
            Dict with 'success', 'report_url', 'logs_url', 'report_path', 'logs_path'
        """
        try:
            # Capture execution time BEFORE any additional processing
            actual_execution_time_ms = context.get_execution_time_ms()
            context.baseline_execution_time_ms = actual_execution_time_ms
            
            # Capture test execution video BEFORE report generation (for both scripts and test cases)
            print(f"🎥 [{self.script_name}] Capturing test execution video...")
            try:
                actual_test_duration_seconds = actual_execution_time_ms / 1000.0
                if not context.capture_artifacts:
                    context.test_video_url = ""
                    print(f"ℹ️ [{self.script_name}] Skipping test video capture (capture_artifacts=False)")
                elif context.selected_device:
                    av_controller = context.selected_device._get_controller('av')
                    video_duration = max(10.0, actual_test_duration_seconds)
                    test_video_url = av_controller.take_video_for_report(video_duration, context.start_time)
                    context.test_video_url = test_video_url
                    print(f"✅ [{self.script_name}] Test execution video captured: {test_video_url}")
                else:
                    context.test_video_url = ""
                    print(f"ℹ️ [{self.script_name}] Host-only execution: skipping test video capture")
            except Exception as e:
                print(f"⚠️ [{self.script_name}] Video capture failed: {e}")
                context.test_video_url = ""
            
            # Build the step mosaic BEFORE the batch screenshot upload below: that
            # upload deletes the local "cold" capture files it just sent to R2
            # (cloudflare_utils.upload_files auto_delete_cold=True), so building
            # the mosaic any later finds nothing on disk (BUG found 2026-09-03 on
            # a real vpt-pi1/stb3 run — see report_mosaic.py / report_generation_
            # utils.py). Best-effort: any failure here just skips the mosaic.
            mosaic_local_path = ''
            mosaic_tile_count = 0
            try:
                if context.capture_artifacts and context.step_results:
                    import tempfile
                    from shared.src.lib.utils.report_mosaic import build_step_mosaic
                    with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as mosaic_tmp:
                        candidate_mosaic_path = mosaic_tmp.name
                    mosaic_info = build_step_mosaic(context.step_results, candidate_mosaic_path)
                    if mosaic_info:
                        mosaic_local_path = candidate_mosaic_path
                        mosaic_tile_count = mosaic_info['tiles']
                    elif os.path.exists(candidate_mosaic_path):
                        os.unlink(candidate_mosaic_path)
            except Exception as mosaic_build_error:
                print(f"⚠️ [{self.script_name}] Mosaic build skipped: {mosaic_build_error}")

            # Batch upload all screenshots to R2 BEFORE report generation
            url_mapping = context.upload_screenshots_to_r2()
            context.screenshot_url_mapping = url_mapping

            # Persist the report's key R2 artifacts (signed URLs) into runtime
            # metadata so downstream consumers (e.g. the Device Info page) can
            # show/link them later without re-deriving R2 paths. After the upload
            # above, context.screenshot_paths holds signed URLs in capture order
            # (first = initial state, last = final state); the report uses the
            # same [0]/[-1] convention. Mirrors generate_and_upload_script_report.
            try:
                sp = [p for p in (context.screenshot_paths or []) if isinstance(p, str)]
                artifacts = {
                    'initial_screenshot_url': sp[0] if sp and sp[0].startswith('https://') else None,
                    'final_screenshot_url': sp[-1] if len(sp) > 1 and sp[-1].startswith('https://') else None,
                    'video_url': (getattr(context, 'test_video_url', '') or None),
                }
                artifacts = {k: v for k, v in artifacts.items() if v}
                if artifacts:
                    if not isinstance(getattr(context, 'metadata', None), dict):
                        context.metadata = {}
                    context.metadata['report_artifacts'] = artifacts
            except Exception as artifact_error:
                print(f"⚠️ [{self.script_name}] Failed to record report artifacts: {artifact_error}")

            # Stop stdout capture and get logs
            context.stop_stdout_capture()
            captured_stdout = context.get_captured_stdout()

            # Upload runtime metadata.json BEFORE report generation so the report can link to it
            metadata_url_for_report = ''
            try:
                runtime_metadata_snapshot = self._merge_final_metadata(context) or {}
                if runtime_metadata_snapshot:
                    from shared.src.lib.utils.cloudflare_utils import upload_script_metadata_artifact
                    metadata_upload_result = upload_script_metadata_artifact(
                        metadata=runtime_metadata_snapshot,
                        device_model=device_info.get('device_model', self.device_model or 'host'),
                        script_name=f"{self.script_name}.py",
                        timestamp=datetime.utcnow().strftime('%Y%m%d%H%M%S%f'),
                        script_result_id=context.script_result_id,
                    )
                    if metadata_upload_result.get('success'):
                        metadata_url_for_report = metadata_upload_result.get('url') or ''
                        context.metadata_upload_result = metadata_upload_result
                        print(f"📦 [{self.script_name}] Metadata JSON uploaded: {metadata_url_for_report}")
                    else:
                        print(f"⚠️ [{self.script_name}] Metadata JSON upload failed: {metadata_upload_result.get('error')}")
            except Exception as metadata_upload_error:
                print(f"⚠️ [{self.script_name}] Failed to upload metadata JSON: {metadata_upload_error}")

            # Generate and upload report using device info
            report_result = generate_and_upload_script_report(
                metadata_url=metadata_url_for_report,
                trigger=getattr(self, 'current_trigger', None) or getattr(context, 'trigger', None) or _normalize_trigger(None),
                script_name=f"{self.script_name}.py",
                device_info=device_info,
                host_info=host_info,
                execution_time=actual_execution_time_ms,
                success=context.overall_success,
                step_results=context.step_results,
                screenshot_paths=context.screenshot_paths,
                screenshot_url_mapping=url_mapping,
                error_message=context.error_message,
                userinterface_name=userinterface_name,
                execution_summary=getattr(context, 'execution_summary', ''),
                test_video_url=getattr(context, 'test_video_url', '') or '',
                stdout=captured_stdout,
                script_result_id=context.script_result_id,
                custom_data=context.custom_data,
                zap_detailed_summary=getattr(context, 'zap_detailed_summary', ''),
                edge_results_summary=getattr(context, 'edge_results_summary', ''),
                script_identity=self._build_script_identity_metadata(context),
                mosaic_local_path=mosaic_local_path,
                mosaic_tile_count=mosaic_tile_count,
            )
            
            if report_result.get('success'):
                print(f"📊 [{self.script_name}] Report generated: {report_result.get('report_url')}")
                if report_result.get('logs_url'):
                    print(f"📝 [{self.script_name}] Logs uploaded: {report_result.get('logs_url')}")
            
            return report_result
            
        except Exception as e:
            print(f"⚠️ [{self.script_name}] Error in report generation: {e}")
            import traceback
            traceback.print_exc()
            return {
                'success': False,
                'report_url': '',
                'report_path': '',
                'logs_url': '',
                'logs_path': ''
            }

    def _clear_device_script_context(self, context: ScriptExecutionContext):
        """Remove script tracking fields from the device navigation context."""
        if context.selected_device and hasattr(context.selected_device, 'navigation_context'):
            nav_context = context.selected_device.navigation_context
            if nav_context.get('script_id'):
                nav_context.pop('script_id', None)
                nav_context.pop('script_name', None)
                nav_context.pop('script_context', None)
                print(f"📝 [{self.script_name}] Script context cleaned from device navigation_context")

    def _ensure_device_powered_on(self, context: ScriptExecutionContext) -> None:
        """Global safety net: never leave a device powered off at the end of a run.

        Some tests legitimately power the device off as their last action (e.g. a
        KPI measurement of poweroff→live that fails on the final iteration). Without
        this, the device stays dark until a human notices. So before releasing the
        lock, if the device exposes a power controller and reports itself OFF, switch
        it back on.

        Must run BEFORE _release_device_early — once the lock is released another job
        can take over the device, and we'd no longer own the right to drive it.

        Best-effort: any failure here is logged and swallowed so it can never break
        report generation or the rest of teardown.
        """
        if getattr(context, 'host_only', False) or not context.selected_device:
            return
        try:
            power_controller = context.selected_device._get_controller('power')
            if not power_controller:
                return
            status = power_controller.get_power_status()
            power_state = status.get('power_state') if isinstance(status, dict) else None
            if power_state != 'off':
                # 'on', 'unknown', or unreadable → leave it alone. We only act on a
                # confirmed OFF so we never toggle a device that's already serving.
                return
            print(f"🔌 [{self.script_name}] Device is powered OFF at end of run — switching it back ON")
            if power_controller.power_on():
                print(f"✅ [{self.script_name}] Device powered back ON")
            else:
                print(f"⚠️ [{self.script_name}] power_on() returned False — device may still be off")
        except Exception as e:
            print(f"⚠️ [{self.script_name}] Failed to ensure device powered on: {e}")

    def _release_device_early(self, context: ScriptExecutionContext) -> None:
        """Ask the server to release this device's lock as soon as the script body
        has finished — BEFORE the final screenshot / report video / R2 uploads /
        DB writes run. Those remaining steps either read from the host's continuous
        HLS capture buffer (final screenshot, report video) or are pure I/O, none of
        which require control of the device, so it can be freed for the next
        user/job immediately instead of staying locked through report generation.

        Best-effort and idempotent by design:
        - The server still owns the decision: /script/releaseDevice skips release
          when the script ran under a manual_control umbrella (same guard as
          /script/taskComplete), so a user's Take Control session is never killed.
        - The normal release-on-completion callback runs afterwards and is a no-op
          if already released, so if this signal fails the lock simply releases at
          its previous timing. The end result is identical to before.
        """
        # Host-only runs hold no device lock — nothing to release.
        if getattr(context, 'host_only', False) or not context.selected_device:
            return
        # A campaign holds ONE lock across all of its scripts. Releasing after the
        # first script would let another job grab the device mid-campaign and break
        # the remaining scripts — so the campaign owns release, not the script.
        trigger_type = (getattr(context, 'trigger', None) or {}).get('type') or os.getenv('VPT_TRIGGER_TYPE')
        if trigger_type == 'campaign':
            return
        host_name = getattr(context.host, 'host_name', None) if context.host else None
        device_id = getattr(context.selected_device, 'device_id', None)
        if not host_name or not device_id:
            return
        try:
            from shared.src.lib.utils.build_url_utils import buildServerUrl
            import requests as _requests

            payload: Dict[str, Any] = {'host_name': host_name, 'device_id': device_id}
            if context.task_id:
                payload['task_id'] = context.task_id
            _requests.post(
                buildServerUrl('server/script/releaseDevice'),
                json=payload,
                timeout=3,
            )
            print(f"🔓 [{self.script_name}] Requested early device release for {host_name}:{device_id} (report/video/upload to follow)")
        except Exception as e:
            # Never let release signalling affect the run — falls back to
            # release-on-completion (previous behaviour).
            print(f"⚠️ [{self.script_name}] Early device release signal failed (will release on completion): {e}")

    def _close_web_browser_if_needed(self, context: ScriptExecutionContext) -> None:
        """Close the Playwright browser after a web-based test finishes.

        Web scripts (Facebook/YouTube/Netflix/etc.) reuse a persistent
        Chrome/WebKit process across runs for speed, so nothing closes it by
        default. That's fine for local iteration but leaves a browser window
        open on the host after every automated run. Set
        VPT_KEEP_BROWSER_OPEN=true on the host to opt back into the old
        "leave it open" behaviour (e.g. for debugging or a multi-script
        sequence that wants to keep the browser warm between steps).

        Best-effort: any failure here is logged and swallowed so it can
        never break report generation or the rest of teardown.
        """
        if getattr(context, 'host_only', False) or not context.selected_device:
            return
        if os.getenv('VPT_KEEP_BROWSER_OPEN', '').strip().lower() in ('1', 'true', 'yes'):
            return
        try:
            web_controller = context.selected_device._get_controller('web')
            if not web_controller:
                return
            print(f"🌐 [{self.script_name}] Closing web browser after test execution...")
            # wait=True: the cleanup runs on a daemon controller-loop thread that
            # would otherwise be cut off by this process's imminent sys.exit(0),
            # leaving Chrome running. Block briefly so it actually finishes.
            web_controller.close_browser(wait=True)
        except Exception as e:
            print(f"⚠️ [{self.script_name}] Failed to close web browser: {e}")

    def finalize_execution_context(
        self,
        context: ScriptExecutionContext,
        userinterface_name: str,
        success: Optional[bool] = None,
        error_message: Optional[str] = None,
        print_summary: bool = False,
        generate_report: bool = True,
    ) -> Dict[str, Any]:
        """
        Finalize execution artifacts and database state without exiting the process.

        This is the shared end-of-run path for decorator-based scripts and graph testcases.

        When ``generate_report`` is False (e.g. an ad-hoc QuickTest single-step run) the
        expensive artifact tail is skipped entirely — no report video capture, no
        screenshot/metadata/markdown R2 uploads, no HTML report, no DB write. Device
        lifecycle (power-on + early release) and resource cleanup (stop stdout capture,
        clear device script context) still run so the device is left in a clean state.
        """
        report_result: Dict[str, Any] = {
            'success': False,
            'report_url': '',
            'report_path': '',
            'logs_url': '',
            'logs_path': '',
        }
        verification_review_upload = None

        try:
            if success is not None:
                context.overall_success = success
            if error_message and not context.error_message:
                context.error_message = error_message

            # Global rule: never leave the device powered off. If a test ended with
            # the device off (e.g. a poweroff KPI step), switch it back on while we
            # still hold the lock — must happen before _release_device_early.
            self._ensure_device_powered_on(context)

            # Release the device now: the remaining work (final screenshot, report
            # video, R2 uploads, DB writes) reads from the continuous HLS capture
            # buffer or is pure I/O and does not need control of the device. Freeing
            # it here lets the next user/job take over without waiting for report
            # generation to finish.
            self._release_device_early(context)

            # Web tests leave Chrome/WebKit running by default (persistent,
            # reused process). Close it now unless VPT_KEEP_BROWSER_OPEN=true.
            self._close_web_browser_if_needed(context)

            # Ad-hoc single-step runs: bail out before the artifact tail. The device
            # is already powered-on + released above; the `finally` block below still
            # stops stdout capture and clears the device script context.
            if not generate_report:
                print(f"⚡ [{self.script_name}] Skipping report generation (generate_report=False)")
                return {
                    'success': True,
                    'report_url': '',
                    'report_path': '',
                    'logs_url': '',
                    'logs_path': '',
                    'metadata': self._merge_final_metadata(context),
                    'verification_review_upload': None,
                    'execution_time_ms': getattr(
                        context, 'baseline_execution_time_ms', context.get_execution_time_ms()
                    ),
                }

            if context.capture_artifacts and context.host and context.selected_device:
                print(f"📸 [{self.script_name}] Capturing final state screenshot...")
                from shared.src.lib.utils.device_utils import capture_screenshot_for_script
                screenshot_id = capture_screenshot_for_script(context.selected_device, context, "final_state")
                if screenshot_id:
                    print(f"✅ [{self.script_name}] Final screenshot captured: {screenshot_id}")

            device_info = self.get_device_info_for_report_context(context)
            host_info = self.get_host_info_for_report_context(context)
            report_result = self.generate_report_for_context(context, device_info, host_info, userinterface_name)

            if report_result and report_result.get('success') and report_result.get('report_url'):
                if not hasattr(context, 'custom_data') or context.custom_data is None:
                    context.custom_data = {}
                context.custom_data['report_url'] = report_result['report_url']
                if report_result.get('logs_url'):
                    context.logs_url = report_result['logs_url']

            execution_time_for_db = getattr(context, 'baseline_execution_time_ms', context.get_execution_time_ms())

            try:
                markdown_content = self._build_verification_review_markdown(context, report_result, execution_time_for_db)
                logs_path = report_result.get('logs_path') if isinstance(report_result, dict) else ''
                report_path = report_result.get('report_path') if isinstance(report_result, dict) else ''
                preferred_remote_path = ''
                if logs_path:
                    preferred_remote_path = f"{os.path.dirname(logs_path)}/verification_review.md"
                elif report_path:
                    preferred_remote_path = f"{os.path.dirname(report_path)}/verification_review.md"

                from shared.src.lib.utils.cloudflare_utils import upload_verification_review_markdown
                verification_review_upload = upload_verification_review_markdown(
                    markdown_content=markdown_content,
                    device_model=getattr(context.selected_device, 'device_model', self.device_model or 'host'),
                    script_name=f"{self.script_name}.py",
                    timestamp=datetime.utcnow().strftime('%Y%m%d%H%M%S%f'),
                    script_result_id=context.script_result_id,
                    remote_path=preferred_remote_path or None,
                )
                if verification_review_upload.get('success'):
                    print(f"🧠 [{self.script_name}] Verification review markdown uploaded: {verification_review_upload.get('url')}")
                else:
                    print(f"⚠️ [{self.script_name}] Verification review markdown upload failed: {verification_review_upload.get('error')}")
            except Exception as review_upload_error:
                print(f"⚠️ [{self.script_name}] Failed to upload verification review markdown: {review_upload_error}")

            metadata_to_save = self._build_final_metadata_with_review(
                context,
                report_result,
                execution_time_for_db,
                verification_review_upload=verification_review_upload,
            )

            # Mosaic lives in metadata (no dedicated column): Grafana/notifications
            # can read metadata->>'mosaic_r2_url' without a schema change.
            if isinstance(report_result, dict) and report_result.get('mosaic_url'):
                metadata_to_save = metadata_to_save or {}
                metadata_to_save['mosaic_r2_url'] = report_result.get('mosaic_url') or ''
                metadata_to_save['mosaic_r2_path'] = report_result.get('mosaic_path') or ''

            if metadata_to_save:
                metadata_upload_result = getattr(context, 'metadata_upload_result', None)
                if isinstance(metadata_upload_result, dict) and metadata_upload_result.get('success'):
                    metadata_to_save['metadata_r2_url'] = metadata_upload_result.get('url') or ''
                    metadata_to_save['metadata_r2_path'] = metadata_upload_result.get('path') or ''
                print(f"📦 [{self.script_name}] Including metadata in database update: {list(metadata_to_save.keys())}")

            if context.script_result_id:
                print(f"📝 [{self.script_name}] Recording {'success' if context.overall_success else 'failure'} in database...")
                update_script_execution_result(
                    script_result_id=context.script_result_id,
                    success=context.overall_success,
                    execution_time_ms=execution_time_for_db,
                    html_report_r2_path=report_result.get('report_path') if report_result and report_result.get('success') else None,
                    html_report_r2_url=report_result.get('report_url') if report_result and report_result.get('success') else None,
                    logs_r2_path=report_result.get('logs_path') if report_result and report_result.get('success') else None,
                    logs_r2_url=report_result.get('logs_url') if report_result and report_result.get('success') else None,
                    error_msg=None if context.overall_success else (context.error_message or 'Script execution failed'),
                    metadata=metadata_to_save,
                )

            return {
                'success': bool(report_result and report_result.get('success')),
                'report_url': report_result.get('report_url', '') if isinstance(report_result, dict) else '',
                'report_path': report_result.get('report_path', '') if isinstance(report_result, dict) else '',
                'logs_url': report_result.get('logs_url', '') if isinstance(report_result, dict) else '',
                'logs_path': report_result.get('logs_path', '') if isinstance(report_result, dict) else '',
                'metadata': metadata_to_save,
                'verification_review_upload': verification_review_upload,
                'execution_time_ms': execution_time_for_db,
            }
        except Exception as e:
            print(f"⚠️ [{self.script_name}] Error during report generation: {e}")
            return {
                'success': False,
                'report_url': '',
                'report_path': '',
                'logs_url': '',
                'logs_path': '',
                'metadata': self._merge_final_metadata(context),
                'verification_review_upload': verification_review_upload,
                'execution_time_ms': getattr(context, 'baseline_execution_time_ms', context.get_execution_time_ms()),
            }
        finally:
            context.stop_stdout_capture()
            self._clear_device_script_context(context)
            if print_summary:
                baseline_time = getattr(context, 'baseline_execution_time_ms', None)
                self.print_execution_summary(context, userinterface_name, baseline_time)

    def cleanup_and_exit(self, context: ScriptExecutionContext, userinterface_name: str):
        """Cleanup resources and exit with appropriate code - NO DEVICE UNLOCKING"""
        try:
            # Output results for execution system FIRST
            success_str = str(context.overall_success).lower()
            print(f"SCRIPT_SUCCESS:{success_str}")
            import sys
            sys.stdout.flush()
            self.finalize_execution_context(
                context,
                userinterface_name,
                print_summary=True,
            )
        except Exception as e:
            print(f"⚠️ [{self.script_name}] Error during report generation: {e}")
        
        # Exit with proper code
        print(f"✅ [{self.script_name}] Script execution completed (test result: {'PASS' if context.overall_success else 'FAIL'})")
        sys.exit(0)
    
    def generate_final_report(self, context: ScriptExecutionContext, userinterface_name: str) -> Dict[str, str]:
        """Generate and upload final execution report using device info (DEPRECATED - use generate_report_for_context)"""
        print(f"[@script_executor] DEPRECATED: generate_final_report() called, use generate_report_for_context() instead")
        
        # Capture test execution video (testcase_executor doesn't need this yet)
        try:
            actual_test_duration_seconds = context.get_execution_time_ms() / 1000.0
            av_controller = context.selected_device._get_controller('av')
            video_duration = max(10.0, actual_test_duration_seconds)
            test_video_url = av_controller.take_video_for_report(video_duration, context.start_time)
            context.test_video_url = test_video_url
            print(f"✅ [{self.script_name}] Test execution video captured: {test_video_url}")
        except Exception as e:
            print(f"⚠️ [{self.script_name}] Video capture failed: {e}")
            context.test_video_url = ""
        
        # Use the new reusable method
        device_info = self.get_device_info_for_report_context(context)
        host_info = self.get_host_info_for_report_context(context)
        return self.generate_report_for_context(context, device_info, host_info, userinterface_name)
    
    def get_device_info_for_report_context(self, context: ScriptExecutionContext) -> Dict[str, Any]:
        """Get device information for report generation from context"""
        if context.selected_device:
            return {
                'device_name': context.selected_device.device_name,
                'device_model': context.selected_device.device_model,
                'device_id': context.selected_device.device_id
            }
        elif getattr(context, 'host_only', False):
            return {
                'device_name': 'host',
                'device_model': 'host',
                'device_id': 'host'
            }
        else:
            return {
                'device_name': self.device_id,
                'device_model': self.device_model,
                'device_id': self.device_id
            }
    
    def get_host_info_for_report_context(self, context: ScriptExecutionContext) -> Dict[str, Any]:
        """Get host information for report generation from context"""
        if context.host:
            return {
                'host_name': context.host.host_name
            }
        else:
            return {
                'host_name': self.host_name
            }
    
    def print_execution_summary(self, context: ScriptExecutionContext, userinterface_name: str, execution_time_ms: int = None):
        """Print execution summary"""
        print("\n" + "="*60)
        print(f"🎯 [{self.script_name.upper()}] EXECUTION SUMMARY")
        print("="*60)
        
        if context.selected_device and context.host:
            print(f"📱 Device: {context.selected_device.device_name} ({context.selected_device.device_model})")
            print(f"🖥️ Host: {context.host.host_name}")
        
        print(f"📋 Interface: {userinterface_name}")
        # Use passed execution time if available, otherwise fall back to context time
        display_time_ms = execution_time_ms if execution_time_ms is not None else context.get_execution_time_ms()
        print(f"⏱️ Total Time: {display_time_ms/1000:.1f}s")
        print(f"📊 Steps: {len(context.step_results)} executed")
        print(f"📸 Screenshots: {len(context.screenshot_paths)} captured")
        print(f"🎯 Result: {'SUCCESS' if context.overall_success else 'FAILED'}")
        
        if context.error_message:
            print(f"❌ Error: {context.error_message}")
        
        # Show simple step summary
        print(f"\n📋 Steps executed: {len(context.step_results)}")
        
        # Show custom data from scripts
        if hasattr(context, 'custom_data') and context.custom_data:
            for key, value in context.custom_data.items():
                print(f"{key}: {value}")
                # Display log URL right after report URL
                if key == 'report_url' and hasattr(context, 'logs_url') and context.logs_url:
                    print(f"logs_url: {context.logs_url}")

        print("="*60)

        metadata = getattr(context, 'metadata', None)
        if metadata:
            import json as _json
            print("\n" + "-"*60)
            print("METADATA (KPIs)")
            print("-"*60)
            try:
                print(_json.dumps(metadata, indent=2, default=str, ensure_ascii=False, sort_keys=True))
            except Exception:
                for key, value in metadata.items():
                    print(f"{key}: {value}")
            print("-"*60)
    
    # =====================================================
    # HIGH-LEVEL NAVIGATION METHODS (Auto-record steps)
    # =====================================================
    
    def navigate_to(self, context: ScriptExecutionContext, target_node: str, userinterface_name: str) -> bool:
        """
        High-level navigation that handles everything automatically:
        - Loads navigation tree if needed
        - Executes navigation
        - Creates and records step automatically
        - Returns success/failure
        """
        try:
            # Load navigation tree if not already loaded
            nav_result = context.selected_device.navigation_executor.load_navigation_tree(
                userinterface_name, 
                context.team_id
            )
            if not nav_result['success']:
                context.error_message = f"Navigation tree loading failed: {nav_result.get('error', 'Unknown error')}"
                return False
            
            # Update context with loaded tree information
            context.tree_id = nav_result['tree_id']
            context.tree_data = nav_result
            context.nodes = nav_result.get('nodes', [])
            context.edges = nav_result.get('edges', [])
            
            # Execute navigation - convert target_node (label) to node_id
            # For script executor, target_node is typically a label, so we need to convert it
            try:
                target_node_id = context.selected_device.navigation_executor.get_node_id(target_node)
            except ValueError:
                # If conversion fails, assume target_node is already a node_id
                target_node_id = target_node
            
            # ✅ Wrap async call with asyncio.run for script context
            import asyncio
            navigation_result = asyncio.run(context.selected_device.navigation_executor.execute_navigation(
                tree_id=context.tree_id,
                userinterface_name=context.userinterface_name,  # MANDATORY parameter
                target_node_id=target_node_id,
                team_id=context.team_id,
                context=context
            ))
            
            # Navigation steps are already recorded by NavigationExecutor.execute_navigation()
            # No need to record duplicate step here
            
            success = navigation_result['success']
            if not success:
                context.error_message = navigation_result.get('error', 'Navigation failed')
            
            return success
            
        except Exception as e:
            context.error_message = f"Navigation error: {str(e)}"
            return False
    
    def test_success(self, context: ScriptExecutionContext):
        """Mark test as successful"""
        context.overall_success = True
        print(f"🎉 [{self.script_name}] Test completed successfully!")
    
    def test_fail(self, context: ScriptExecutionContext, error_message: str = None):
        """Mark test as failed with optional error message"""
        context.overall_success = False
        if error_message:
            context.error_message = error_message
        print(f"❌ [{self.script_name}] Test failed: {context.error_message}")


# =====================================================
# UTILITY FUNCTIONS (from script_utils.py)
# =====================================================

def handle_keyboard_interrupt(script_name: str):
    """Standard keyboard interrupt handler"""
    print(f"\n⚠️ [{script_name}] Execution interrupted by user")
    sys.exit(130)  # Standard exit code for keyboard interrupt


def handle_unexpected_error(script_name: str, error: Exception):
    """Standard unexpected error handler"""
    error_message = f"Unexpected error: {str(error)}"
    print(f"❌ [{script_name}] {error_message}")
    sys.exit(1)
