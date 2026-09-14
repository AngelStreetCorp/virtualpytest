#!/usr/bin/env python3
"""
KPI Measurement Executor Service

Measures actual time from navigation action to visual confirmation (node's KPI reference appearing).
Runs as background service, processes queued measurement requests by scanning through 5 FPS FFmpeg captures.

Architecture:
- NavigationExecutor queues KPI measurements after each successful navigation step
- Background worker processes queue and scans captures
- Stops immediately when match found (minimal scanning)
- Updates execution_results with KPI timing
- No fallbacks - fail early if required data missing
"""

import os
import time
import glob
import queue
import threading
from typing import Dict, List, Optional, Any


class KPIMeasurementRequest:
    """
    KPI measurement request - all data required, no defaults, fail early
    """
    def __init__(
        self,
        execution_result_id: str,
        team_id: str,
        capture_dir: str,
        action_timestamp: float,
        kpi_references: List[Dict[str, Any]],
        timeout_ms: int,
        device_id: str,
        userinterface_name: str,  # MANDATORY for reference resolution
        verification_timestamp: float = None,  # Optional: when verification succeeded
        last_action_wait_ms: int = None,  # Optional: for wait actions (from last action's wait_time)
        device_model: str = None,
        **kwargs
    ):
        # Validate required fields - fail early
        if not execution_result_id:
            raise ValueError("execution_result_id required")
        if not team_id:
            raise ValueError("team_id required")
        if not capture_dir:
            raise ValueError("capture_dir required")
        if not os.path.exists(capture_dir):
            raise ValueError(f"capture_dir does not exist: {capture_dir}")
        if not kpi_references:
            raise ValueError("kpi_references required")
        if timeout_ms <= 0:
            raise ValueError(f"timeout_ms must be > 0, got {timeout_ms}")
        if not device_id:
            raise ValueError("device_id required")
        if not userinterface_name:
            raise ValueError("userinterface_name required")
        
        # Validate that we have at least one: verification_timestamp OR last_action_wait_ms
        if not verification_timestamp and not last_action_wait_ms:
            raise ValueError("Either verification_timestamp or last_action_wait_ms required")
        
        if verification_timestamp and verification_timestamp < action_timestamp:
            raise ValueError(f"verification_timestamp ({verification_timestamp}) must be >= action_timestamp ({action_timestamp})")
        
        self.execution_result_id = execution_result_id
        self.team_id = team_id
        self.capture_dir = capture_dir
        self.action_timestamp = action_timestamp
        self.verification_timestamp = verification_timestamp
        self.last_action_wait_ms = last_action_wait_ms
        self.kpi_references = kpi_references
        self.timeout_ms = timeout_ms
        self.device_id = device_id
        self.userinterface_name = userinterface_name
        self.device_model = device_model
        self.kpi_timestamp = kwargs.get('kpi_timestamp')  # Pre-calculated KPI timestamp from verification


class KPIExecutor:
    """
    Background KPI measurement executor (singleton)
    
    Processes KPI measurement requests in background thread.
    Scans 5 FPS captures to find when KPI reference appears.
    """
    
    _instance = None
    _lock = threading.Lock()
    
    @classmethod
    def get_instance(cls):
        """Get singleton instance"""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
                    print(f"🆕 [KPIExecutor] Created NEW singleton instance (id={id(cls._instance)}, queue={id(cls._instance.queue)})", flush=True)
        else:
            print(f"♻️  [KPIExecutor] Returning EXISTING singleton (id={id(cls._instance)}, queue={id(cls._instance.queue)})", flush=True)
        return cls._instance
    
    def __init__(self):
        """Initialize KPI executor"""
        # Skip if already initialized
        if hasattr(self, 'queue'):
            return
        
        self.queue = queue.Queue(maxsize=1000)
        self.running = False
        self.worker_thread = None
        print("🔧 [KPIExecutor] Initialized (queue capacity: 1000)")
    
    def start(self):
        """Start background worker thread"""
        import sys
        with self._lock:  # Thread-safe start
            if self.running:
                print("⚠️ [KPIExecutor] Already running", flush=True)
                sys.stdout.flush()
                return
            
            self.running = True
            # CRITICAL: Pass queue directly to worker (proven pattern from capture_monitor.py)
            self.worker_thread = threading.Thread(
                target=self._worker_loop,
                args=(self.queue,),  # ← Pass queue as argument
                daemon=True,
                name="KPI-Worker"
            )
            self.worker_thread.start()
            print(f"✅ [KPIExecutor] Worker thread started (thread_id: {self.worker_thread.ident})", flush=True)
            sys.stdout.flush()
    
    def stop(self):
        """Stop background worker thread"""
        if not self.running:
            return
        
        print("🛑 [KPIExecutor] Stopping worker thread...")
        self.running = False
        if self.worker_thread:
            self.worker_thread.join(timeout=5)
        print("✅ [KPIExecutor] Worker thread stopped")
    
    def enqueue_measurement(self, request: KPIMeasurementRequest) -> bool:
        """
        Add measurement request to queue
        
        Returns:
            True if enqueued successfully, False if queue full
        """
        import sys
        try:
            self.queue.put(request, block=False)
            thread_alive = self.worker_thread.is_alive() if self.worker_thread else False
            print(f"📋 [KPIExecutor] Queued KPI measurement (instance={id(self)}, queue={id(self.queue)}, queue size: {self.queue.qsize()}, worker running: {self.running}, thread alive: {thread_alive})", flush=True)
            sys.stdout.flush()
            return True
        except queue.Full:
            print("❌ [KPIExecutor] Queue full! Dropping KPI measurement request", flush=True)
            sys.stdout.flush()
            return False
    
    def _worker_loop(self, work_queue):
        """
        Background worker loop that processes measurement requests
        
        CRITICAL: Queue passed as argument (proven pattern from capture_monitor.py)
        This ensures worker uses EXACT same queue object as enqueue_measurement()
        """
        import sys
        print(f"🔄 [KPIExecutor] Worker loop started (work_queue id={id(work_queue)})", flush=True)
        sys.stdout.flush()
        
        iteration = 0
        while self.running:
            try:
                # Wait for measurement request with timeout (allows clean shutdown)
                try:
                    request = work_queue.get(timeout=1.0)
                except queue.Empty:
                    # Periodic heartbeat every 30 iterations (~30 seconds)
                    iteration += 1
                    if iteration % 30 == 0:
                        print(f"💓 [KPIExecutor] Worker heartbeat (queue size: {work_queue.qsize()})", flush=True)
                        sys.stdout.flush()
                    continue
                
                # Got an item from queue - log IMMEDIATELY with explicit flush
                print(f"📥 [KPIExecutor] Worker dequeued item (type: {type(request).__name__})", flush=True)
                sys.stdout.flush()
                
                # Validate request object
                if not isinstance(request, KPIMeasurementRequest):
                    print(f"❌ [KPIExecutor] Invalid request type: {type(request)}", flush=True)
                    sys.stdout.flush()
                    self.queue.task_done()
                    continue
                
                # Process measurement request
                try:
                    print(f"🎬 [KPIExecutor] Starting processing for execution_result_id: {request.execution_result_id[:8]}", flush=True)
                    sys.stdout.flush()
                    self._process_measurement(request)
                    print(f"🏁 [KPIExecutor] Finished processing", flush=True)
                    sys.stdout.flush()
                except Exception as e:
                    print(f"❌ [KPIExecutor] Error processing measurement: {e}", flush=True)
                    sys.stdout.flush()
                    import traceback
                    traceback.print_exc()
                finally:
                    work_queue.task_done()
                    
            except Exception as e:
                print(f"❌ [KPIExecutor] Worker loop error: {e}", flush=True)
                sys.stdout.flush()
                import traceback
                traceback.print_exc()
                time.sleep(1)  # Prevent tight loop on errors
        
        print("🛑 [KPIExecutor] Worker loop exited", flush=True)
        sys.stdout.flush()
    
    def _process_measurement(self, request: KPIMeasurementRequest):
        """
        Process single KPI measurement request
        
        Scans captures from action_timestamp until match or timeout.
        Stops immediately when match found.
        """
        print("🔍 [KPIExecutor] Processing KPI measurement")
        print(f"   • Execution result: {request.execution_result_id[:8]}")
        
        # Log use case early and clearly
        if request.verification_timestamp:
            window_s = (request.verification_timestamp - request.action_timestamp)
            use_case = "CASE 1: Has verification"
            strategy = f"Scan BACKWARD from verification (last {min(100 if window_s > 60 else 25, int(window_s * 5))} images)"
            print(f"📋 [KPIExecutor] {use_case}")
            print(f"   • Strategy: {strategy}")
            print(f"   • Window: {window_s:.2f}s")
        elif request.last_action_wait_ms:
            wait_s = request.last_action_wait_ms / 1000
            use_case = "CASE 2: Has last_action_wait_ms"
            strategy = f"Scan BACKWARD from wait end (last {min(100 if wait_s > 60 else 25, int(wait_s * 5))} images)"
            print(f"📋 [KPIExecutor] {use_case}")
            print(f"   • Strategy: {strategy}")
            print(f"   • Wait time: {wait_s:.2f}s")
        else:
            timeout_s = request.timeout_ms / 1000
            use_case = "CASE 3: No verification, no wait"
            strategy = f"Scan FORWARD from action (first {min(100 if timeout_s > 60 else 25, int(timeout_s * 5))} images)"
            print(f"📋 [KPIExecutor] {use_case}")
            print(f"   • Strategy: {strategy}")
            print(f"   • Timeout: {timeout_s:.2f}s")
        
        # Check if KPI already calculated during verification (timeout polling found exact match)
        if request.kpi_timestamp:
            kpi_ms = int((request.kpi_timestamp - request.action_timestamp) * 1000)
            print(f"⚡ [KPIExecutor] KPI already calculated during verification: {kpi_ms}ms")
            print(f"   • Skipping post-processing scan (match found during timeout polling)")
            self._update_result(request.execution_result_id, request.team_id, True, kpi_ms, None)
            return
        
        print(f"   • Action timestamp: {time.strftime('%H:%M:%S', time.localtime(request.action_timestamp))}")
        print(f"   • Timeout: {request.timeout_ms}ms ({request.timeout_ms / 1000:.1f}s)")
        print(f"   • KPI references: {len(request.kpi_references)}")
        
        start_time = time.time()
        
        # Scan captures - stops at first match or timeout
        match_result = self._scan_until_match(request)
        
        # Store result
        if match_result['success']:
            kpi_ms = int((match_result['timestamp'] - request.action_timestamp) * 1000)
            algorithm = match_result.get('algorithm', 'unknown')
            print(f"✅ [KPIExecutor] KPI match found!")
            print(f"   • KPI duration: {kpi_ms}ms")
            print(f"   • Algorithm: {algorithm}")
            print(f"   • Captures scanned: {match_result['captures_scanned']}")
            self._update_result(request.execution_result_id, request.team_id, True, kpi_ms, None)
        else:
            algorithm = match_result.get('algorithm', 'unknown')
            print(f"❌ [KPIExecutor] KPI measurement failed: {match_result['error']}")
            print(f"   • Algorithm: {algorithm}")
            print(f"   • Captures scanned: {match_result.get('captures_scanned', 0)}")
            self._update_result(request.execution_result_id, request.team_id, False, None, match_result['error'])
        
        processing_time = int((time.time() - start_time) * 1000)
        print(f"⏱️ [KPIExecutor] Processing completed in {processing_time}ms")
    
    def _scan_until_match(self, request: KPIMeasurementRequest) -> Dict[str, Any]:
        """
        Scan captures using optimized quick check + backward scan algorithm.
        
        Algorithm:
        1. Quick Check: Test T0+200ms and T1-200ms (80% hit rate)
        2. Backward Scan: If not found, scan from T1 backward to T0
        
        Uses device's existing verification_executor - zero code duplication!
        
        Args:
            request: KPI measurement request with all required data
        
        Returns:
            Dict with success, timestamp, captures_scanned, error
        """
        # Extract parameters from request for clarity
        capture_dir = request.capture_dir
        action_timestamp = request.action_timestamp
        verification_timestamp = request.verification_timestamp
        kpi_references = request.kpi_references
        
        # Get device instance from host (same host, same device, just post-processing)
        from backend_host.src.lib.utils.host_utils import get_device_by_id
        
        device = get_device_by_id(request.device_id)
        if not device:
            return {'success': False, 'error': f'Device {request.device_id} not found on host', 'captures_scanned': 0}
        
        # Use device's existing verification_executor (already has all controllers initialized)
        verif_executor = device.verification_executor
        if not verif_executor:
            return {'success': False, 'error': f'No verification_executor for device {request.device_id}', 'captures_scanned': 0}
        
        # Calculate optimized time window based on what we have
        # Case 1: verification succeeded - use verification_timestamp
        # Case 2: last_action_wait_ms with no verification - use action + wait_time
        # Case 3: no verification, no wait_time - scan forward from action
        
        if request.verification_timestamp:
            # CASE 1: Has verification - scan BACKWARD from verification
            end_timestamp = request.verification_timestamp
            window_ms = int((end_timestamp - action_timestamp) * 1000)
            window_s = window_ms / 1000
            
            # Limit: 25 images (5s) normally, 100 images (20s) for long waits (>60s)
            max_images = 100 if window_s > 60 else 25
            max_window_s = max_images / 5.0
            scan_start = end_timestamp - max_window_s
            
            print(f"🔙 [KPIExecutor] Case 1: Scan BACKWARD from verification")
            print(f"   Window: {window_s:.2f}s, limiting to last {max_images} images ({max_window_s:.1f}s)")
            
        elif request.last_action_wait_ms:
            # CASE 2: Has last_action_wait_ms - scan BACKWARD from action + wait_time
            end_timestamp = action_timestamp + (request.last_action_wait_ms / 1000)
            window_s = request.last_action_wait_ms / 1000
            
            # Limit: 25 images (5s) normally, 100 images (20s) for long waits (>60s)
            max_images = 100 if window_s > 60 else 25
            max_window_s = max_images / 5.0
            scan_start = end_timestamp - max_window_s
            
            print(f"🔙 [KPIExecutor] Case 2: Scan BACKWARD from last_action_wait_ms end")
            print(f"   Wait: {window_s:.2f}s, limiting to last {max_images} images ({max_window_s:.1f}s)")
            
        else:
            # CASE 3: No verification, no last_action_wait_ms - scan FORWARD from action
            scan_start = action_timestamp
            timeout_s = request.timeout_ms / 1000
            window_s = timeout_s
            
            # Limit: 25 images (5s) normally, 100 images (20s) for long timeouts (>60s)
            max_images = 100 if timeout_s > 60 else 25
            max_window_s = max_images / 5.0
            end_timestamp = scan_start + max_window_s
            
            print(f"⏩ [KPIExecutor] Case 3: Scan FORWARD from action")
            print(f"   Timeout: {timeout_s:.2f}s, limiting to first {max_images} images ({max_window_s:.1f}s)")
        
        # Find all captures in limited time window
        pattern = os.path.join(capture_dir, "capture_*.jpg")
        all_captures = []
        
        for path in glob.glob(pattern):
            if "_thumbnail" in path:
                continue
            try:
                ts = os.path.getmtime(path)
                if scan_start <= ts <= end_timestamp:
                    all_captures.append({'path': path, 'timestamp': ts})
            except OSError:
                continue
        
        # Sort by timestamp (oldest first for index-based access)
        all_captures.sort(key=lambda x: x['timestamp'])
        
        if not all_captures:
            print(f"❌ [KPIExecutor] No captures found in time window!")
            print(f"   • Scan window: {scan_start:.2f} → {end_timestamp:.2f}")
            print(f"   • Directory: {capture_dir}")
            return {'success': False, 'error': 'No captures found in time window', 'captures_scanned': 0}
        
        total_captures = len(all_captures)
        
        # Log capture range with full paths and timestamps for debugging
        first_capture = all_captures[0]
        last_capture = all_captures[-1]
        first_time = time.strftime('%H:%M:%S', time.localtime(first_capture['timestamp']))
        last_time = time.strftime('%H:%M:%S', time.localtime(last_capture['timestamp']))
        
        print(f"📸 [KPIExecutor] Found {total_captures} captures to scan")
        print(f"   • First: {first_capture['path']}")
        print(f"   •   Time: {first_time} (ts={first_capture['timestamp']:.3f})")
        print(f"   • Last: {last_capture['path']}")
        print(f"   •   Time: {last_time} (ts={last_capture['timestamp']:.3f})")
        print(f"   • Time span: {(last_capture['timestamp'] - first_capture['timestamp']):.2f}s")
        
        # Convert kpi_references to verification format (same structure as navigation)
        verifications = []
        for kpi_ref in kpi_references:
            verifications.append({
                'verification_type': kpi_ref.get('verification_type', 'image'),
                'command': kpi_ref.get('command', 'waitForImageToAppear'),
                'params': kpi_ref.get('params', {})
            })
        
        # Helper function to test a capture
        def test_capture(capture, label):
            print(f"🔍 [KPIExecutor] Quick check - {label}: {os.path.basename(capture['path'])}")
            result = verif_executor.execute_verifications(
                verifications=verifications,
                userinterface_name=request.userinterface_name,  # MANDATORY parameter
                image_source_url=capture['path'],
                team_id=request.team_id
            )
            return result.get('success')
        
        captures_scanned = 0
        
        # ========================================
        # PHASE 1: QUICK CHECK (2 checks)
        # ========================================
        print(f"⚡ [KPIExecutor] Phase 1: Quick check")
        
        # Quick check 1: T0+200ms (immediate appearance)
        # Find capture closest to scan_start + 200ms
        target_ts = scan_start + 0.2
        early_idx = min(range(total_captures), key=lambda i: abs(all_captures[i]['timestamp'] - target_ts))
        captures_scanned += 1
        
        if test_capture(all_captures[early_idx], f"early check (T0+200ms, idx {early_idx}/{total_captures})"):
            return {
                'success': True,
                'timestamp': all_captures[early_idx]['timestamp'],
                'capture_path': all_captures[early_idx]['path'],
                'captures_scanned': captures_scanned,
                'error': None,
                'algorithm': 'quick_check_early'
            }
        
        # Quick check 2: T1-200ms (late appearance)
        # Find capture closest to end_timestamp - 200ms
        target_ts = end_timestamp - 0.2
        late_idx = min(range(total_captures), key=lambda i: abs(all_captures[i]['timestamp'] - target_ts))
        
        # Only test if different from early check
        if late_idx != early_idx:
            captures_scanned += 1
            if test_capture(all_captures[late_idx], f"late check (T1-200ms, idx {late_idx}/{total_captures})"):
                return {
                    'success': True,
                    'timestamp': all_captures[late_idx]['timestamp'],
                    'capture_path': all_captures[late_idx]['path'],
                    'captures_scanned': captures_scanned,
                    'error': None,
                    'algorithm': 'quick_check_late'
                }
        
        # ========================================
        # PHASE 2: FULL SCAN
        # ========================================
        # Determine scan direction based on case
        if request.verification_timestamp or request.last_action_wait_ms:
            # Cases 1 & 2: BACKWARD SCAN (from end to start)
            print(f"🔙 [KPIExecutor] Phase 2: Backward scan (end → start)")
            scan_range = range(total_captures - 1, -1, -1)
        else:
            # Case 3: FORWARD SCAN (from start to end)
            print(f"⏩ [KPIExecutor] Phase 2: Forward scan (start → end)")
            scan_range = range(total_captures)
        
        # Scan in determined direction
        # Skip captures already checked in quick check phase
        checked_indices = {early_idx, late_idx}
        
        print(f"🔍 [KPIExecutor] Starting full scan of {total_captures - len(checked_indices)} remaining captures")
        
        for i in scan_range:
            if i in checked_indices:
                continue
            
            capture = all_captures[i]
            captures_scanned += 1
            
            # Log progress every 10 captures to avoid spam
            if captures_scanned % 10 == 0 or captures_scanned == total_captures:
                print(f"🔍 [KPIExecutor] Progress: {captures_scanned}/{total_captures} captures scanned")
            
            result = verif_executor.execute_verifications(
                verifications=verifications,
                userinterface_name=request.userinterface_name,  # MANDATORY parameter
                image_source_url=capture['path'],
                team_id=request.team_id
            )
            
            # MATCH FOUND
            if result.get('success'):
                algorithm = 'backward_scan' if (request.verification_timestamp or request.last_action_wait_ms) else 'forward_scan'
                return {
                    'success': True,
                    'timestamp': capture['timestamp'],
                    'capture_path': capture['path'],
                    'captures_scanned': captures_scanned,
                    'error': None,
                    'algorithm': algorithm
                }
        
        # No match found after quick check + full scan
        print(f"❌ [KPIExecutor] Exhausted all {total_captures} captures without finding match")
        print(f"   • Window scanned: {window_s:.2f}s")
        print(f"   • Total captures checked: {captures_scanned}")
        
        return {
            'success': False,
            'timestamp': None,
            'captures_scanned': captures_scanned,
            'error': f'No match found in {total_captures} captures ({window_s:.2f}s window)',
            'algorithm': 'exhaustive_search_failed'
        }
    
    def _update_result(
        self,
        execution_result_id: str,
        team_id: str,
        success: bool,
        kpi_ms: Optional[int],
        error: Optional[str],
        report_url: Optional[str] = None
    ):
        """
        Update execution_results with KPI measurement result using shared database function
        """
        try:
            from shared.src.lib.database.execution_results_db import update_execution_result_with_kpi
            
            result = update_execution_result_with_kpi(
                execution_result_id=execution_result_id,
                team_id=team_id,
                kpi_measurement_success=success,
                kpi_measurement_ms=kpi_ms,
                kpi_measurement_error=error,
                kpi_report_url=report_url
            )
            
            if result:
                if report_url:
                    print(f"💾 [KPIExecutor] Stored KPI result: {kpi_ms}ms (success: {success}) - Report: {report_url}")
                else:
                    print(f"💾 [KPIExecutor] Stored KPI result: {kpi_ms}ms (success: {success})")
            else:
                print(f"⚠️ [KPIExecutor] Failed to update execution_result_id: {execution_result_id[:8]}")
                
        except Exception as e:
            print(f"❌ [KPIExecutor] Error storing KPI result: {e}")
            import traceback
            traceback.print_exc()


# Module-level function to get service instance
def get_kpi_executor() -> KPIExecutor:
    """Get singleton KPI executor instance"""
    return KPIExecutor.get_instance()
