"""
Standardized Verification Executor

This module provides a standardized way to execute verifications that can be used by:
- Python code directly (navigation execution, scripts, etc.)
- API endpoints (maintaining consistency)
- Frontend hooks (via API calls)

The core logic is the same as /server/verification/executeBatch but available as a reusable class.
"""

import os
import time
from typing import Dict, List, Optional, Any, Tuple


class VerificationExecutor:
    """
    Standardized verification executor that provides consistent verification execution
    across Python code and API endpoints.
    
    CRITICAL: Do not create new instances directly! Use device.verification_executor instead.
    Each device has a singleton VerificationExecutor that preserves navigation context.
    """
    
    @classmethod
    def get_for_device(cls, device):
        """
        Factory method to get the device's existing VerificationExecutor.
        
        RECOMMENDED: Use device.verification_executor directly instead of this method.
        
        Args:
            device: Device instance
            
        Returns:
            The device's existing VerificationExecutor instance
            
        Raises:
            ValueError: If device doesn't have a verification_executor
        """
        if not hasattr(device, 'verification_executor') or not device.verification_executor:
            raise ValueError(f"Device {device.device_id} does not have a VerificationExecutor. "
                           "VerificationExecutors are created during device initialization.")
        return device.verification_executor
    
    def __init__(self, device, tree_id: str = None, node_id: str = None, _from_device_init: bool = False):
        """
        Initialize VerificationExecutor
        
        Args:
            device: Device instance (mandatory, contains host_name and device_id)
            tree_id: Tree ID for navigation context
            node_id: Node ID for navigation context
            _from_device_init: Internal flag to indicate creation from device initialization
        """
        if not device:
            raise ValueError("Device instance is required")
        if not device.host_name:
            raise ValueError("Device must have host_name")
        if not device.device_id:
            raise ValueError("Device must have device_id")
        
        if not _from_device_init:
            import traceback
            print(f"⚠️ [VerificationExecutor] WARNING: Creating new VerificationExecutor instance for device {device.device_id}")
            print(f"⚠️ [VerificationExecutor] This may cause state loss! Use device.verification_executor instead.")
            print(f"⚠️ [VerificationExecutor] Call stack:")
            for line in traceback.format_stack()[-3:-1]:  # Show last 2 stack frames
                print(f"⚠️ [VerificationExecutor]   {line.strip()}")
        
        # Store instances directly
        self.device = device
        self.host_name = device.host_name
        self.device_id = device.device_id
        self.device_model = device.device_model
        self.device_name = device.device_name

        # Get AV controller directly from device for screenshot capture
        self.av_controller = device._get_controller('av')
        if not self.av_controller:
            print(f"[@verification_executor] Warning: No AV controller found for device {self.device_id}")
        
        # Get verification controllers directly by type
        verification_controllers = device.get_controllers('verification')
        
        # ALSO get web and desktop controllers (they have built-in verification methods)
        web_controllers = device.get_controllers('web')
        desktop_controllers = device.get_controllers('desktop')
        
        # Combine all controllers that support verifications
        all_controllers = verification_controllers + web_controllers + desktop_controllers
        
        self.video_controller = None
        self.image_controller = None
        self.text_controller = None
        self.color_controller = None
        self.audio_controller = None
        self.adb_controller = None
        self.appium_controller = None
        self.web_controller = None
        self.desktop_controller = None

        for ctrl in all_controllers:
            class_name = ctrl.__class__.__name__.lower()
            if 'video' in class_name:
                self.video_controller = ctrl
            elif 'image' in class_name:
                self.image_controller = ctrl
            elif 'color' in class_name:
                self.color_controller = ctrl
            elif 'text' in class_name:
                self.text_controller = ctrl
            elif 'audio' in class_name:
                self.audio_controller = ctrl
            elif 'adb' in class_name:
                self.adb_controller = ctrl
            elif 'appium' in class_name:
                self.appium_controller = ctrl
            elif 'playwright' in class_name or 'web' in class_name:
                self.web_controller = ctrl
            elif 'desktop' in class_name or 'bash' in class_name or 'pyautogui' in class_name:
                self.desktop_controller = ctrl

        # Initialized for device: {self.device_id}, model: {self.device_model}
    
    def take_screenshot(self) -> Tuple[bool, str, str]:
        """
        Take a screenshot and return base64 data for AI analysis.
        
        Returns:
            tuple: (success, base64_screenshot_data, error_message)
        """
        try:
            # Use remote controller for base64 screenshot data
            remote_controller = self.device._get_controller('remote')
            if not remote_controller:
                return False, "", "No remote controller available"
            
            if not hasattr(remote_controller, 'take_screenshot'):
                return False, "", "Remote controller does not support screenshots"
            
            print(f"[@verification_executor] Taking screenshot using remote controller: {type(remote_controller).__name__}")
            return remote_controller.take_screenshot()
            
        except Exception as e:
            error_msg = f"Screenshot error: {str(e)}"
            print(f"[@verification_executor] {error_msg}")
            return False, "", error_msg
    
    def get_available_context(self, userinterface_name: str = None) -> Dict[str, Any]:
        """
        Get available verification context for AI based on user interface
        
        Args:
            userinterface_name: User interface name for context
            
        Returns:
            Dict with available verifications and their descriptions
        """
        try:
            device_verifications = []
            
            print(f"[@verification_executor] Loading verification context for device: {self.device_id}, model: {self.device_model}")
            
            # Get verification actions from verification controllers AND web controller
            verification_types = ['image', 'text', 'color', 'adb', 'appium', 'video', 'audio', 'web', 'desktop']
            for v_type in verification_types:
                try:
                    controller = getattr(self, f'{v_type}_controller', None)
                    if controller and hasattr(controller, 'get_available_verifications'):
                        verifications = controller.get_available_verifications()
                        if isinstance(verifications, list):
                            for verification in verifications:
                                device_verifications.append({
                                    'command': verification.get('command', ''),
                                    'action_type': f'verification_{v_type}',
                                    'params': verification.get('params', {}),
                                    'description': verification.get('description', '')
                                })
                except Exception as e:
                    print(f"[@verification_executor] Could not load verification_{v_type} verifications: {e}")
                    continue
            
            print(f"[@verification_executor] Loaded {len(device_verifications)} verifications from controllers")
            
            return {
                'service_type': 'verifications',
                'device_id': self.device_id,
                'device_model': self.device_model,
                'userinterface_name': userinterface_name,
                'available_verifications': device_verifications
            }
            
        except Exception as e:
            print(f"[@verification_executor] Error loading verification context: {e}")
            return {
                'service_type': 'verifications',
                'device_id': self.device_id,
                'device_model': self.device_model,
                'userinterface_name': userinterface_name,
                'available_verifications': []
            }
    
    async def execute_verifications(self, 
                            verifications: List[Dict[str, Any]],
                            userinterface_name: str,  # MANDATORY for reference resolution
                            image_source_url: Optional[str] = None,
                            team_id: str = None,
                            context = None,
                            tree_id: Optional[str] = None,
                            node_id: Optional[str] = None,
                            verification_pass_condition: str = None,  # Auto-detect if not provided
                            suppress_failure_report: bool = False,  # Skip per-call debug report + R2 upload (KPI scans)
                            generate_success_report: bool = False  # Also build a report for the last PASSED check (manual verifications, false-positive review)
                           ) -> Dict[str, Any]:
        """
        Execute batch of verifications (PURE - no log capture)
        
        Args:
            verifications: List of verification dictionaries
            userinterface_name: User interface name (REQUIRED for reference resolution, e.g., 'example_androidtv')
            image_source_url: Optional source image URL for image/text verifications
            team_id: Team ID for database recording
            context: Optional execution context
            tree_id: Navigation tree ID for database recording
            node_id: Navigation node ID for database recording
            verification_pass_condition: Condition for passing ('all' or 'any'). If None, auto-detects from verifications data.
            
        Returns:
            Dict with success status, results, and execution statistics
        """
        # Auto-detect verification_pass_condition from verifications if not explicitly provided
        if verification_pass_condition is None:
            if verifications and isinstance(verifications[0], dict) and 'verification_pass_condition' in verifications[0]:
                verification_pass_condition = verifications[0]['verification_pass_condition']
                print(f"[@lib:verification_executor:execute_verifications] Auto-detected pass_condition from verification data: '{verification_pass_condition}'")
            else:
                verification_pass_condition = 'all'  # Default
                print(f"[@lib:verification_executor:execute_verifications] Using default pass_condition: 'all' (not found in verification data)")
        
        # Reduced logging for cleaner output during KPI scans

        # Validate inputs
        if not verifications:
            return {
                'success': True,
                'message': 'No verifications to execute',
                'results': [],
                'passed_count': 0,
                'total_count': 0
            }
        
        # Filter valid verifications
        valid_verifications = self._filter_valid_verifications(verifications)
        
        if not valid_verifications:
            return {
                'success': True,
                'has_verifications': False,
                'message': 'All verifications were invalid and filtered out',
                'results': [],
                'passed_count': 0,
                'total_count': 0
            }
        
        results = []
        passed_count = 0

        # Capture ONE shared frame for all image/text verifications in this batch.
        # Without this, each image/text controller calls take_screenshot() independently and starts
        # its own polling window from a later frame, doubling the wall-clock when the first frame
        # doesn't match. The shared frame becomes image_list[0] for both controllers; their
        # _get_next_capture polling still walks future frames identically.
        shared_capture_path = None
        if not image_source_url and self.av_controller:
            needs_shared_capture = any(
                v.get('verification_type') in ('image', 'text') for v in valid_verifications
            )
            if needs_shared_capture:
                # Sync HTTP/adb call — wrap in to_thread to keep the event
                # loop responsive (see _execute_single_verification's call
                # below for the same rationale). For KPI scans this branch
                # is skipped (image_source_url is set), but live verification
                # benefits.
                import asyncio
                shared_capture_path = await asyncio.to_thread(self.av_controller.take_screenshot)
                if shared_capture_path:
                    print(f"[@lib:verification_executor:execute_verifications] Shared capture for batch: {shared_capture_path}")

        # Two ways to walk frames:
        #   • Shared-window (_execute_shared_window): a LIVE batch with more than
        #     one image/text leg where at least one polls (timeout>0). Build ONE
        #     frame window and check every leg against each frame in lock-step —
        #     coherent (all legs see the same frames) and fast (stop the moment
        #     the pass_condition is met). Fixes the 'any can pass' either/or bug
        #     where a timeout=0 leg (e.g. CONTINUE) was only ever checked against
        #     the first, often-still-loading frame.
        #   • Sequential (else): single leg, all-instant (timeout=0), fixed KPI
        #     image, or a mixed-type batch — each leg walks its own frames via
        #     the controller, exactly as before.
        poll_window_ms = max(
            (int(v.get('params', {}).get('timeout', 0) or 0) for v in valid_verifications),
            default=0,
        )
        use_shared_window = (
            shared_capture_path is not None
            and len(valid_verifications) > 1
            and poll_window_ms > 0
            and all(v.get('verification_type', 'text') in ('image', 'text') for v in valid_verifications)
        )

        if use_shared_window:
            results, passed_count = await self._execute_shared_window(
                valid_verifications,
                base_capture_path=shared_capture_path,
                window_timeout_s=poll_window_ms / 1000.0,
                userinterface_name=userinterface_name,
                context=context,
                team_id=team_id,
                verification_pass_condition=verification_pass_condition,
            )
        else:
            # Execute each verification sequentially (each leg polls its own
            # window via the controller when timeout>0).
            for i, verification in enumerate(valid_verifications):
                verification_type = verification.get('verification_type', 'text')

                # Use the shared capture for image/text verifications; other types keep their own paths
                per_verification_source = image_source_url
                if per_verification_source is None and shared_capture_path and verification_type in ('image', 'text'):
                    per_verification_source = shared_capture_path

                start_time = time.time()
                result = await self._execute_single_verification(verification, userinterface_name, per_verification_source, context, team_id)
                execution_time = int((time.time() - start_time) * 1000)

                # Add execution time to result
                result['execution_time_ms'] = execution_time
                results.append(result)

                # Count successful verifications
                if result.get('success'):
                    passed_count += 1

                # NavigationExecutor records one execution_results row per node
                # visit (verify_node call) — not one per individual verification.
                # VerificationExecutor is a pure primitive — never writes to DB.

                # Short-circuit for 'any can pass': the batch is already decided the
                # moment one leg passes, so running the remaining legs is wasted work
                # (and produces confusing red ❌ lines for checks that never needed to
                # pass — e.g. a 'no_signal' image check failing is the desired state
                # once 'blackscreen' matched). Mark the rest as "not verified"
                # (skipped, neutral — neither pass nor fail) and stop early.
                if verification_pass_condition == 'any' and result.get('success'):
                    for skipped in valid_verifications[i + 1:]:
                        results.append({
                            'success': False,
                            'skipped': True,
                            'resultType': 'SKIPPED',
                            'command': skipped.get('command'),
                            'params': skipped.get('params', {}),
                            'verification_type': skipped.get('verification_type', 'text'),
                            'message': 'Not verified (any-pass already satisfied)',
                            'execution_time_ms': 0,
                        })
                    print(f"[@lib:verification_executor:execute_verifications] 'any can pass' short-circuit: leg {i + 1}/{len(valid_verifications)} passed, skipping {len(valid_verifications) - i - 1} remaining leg(s)")
                    break


        
        # Calculate overall success based on verification_pass_condition
        if verification_pass_condition == 'any':
            # Pass if ANY verification passed (at least one)
            overall_success = passed_count > 0
            print(f"[@lib:verification_executor:execute_verifications] 'any can pass' mode: {passed_count}/{len(valid_verifications)} passed → {'✅ PASS' if overall_success else '❌ FAIL'}")
        else:
            # Default: Pass only if ALL verifications passed
            overall_success = passed_count == len(valid_verifications)
            print(f"[@lib:verification_executor:execute_verifications] 'all must pass' mode: {passed_count}/{len(valid_verifications)} passed → {'✅ PASS' if overall_success else '❌ FAIL'}")
        
        # Generate a debug report for the LAST failed verification, even when
        # 'any can pass' lets the batch succeed overall. A passing batch with
        # one failed leg used to swallow the artefact, leaving no way to
        # inspect WHY the failed leg didn't match (weak reference, wrong
        # area, stale capture). Iterating reversed so multi-failure batches
        # surface the most-recent attempt.
        debug_report_path = None
        debug_report_url = None
        success_report_path = None
        success_report_url = None
        # KPI scans call this once per candidate frame; every non-matching frame
        # is a "failure" that would otherwise generate a debug report + upload
        # 2–3 images to R2 (~1.5–3s each on a Pi). That per-frame cost is what
        # blows kpi_executor's 10s SCAN_DEADLINE_SECONDS budget, recording a
        # spurious "scan budget exceeded" failure even though the destination is
        # on screen a few frames later. The kpi_executor builds its own report
        # for the single matched/failed frame, so suppress these here.
        if not suppress_failure_report and any(not r.get('success', False) and '_report_config' in r for r in results):
            # Generate a debug report for EVERY failed image/text verification,
            # not just one: a step with multiple failing legs (e.g. two
            # waitForTextToAppear checks) must let the reader open each leg's own
            # source/reference/overlay evidence pack from the report. Each report
            # uploads 2–3 images to R2 (~1.5–3s/each on a Pi) — fine for live nav
            # (1–3 verifications), and KPI per-frame scans skip this entirely via
            # suppress_failure_report. The top-level debug_report_* mirrors the
            # FIRST failure so the single-link summary stays consistent with
            # error_info below (which is also the first failure's message).
            for result in results:
                if not result.get('success', False) and '_report_config' in result:
                    print(f"[@lib:verification_executor] 🔍 GENERATING DEBUG REPORT FOR FAILED LEG (batch overall: {'PASS' if overall_success else 'FAIL'})")
                    report_path, report_url = self._build_verification_report(result, is_success=False)
                    if report_path:
                        result['debug_report_path'] = report_path
                        result['debug_report_url'] = report_url
                        if not debug_report_url:
                            debug_report_path = report_path
                            debug_report_url = report_url

        # Success report: opt-in (manual verifications only — see route). Mirrors
        # the failure path but for the LAST passing image/text check, so a
        # suspected false positive (passed but the evidence looks wrong) can be
        # inspected with the same source/reference/overlay evidence pack.
        if generate_success_report and any(r.get('success', False) and '_report_config' in r for r in results):
            for result in reversed(results):
                if result.get('success', False) and '_report_config' in result:
                    print(f"[@lib:verification_executor] 🟢 GENERATING SUCCESS REPORT FOR LAST PASS (false-positive review)")
                    report_path, report_url = self._build_verification_report(result, is_success=True)
                    if report_path:
                        success_report_path = report_path
                        success_report_url = report_url
                        result['success_report_path'] = report_path
                        result['success_report_url'] = report_url
                    break

        # Extract detailed error information from failed verifications
        error_info = None
        if not overall_success and results:
            # Get the first failed verification's message as the primary error
            for result in results:
                if not result.get('success', False):
                    error_info = result.get('message', 'Verification failed')
                    # Debug report paths already set above (lines 311-395)
                    break
        
        # Collect all verification evidence for KPI report
        verification_evidence_list = []
        for result in results:
            if 'verification_evidence' in result:
                verification_evidence_list.append(result['verification_evidence'])

        # Report screenshots MUST stay 1:1 (and same order) with `results`: the
        # report zips verification_screenshots[i] against verification_results[i]
        # to resolve each thumbnail's command/params. Derive the list straight
        # from results — each row already carries its final-frame
        # `screenshot_path`. A naive per-capture accumulator would NOT be 1:1:
        # the shared poll-window (_execute_shared_window) re-runs each leg
        # against every frame it walks, so a leg polling N frames would yield N
        # screenshots while results holds one row per leg, and the trailing
        # thumbnails would fall past the end of verification_results and render
        # as "unknown()" in the report. '' placeholders keep positions for
        # skipped legs (any-pass short-circuit) that never captured a frame.
        verification_screenshots = [r.get('screenshot_path') or '' for r in results]

        result = {
            'success': overall_success,
            'total_count': len(valid_verifications),
            'passed_count': passed_count,
            'failed_count': len(valid_verifications) - passed_count,
            'results': results,
            'verification_screenshots': verification_screenshots,  # 1:1 with results (see note above)
            'verification_evidence_list': verification_evidence_list,  # ✅ NEW: All verification evidence for KPI
            'message': f'Batch verification completed: {passed_count}/{len(valid_verifications)} passed'
        }
        
        # Add error information if verifications failed
        if error_info:
            result['error'] = error_info
            # ✅ Include debug report path and URL if available
            if debug_report_path:
                result['debug_report_path'] = debug_report_path
            if debug_report_url:
                result['debug_report_url'] = debug_report_url

        # Surface the success report (false-positive review) at the batch level too.
        if success_report_path:
            result['success_report_path'] = success_report_path
        if success_report_url:
            result['success_report_url'] = success_report_url

        return result

    def _build_verification_report(self, result: Dict[str, Any], is_success: bool):
        """Upload a verification's evidence images to R2 and generate its HTML+PNG report.

        Shared by the failure path (always-on) and the success path (opt-in, for
        false-positive review). `result` must carry `_report_config` and `details`
        from `_execute_single_verification`. Returns `(report_path, report_url)` or
        `(None, None)` on any failure — report generation must never break the batch.
        """
        outcome = 'success' if is_success else 'failure'
        try:
            from shared.src.lib.utils.verification_report_generator import (
                generate_verification_failure_report,
                generate_verification_success_report,
            )
            from shared.src.lib.utils.storage_path_utils import get_capture_folder
            from backend_host.src.lib.utils.host_utils import get_host_instance

            verification_config = result['_report_config']
            details = result.get('details', {})

            # Get device folder from AV controller
            device_folder = get_capture_folder(self.av_controller.video_capture_path)

            # Get host info for URL building
            host = get_host_instance()
            host_info = {
                'host_name': host.host_name,
                'host_url': host.host_url
            }

            # Get source_image_path from result details (cropped) and original from config
            source_path = None
            original_path = verification_config.get('source_image_path')  # Original before crop
            # Prefer the actual area used at runtime (resolved from references DB) over the
            # potentially-stale params.area embedded in the navigation edge config. The red
            # rectangle on the full screenshot must mark where the crop was actually taken.
            crop_area = (
                details.get('match_location')
                or details.get('resolved_area')
                or verification_config.get('params', {}).get('area')
            )

            if 'source_image_path' in details:
                source_path = details['source_image_path']  # Cropped version
            elif 'source_image_path' in verification_config:
                source_path = verification_config['source_image_path']
            else:
                print(f"[@lib:verification_executor] ❌ source_image_path not found!")

            if not (source_path and device_folder):
                if not source_path:
                    print(f"[@lib:verification_executor] ⚠️ Source path not found - cannot generate {outcome} report")
                if not device_folder:
                    print(f"[@lib:verification_executor] ⚠️ Device folder is None - cannot generate {outcome} report")
                return None, None

            # ✅ UPLOAD verification images to R2 BEFORE generating report (reuse KPI upload utility)
            try:
                from shared.src.lib.utils.cloudflare_utils import upload_kpi_thumbnails
                from shared.src.lib.utils.storage_path_utils import get_cold_storage_path
                from PIL import Image, ImageDraw

                # Resolve the red (exact crop / match location) + yellow (fuzzy search)
                # rectangle geometry once. Fuzzy params live on the user-defined area
                # (resolved_area or params.area), independent of the red-rectangle source.
                rx = ry = rw = rh = None
                if isinstance(crop_area, dict):
                    rx, ry, rw, rh = crop_area.get('x'), crop_area.get('y'), crop_area.get('width'), crop_area.get('height')
                elif isinstance(crop_area, (list, tuple)) and len(crop_area) == 4:
                    rx, ry, rw, rh = crop_area
                fuzzy_src = (
                    details.get('resolved_area')
                    or verification_config.get('params', {}).get('area')
                )
                fx = fy = fw = fh = None
                if isinstance(fuzzy_src, dict):
                    fx, fy, fw, fh = fuzzy_src.get('fx'), fuzzy_src.get('fy'), fuzzy_src.get('fwidth'), fuzzy_src.get('fheight')
                has_red = None not in (rx, ry, rw, rh)
                has_yellow = None not in (fx, fy, fw, fh)

                def _annotate_full(full_disk_path):
                    """Draw the red/yellow rectangles on a full frame; return the path to
                    upload (annotated copy, or the original on draw failure / no boxes)."""
                    if not (full_disk_path and os.path.exists(full_disk_path)):
                        return None
                    if not (has_red or has_yellow):
                        return full_disk_path
                    try:
                        img = Image.open(full_disk_path)
                        draw = ImageDraw.Draw(img)
                        if has_red:
                            draw.rectangle([rx, ry, rx + rw, ry + rh], outline='red', width=3)
                        if has_yellow:
                            draw.rectangle([fx, fy, fx + fw, fy + fh], outline='yellow', width=3)
                        cold_base = get_cold_storage_path(device_folder, '')
                        stamp = str(int(time.time() * 1000))
                        out = os.path.join(cold_base, f'original_with_crop_{stamp}.png')
                        img.save(out)
                        return out
                    except Exception as overlay_err:
                        print(f"[@lib:verification_executor] ⚠️ Could not draw crop rectangle, uploading original unmodified: {overlay_err}")
                        return full_disk_path

                upload_timestamp = time.strftime('%Y%m%d%H%M%S')
                # R2 keys are namespaced by upload_kpi_thumbnails as
                # kpi_measurement/<id[:8]>/<timestamp>_<type>.jpg, so the id MUST be
                # unique in its FIRST 8 CHARS per upload group. A descriptive id like
                # f"verif_{outcome}_{device_folder}" truncates to the constant "verif_fa"
                # (and the per-frame "_<label>" suffix lives past char 8, so it's discarded
                # too). With a second-precision timestamp, a node's two shared-window legs
                # (e.g. text 'Discover' + image 'replay_red') that both fail and generate
                # their reports in the same second upload to identical keys — the second
                # leg OVERWRITES the first. The text report then renders the image leg's
                # frame + fuzzy box + 20x4 crop (empty "Cropped source"). Use a fresh uuid
                # per upload group so every report/frame gets its own R2 folder.
                import uuid
                frames = details.get('frames') or []

                if frames:
                    # Wait-timeline (waitFor* polling): upload first/best/last each as a
                    # full + crop + overlay set, attaching per-frame R2 URLs the report's
                    # synced hero swaps between. The legacy single-image URLs + the AI
                    # composite are then pointed at the BEST frame so they stay in sync
                    # with its crop (fixes the full=frame-0 / crop=best misalignment).
                    for fr in frames:
                        imgs = {}
                        full_ann = _annotate_full(fr.get('full_path'))
                        if full_ann:
                            imgs['original'] = full_ann
                        if fr.get('crop_path') and os.path.exists(fr['crop_path']):
                            imgs['source'] = fr['crop_path']
                        if fr.get('overlay_path') and os.path.exists(fr['overlay_path']):
                            imgs['overlay'] = fr['overlay_path']
                        if not imgs:
                            continue
                        # Fresh uuid per frame: first/best/last must not share a folder
                        # (same timestamp + constant prefix would collapse them to one).
                        urls = upload_kpi_thumbnails(imgs, uuid.uuid4().hex, upload_timestamp)
                        fr['full_url'] = urls.get('original')
                        fr['source_url'] = urls.get('source')
                        fr['overlay_url'] = urls.get('overlay')
                    best_fr = next((f for f in frames if f.get('label') == 'best'), frames[0])
                    if best_fr.get('source_url'):
                        details['source_image_url'] = best_fr['source_url']
                    if best_fr.get('full_url'):
                        details['original_image_url'] = best_fr['full_url']
                    if best_fr.get('overlay_url'):
                        details['result_overlay_url'] = best_fr['overlay_url']
                    # Sync the composite's full frame to the best frame too.
                    if best_fr.get('full_path'):
                        original_path = best_fr['full_path']
                    print(f"[@lib:verification_executor] ✅ Uploaded {len(frames)} wait-timeline frames to R2 for {outcome} report")
                else:
                    # Single-shot verification (no polling) — one full + crop + overlay.
                    evidence_images = {}
                    if source_path and os.path.exists(source_path):
                        evidence_images['source'] = source_path
                    full_ann = _annotate_full(original_path)
                    if full_ann:
                        evidence_images['original'] = full_ann
                    elif original_path:
                        print(f"[@lib:verification_executor] ⚠️ Original screenshot path missing on disk: {original_path}")
                    overlay_path = details.get('result_overlay_path')
                    if overlay_path and os.path.exists(overlay_path):
                        evidence_images['overlay'] = overlay_path

                    if evidence_images:
                        r2_urls = upload_kpi_thumbnails(evidence_images, uuid.uuid4().hex, upload_timestamp)
                        if r2_urls.get('source'):
                            details['source_image_url'] = r2_urls['source']
                        if r2_urls.get('original'):
                            details['original_image_url'] = r2_urls['original']
                        if r2_urls.get('overlay'):
                            details['result_overlay_url'] = r2_urls['overlay']
                        print(f"[@lib:verification_executor] ✅ Uploaded {len(r2_urls)}/{len(evidence_images)} images to R2 for {outcome} report")
            except Exception as upload_error:
                print(f"[@lib:verification_executor] ⚠️ R2 upload failed: {upload_error}, using local paths")
                import traceback
                traceback.print_exc()

            # Full analysed-window mosaic — debugging aid for FAILURES only, and only
            # when a real window was polled (>=5 distinct frames). Verification runs
            # constantly (every node verify), so this gate stops it flooding R2; KPI
            # has no such gate (it runs once per edge). Shows every frame the verifier
            # checked so you can see WHY nothing matched. Never breaks the report.
            if not is_success:
                try:
                    analyzed = details.get('analyzed_frames') or []
                    if len(analyzed) < 5:
                        # Fall back to per-leg wait-timeline frames (sequential path).
                        analyzed = [{'path': fr.get('full_path')}
                                    for fr in (details.get('frames') or []) if fr.get('full_path')]
                    if len(analyzed) >= 5:
                        import tempfile, shutil as _shutil
                        from shared.src.lib.utils.scan_mosaic import build_mosaic_pages, render_mosaic_section, format_offset
                        from shared.src.lib.utils.cloudflare_utils import upload_kpi_thumbnails as _upload
                        base_ts = analyzed[0].get('mtime') or 0
                        frames_in = []
                        for fr in analyzed:
                            pth = fr.get('path')
                            if not pth:
                                continue
                            off = (fr.get('mtime') or base_ts) - base_ts
                            frames_in.append({
                                'path': pth,
                                'label': os.path.basename(pth).replace('capture_', '').replace('.jpg', ''),
                                'sublabel': format_offset(off),
                                'border': None,
                            })
                        mosaic_ts = time.strftime('%Y%m%d%H%M%S')
                        import uuid as _uuid
                        tmpd = tempfile.mkdtemp(prefix='verif_mosaic_')
                        try:
                            pages, stats = build_mosaic_pages(frames_in, tmpd, f"verif_{device_folder}")
                            if pages:
                                ups = {f'scan_{i + 1}': p for i, p in enumerate(pages)}
                                # Fresh uuid folder — "verif_failure_<device>"[:8] is the
                                # constant "verif_fa", so sibling reports' mosaics collide.
                                m_urls = _upload(ups, _uuid.uuid4().hex, mosaic_ts) or {}
                                page_urls = [m_urls[f'scan_{i + 1}'] for i in range(len(pages)) if f'scan_{i + 1}' in m_urls]
                                details['scan_mosaic_section'] = render_mosaic_section(page_urls, stats)
                                print(f"[@lib:verification_executor] 🧩 Scan mosaic: {stats['analyzed']} → "
                                      f"{stats['shown']} shown across {len(page_urls)} page(s)")
                        finally:
                            _shutil.rmtree(tmpd, ignore_errors=True)
                except Exception as mosaic_err:
                    print(f"[@lib:verification_executor] ⚠️ scan mosaic skipped: {mosaic_err}")

            # Add paths to verification_config for report generator.
            # `resolved_area` and `match_location` come from details (set by the image
            # controller); the report shows these in chips instead of the stale params.area.
            verification_config_with_path = {
                **verification_config,
                'source_image_path': source_path,
                'original_image_path': original_path,
                'crop_area': crop_area,
                'resolved_area': details.get('resolved_area'),
                'match_location': details.get('match_location'),
            }

            # Generate report (with R2 URLs in details if upload succeeded)
            generator = generate_verification_success_report if is_success else generate_verification_failure_report
            report_path = generator(
                verification_config=verification_config_with_path,
                verification_result=result,
                device_folder=device_folder,
                host_info=host_info
            )
            if not report_path:
                print(f"[@lib:verification_executor] ⚠️ {outcome.capitalize()} report generation returned None")
                return None, None

            from shared.src.lib.utils.build_url_utils import buildHostImageUrl
            report_url = buildHostImageUrl(host_info, report_path)
            print(f"[@lib:verification_executor] 🔍 {outcome.upper()} REPORT: {report_url}")
            return report_path, report_url
        except Exception as report_error:
            print(f"[@lib:verification_executor] ❌ Failed to generate {outcome} report: {report_error}")
            import traceback
            traceback.print_exc()
            return None, None

    def get_execution_status(self, execution_id: str) -> Dict[str, Any]:
        """
        Get status of async verification execution (called by route polling).
        
        Returns:
            {
                'success': bool,
                'execution_id': str,
                'status': 'running' | 'completed' | 'error',
                'result': dict (if completed),
                'error': str (if error),
                'progress': int,
                'message': str
            }
        """
        import threading
        if not hasattr(self, '_executions'):
            return {
                'success': False,
                'error': f'Execution {execution_id} not found'
            }
        
        if not hasattr(self, '_lock'):
            self._lock = threading.Lock()
        
        with self._lock:
            if execution_id not in self._executions:
                return {
                    'success': False,
                    'error': f'Execution {execution_id} not found'
                }
            
            execution = self._executions[execution_id].copy()
        
        return {
            'success': True,
            'execution_id': execution['execution_id'],
            'status': execution['status'],
            'result': execution.get('result'),
            'error': execution.get('error'),
            'progress': execution.get('progress', 0),
            'message': execution.get('message', ''),
            'elapsed_time_ms': int((time.time() - execution['start_time']) * 1000)
        }
    
    async def verify_node(self, node_id: str, userinterface_name: str, team_id: str, tree_id: str = None, image_source_url: Optional[str] = None) -> Dict[str, Any]:
        """
        Execute verifications for a specific node during navigation.
        
        Args:
            node_id: Node ID to verify
            userinterface_name: User interface name (REQUIRED for reference resolution)
            team_id: Team ID
            tree_id: Optional tree ID (will fall back to navigation context if not provided)
            image_source_url: Optional image source URL
            
        Returns:
            Dict with success status and verification results
        """
        print(f"[@lib:verification_executor:verify_node] 🔍 Called with node_id={node_id}, userinterface_name={userinterface_name}, tree_id={tree_id}, team_id={team_id}")
        
        try:
            # Get tree_id from navigation context if not provided (use root tree for unified graph)
            if not tree_id:
                nav_context = self.device.navigation_context
                tree_id = nav_context.get('tree_id')  # Use root tree_id, not current_tree_id
                print(f"[@lib:verification_executor:verify_node] Tree ID from context: {tree_id}")
            
            # ✅ USE ALREADY-LOADED UNIFIED GRAPH (zero database calls, zero cache calls!)
            # NavigationExecutor already loaded the unified graph during navigation
            if not hasattr(self.device, 'navigation_executor') or not self.device.navigation_executor:
                raise ValueError(f"Device {self.device_id} has no NavigationExecutor - cannot verify")

            unified_graph = self.device.navigation_executor.unified_graph
            if not unified_graph:
                # A whole-tree /cache/clear (edge/node delete, batch save, restore)
                # blanks every executor's snapshot — including one whose navigation
                # is mid-flight in a wait_time sleep. Re-sync from the variant-aware
                # cache (auto-populates from DB on miss) the same way
                # execute_navigation does at entry, instead of failing the run.
                unified_graph = self.device.navigation_executor._sync_unified_graph(
                    tree_id, team_id, userinterface_name
                )
            if not unified_graph:
                raise ValueError(f"NavigationExecutor has no unified graph loaded - call load_navigation_tree() first")
            
            print(f"[@lib:verification_executor:verify_node] ✅ Using unified graph from NavigationExecutor ({len(unified_graph.nodes)} nodes)")
            
            # Get node data from unified graph
            if node_id not in unified_graph.nodes:
                print(f"[@lib:verification_executor:verify_node] ⚠️ Node {node_id} not in graph - skipping verification")
                return {'success': False, 'has_verifications': False, 'message': 'Node not found in graph', 'results': []}
            
            node_data = unified_graph.nodes[node_id]
            
            if not node_data:
                print(f"[@lib:verification_executor:verify_node] ⚠️ Node {node_id} has no data - skipping verification")
                return {'success': False, 'has_verifications': False, 'message': 'Node not found in graph', 'results': []}
            
            print(f"[@lib:verification_executor:verify_node] ✅ Node data from graph: {node_data.get('label')} (tree: {node_data.get('tree_name')})")
            
            # Extract verifications from node
            verifications = node_data.get('verifications', [])

            # Guard: auto-deserialize if verifications is a JSON string (stale cache from double-encoding)
            if isinstance(verifications, str):
                try:
                    import json
                    verifications = json.loads(verifications)
                    print(f"[@lib:verification_executor:verify_node] ⚠️ Auto-deserialized verifications from JSON string for node {node_id}")
                except (json.JSONDecodeError, TypeError):
                    verifications = []

            if not verifications:
                # Fingerprint-verification toggle (mirror of the KPI fingerprint fallback): when a node
                # opts in via use_fingerprint_for_verification, verify it by its stored fingerprint
                # instead of refusing for lack of a hand-authored reference. OFF (default) = unchanged —
                # no verification runs (e.g. live nodes). Reuses the match_fingerprint image verification.
                if node_data.get('use_fingerprint_for_verification'):
                    _fp = node_data.get('__fingerprint') or {}
                    if _fp.get('dhash'):
                        verifications = [{'verification_type': 'image', 'command': 'match_fingerprint',
                                          'params': {'fingerprint': _fp, 'threshold': 14,
                                                     'node_label': node_data.get('label')}}]
                if not verifications:
                    print(f"[@lib:verification_executor:verify_node] No verifications for node {node_id} (fingerprint-verify off or no fingerprint)")
                    return {'success': False, 'has_verifications': False, 'message': 'No verifications defined - cannot verify position', 'results': []}
            
            # Extract verification_pass_condition from node (defaults to 'all')
            # Priority: 1) first verification's pass_condition, 2) node's pass_condition, 3) default 'all'
            if verifications and isinstance(verifications[0], dict) and 'verification_pass_condition' in verifications[0]:
                verification_pass_condition = verifications[0]['verification_pass_condition']
                print(f"[@lib:verification_executor:verify_node] Using pass_condition from verification data: '{verification_pass_condition}'")
            else:
                verification_pass_condition = node_data.get('verification_pass_condition', 'all')
                print(f"[@lib:verification_executor:verify_node] Using pass_condition from node data: '{verification_pass_condition}' (not embedded in verifications)")
            
            print(f"[@lib:verification_executor:verify_node] Executing {len(verifications)} verifications for node {node_id} with condition '{verification_pass_condition}'")
            
            # Use actual node's tree_id for database recording (nested tree)
            actual_tree_id = node_data.get('tree_id')
            
            # Execute verifications with proper tree_id and node_id for database recording
            return await self.execute_verifications(
                verifications=verifications,
                userinterface_name=userinterface_name,  # MANDATORY parameter
                image_source_url=image_source_url,
                team_id=team_id,
                tree_id=actual_tree_id,  # Use node's actual tree_id for recording
                node_id=node_id,
                verification_pass_condition=verification_pass_condition  # NEW: Pass condition from node
            )
            
        except Exception as e:
            print(f"[@lib:verification_executor:verify_node] Error: {e}")
            import traceback
            traceback.print_exc()
            return {'success': False, 'error': str(e), 'results': []}
    
    def _filter_valid_verifications(self, verifications: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Filter out invalid verifications"""
        valid_verifications = []
        
        for i, verification in enumerate(verifications):
            verification_type = verification.get('verification_type', 'text')
            
            if not verification.get('command') or verification.get('command', '').strip() == '':
                print(f"[@lib:verification_executor:_filter_valid_verifications] Removing verification {i}: No command specified")
                continue
            
            # Type-specific validation
            if verification_type == 'image':
                command = verification.get('command', '')
                # Icon commands run on the image controller but use a built-in glyph
                # (chosen via params.icon) instead of an R2/DB reference image.
                if command in ('waitForIconToAppear', 'waitForIconToDisappear'):
                    if not verification.get('params', {}).get('icon'):
                        print(f"[@lib:verification_executor:_filter_valid_verifications] Removing verification {i}: No icon specified")
                        continue
                    if not verification.get('params', {}).get('area'):
                        print(f"[@lib:verification_executor:_filter_valid_verifications] Removing verification {i}: icon verification needs an area")
                        continue
                elif not verification.get('params', {}).get('image_path'):
                    print(f"[@lib:verification_executor:_filter_valid_verifications] Removing verification {i}: No image reference specified")
                    continue
            elif verification_type == 'text':
                if not verification.get('params', {}).get('text'):
                    print(f"[@lib:verification_executor:_filter_valid_verifications] Removing verification {i}: No text specified")
                    continue
            elif verification_type == 'adb':
                if not verification.get('params', {}).get('search_term'):
                    print(f"[@lib:verification_executor:_filter_valid_verifications] Removing verification {i}: No search term specified")
                    continue
            elif verification_type == 'color':
                params = verification.get('params', {})
                if not params.get('color') or not params.get('area'):
                    print(f"[@lib:verification_executor:_filter_valid_verifications] Removing verification {i}: color verification needs 'color' and 'area' params")
                    continue

            valid_verifications.append(verification)
        
        return valid_verifications
    
    async def _execute_shared_window(self, valid_verifications: List[Dict[str, Any]],
                                     base_capture_path: str, window_timeout_s: float,
                                     userinterface_name: str, context, team_id: str,
                                     verification_pass_condition: str) -> Tuple[List[Dict[str, Any]], int]:
        """Check every leg against ONE shared frame window, frame by frame.

        Polls hot/captures once and, for each frame (oldest → newest), tests
        every eligible pending leg against that single frame (the per-leg check
        runs with timeout=0, so the controller scores exactly that frame). Each
        leg honors its OWN timeout as an eligibility window — a timeout=0 leg is
        scored only on the base frame, a timeout=3000 leg across the 3s window —
        so the same frames are shared without flattening every leg to the max
        timeout. Stops the instant the pass_condition is met: first match for
        'any', all legs matched for 'all'. Coherent and fast (early-exit).

        A per-batch reference cache is installed on the text/image controllers
        so each leg's reference resolves from the DB ONCE, not once per frame.

        Returns (results, passed_count): one result per leg in input order — the
        matching frame's result if it matched, else its last failure.
        """
        import copy

        n = len(valid_verifications)
        leg_result: List[Optional[Dict[str, Any]]] = [None] * n
        passed = [False] * n
        # Each leg keeps its OWN timeout as its eligibility window: a leg is
        # checked on the base frame always, then on later frames only while the
        # elapsed window time is within that leg's timeout. So a timeout=0 leg
        # (e.g. CONTINUE) is only ever checked on the immediate frame — never
        # dragged across a sibling's longer poll window.
        leg_timeout_s = [
            int((v.get('params', {}) or {}).get('timeout', 0) or 0) / 1000.0
            for v in valid_verifications
        ]

        def single_frame_leg(v):
            leg = copy.deepcopy(v)
            params = dict(leg.get('params', {}) or {})
            params['timeout'] = 0  # check exactly the frame we hand it; no internal polling
            leg['params'] = params
            return leg

        # Install a per-batch reference cache (cleared in finally). Every other
        # code path keeps _reference_cache = None → no caching, no staleness.
        cached_controllers = [c for c in (self.text_controller, self.image_controller) if c]
        for c in cached_controllers:
            c._reference_cache = {}

        try:
            hotdir_ctrl = self.text_controller or self.image_controller
            hot_dir = (hotdir_ctrl._derive_hot_captures_dir(base_capture_path)
                       if hotdir_ctrl else os.path.dirname(base_capture_path))
            try:
                floor_mtime = os.path.getmtime(base_capture_path)
            except OSError:
                floor_mtime = time.time()
            processed = {os.path.realpath(base_capture_path)}
            deadline = time.time() + window_timeout_s
            poll_interval_s = 0.05
            # Ordered list of every frame this window analyses — surfaced on each
            # result's details so a FAILED verification's report can render a mosaic
            # of the whole window (see scan_mosaic / _build_verification_report).
            analyzed_frames = [{'path': base_capture_path, 'mtime': floor_mtime}]

            print(f"[@lib:verification_executor:_execute_shared_window] {n} legs share one "
                  f"window (timeout {window_timeout_s:.1f}s, '{verification_pass_condition}'), polling {hot_dir}")

            window_start = time.time()  # reset just before frame 0 below

            async def check_frame(frame_path, is_first) -> bool:
                """Test each ELIGIBLE pending leg against one frame. Eligibility:
                always on the base frame, and on later frames only while elapsed
                window time is within that leg's own timeout. Return True once
                polling should stop — condition met, or (for 'all') no longer
                achievable because an unmatched leg's window has closed."""
                elapsed = 0.0 if is_first else (time.time() - window_start)
                for idx, verification in enumerate(valid_verifications):
                    if passed[idx]:
                        continue
                    if not is_first and elapsed > leg_timeout_s[idx]:
                        continue  # this leg's own timeout window has closed
                    t0 = time.time()
                    result = await self._execute_single_verification(
                        single_frame_leg(verification), userinterface_name,
                        frame_path, context, team_id,
                    )
                    result['execution_time_ms'] = int((time.time() - t0) * 1000)
                    leg_result[idx] = result  # latest result (a passing one wins)
                    if result.get('success'):
                        passed[idx] = True
                        if verification_pass_condition == 'any':
                            return True
                if verification_pass_condition != 'any':
                    if all(passed):
                        return True
                    # 'all' can't pass once every unmatched leg's window has closed.
                    if not is_first and all(
                        passed[idx] or elapsed > leg_timeout_s[idx] for idx in range(n)
                    ):
                        return True  # stop early — final passed_count records the FAIL
                return False

            # Frame 0 = the shared base capture.
            window_start = time.time()
            done = await check_frame(base_capture_path, is_first=True)

            # Then walk new frames as FFmpeg writes them, until satisfied/deadline.
            while not done and time.time() < deadline:
                new_files = []
                try:
                    with os.scandir(hot_dir) as entries:
                        for entry in entries:
                            name = entry.name
                            if not name.startswith('capture_') or not name.endswith('.jpg'):
                                continue
                            if 'thumbnail' in name:
                                continue
                            real = os.path.realpath(entry.path)
                            if real in processed:
                                continue
                            try:
                                mtime = entry.stat().st_mtime
                            except OSError:
                                continue
                            if mtime <= floor_mtime:
                                continue
                            new_files.append((mtime, entry.path, real))
                except FileNotFoundError:
                    break

                if not new_files:
                    time.sleep(poll_interval_s)
                    continue

                new_files.sort()
                for mtime, fp, real in new_files:
                    processed.add(real)
                    floor_mtime = max(floor_mtime, mtime)
                    analyzed_frames.append({'path': fp, 'mtime': mtime})
                    done = await check_frame(fp, is_first=False)
                    if done:
                        break
        finally:
            for c in cached_controllers:
                c._reference_cache = None

        # Build ordered results + count.
        results: List[Dict[str, Any]] = []
        passed_count = 0
        for idx, verification in enumerate(valid_verifications):
            r = leg_result[idx] or {
                'success': False,
                'command': verification.get('command'),
                'params': verification.get('params', {}),
                'verification_type': verification.get('verification_type', 'text'),
                'message': 'Not evaluated',
                'execution_time_ms': 0,
            }
            # Attach the window's frame list so a failing leg's report can show
            # the full analysed mosaic (cheap: shared reference, not a copy).
            r.setdefault('details', {})['analyzed_frames'] = analyzed_frames
            results.append(r)
            if r.get('success'):
                passed_count += 1

        print(f"[@lib:verification_executor:_execute_shared_window] "
              f"{passed_count}/{n} leg(s) matched within the window")
        return results, passed_count

    async def _execute_single_verification(self, verification: Dict[str, Any], userinterface_name: str, image_source_url: Optional[str], context = None, team_id: str = None) -> Dict[str, Any]:
        """Execute a single verification and return standardized result"""
        try:
            verification_type = verification.get('verification_type', 'text')
            
            # Get verification controller directly
            controller = getattr(self, f'{verification_type}_controller', None)
            if not controller:
                return {
                    'success': False,
                    'error': f'No {verification_type} verification controller found for device {self.device_id}',
                    'verification_type': verification_type,
                    'resultType': 'FAIL'
                }
            
            # Execute verification directly using controller
            verification_config = {
                'command': verification.get('command'),
                'params': verification.get('params', {}),
                'verification_type': verification_type,
                'team_id': team_id,  # Pass team_id for database operations
                'userinterface_name': userinterface_name  # Use mandatory parameter (no fallback)
            }
            
            # Add source_image_path to config if provided (for offline/post-processing)
            if image_source_url:
                import os
                from shared.src.lib.utils.build_url_utils import convertHostUrlToLocalPath
                
                # Helper function to check if path needs conversion
                def needs_conversion(path):
                    """Check if path is a URL/proxy path that needs conversion (vs already a local path).

                    `buildCaptureUrlFromPath` returns relative `/host/<host>/...` URLs (no scheme),
                    so the frontend echoes those back as `image_source_url`. They must be reversed
                    to local paths or the host-side `os.path.exists` check will fail.
                    """
                    # Strip query string before checking the prefix.
                    bare = path.split('?')[0] if isinstance(path, str) else path
                    return bare.startswith(('http://', 'https://', '/host/', '/stream/', '/captures/', '/resources/'))
                
                # Handle comma-separated paths (for multiple images in subtitle/audio detection)
                if isinstance(image_source_url, str) and ',' in image_source_url:
                    # Split comma-separated paths and convert each if needed
                    paths = [path.strip() for path in image_source_url.split(',')]
                    processed_paths = []
                    for path in paths:
                        if needs_conversion(path):
                            try:
                                converted_path = convertHostUrlToLocalPath(path.split('?')[0])
                                processed_paths.append(converted_path)
                                print(f"[@lib:verification_executor:_execute_single_verification] Converted URL: {path} -> {converted_path}")
                            except Exception as e:
                                print(f"[@lib:verification_executor:_execute_single_verification] Warning: Failed to convert path {path}: {e}")
                        else:
                            # Already a local path, use as-is
                            processed_paths.append(path)
                    
                    if processed_paths:
                        source_image_path = ','.join(processed_paths)
                        verification_config['source_image_path'] = source_image_path
                        print(f"[@lib:verification_executor:_execute_single_verification] Using {len(processed_paths)} image path(s)")
                    else:
                        print(f"[@lib:verification_executor:_execute_single_verification] Warning: No valid paths available")
                else:
                    # Single path
                    if needs_conversion(image_source_url):
                        try:
                            source_image_path = convertHostUrlToLocalPath(image_source_url.split('?')[0])
                            verification_config['source_image_path'] = source_image_path
                        except Exception as e:
                            print(f"[@lib:verification_executor:_execute_single_verification] Warning: Failed to convert path {image_source_url}: {e}")
                            verification_config['source_image_path'] = image_source_url
                    else:
                        # Already a local path, use as-is
                        verification_config['source_image_path'] = image_source_url
            
            # Set context on controller so helpers can access it (for motion image collection)
            if context:
                controller._current_context = context
            
            # Direct controller execution - handle both async (Playwright) and sync (ADB, Image, Text) controllers.
            #
            # Sync controllers run heavy native code (OpenCV template match,
            # tesseract OCR) that can take 0.3–1.5s per call. Running them
            # synchronously inside this async function would block the event
            # loop for that whole duration — which is fine for live
            # verification (no other task is waiting on the loop) but breaks
            # `asyncio.wait_for` deadlines in callers like kpi_executor's
            # _scan_until_match: the timeout callback can't fire while the
            # loop is blocked, so a 10s budget effectively becomes
            # "10s + however long the in-flight verifier takes to finish".
            #
            # `asyncio.to_thread` (Python 3.9+) hands the sync call to the
            # default thread pool and yields control back to the loop. The
            # function semantically still returns when the OCR finishes, but
            # now wait_for's timer task actually gets scheduled and cancellation
            # propagates cleanly. ~10μs spawn overhead from the thread pool.
            import inspect
            import asyncio

            if inspect.iscoroutinefunction(controller.execute_verification):
                # Async controller (e.g., Playwright)
                verification_result = await controller.execute_verification(verification_config)
            else:
                # Sync controller (e.g., ADB, Image, Text) — run in a thread
                # so the event loop stays responsive and wait_for can preempt.
                verification_result = await asyncio.to_thread(
                    controller.execute_verification, verification_config
                )
            
            # Build URLs from file paths if verification generated images
            # Frontend will process these paths using buildVerificationResultUrl from buildUrlUtils.ts
            details = verification_result.get('details', {})
            if details.get('source_image_path'):
                verification_result['sourceUrl'] = details['source_image_path']  # Local path - frontend converts to URL
            if details.get('reference_image_url'):
                verification_result['referenceUrl'] = details['reference_image_url']  # Already R2 URL
            elif details.get('reference_image_path'):
                # Icon verification renders the built-in glyph locally (no R2 reference).
                verification_result['referenceUrl'] = details['reference_image_path']  # Local path - frontend converts to URL
            if details.get('result_overlay_path'):
                verification_result['overlayUrl'] = details['result_overlay_path']  # Local path - frontend converts to URL
            
            # Capture screenshot (no upload). Sync I/O (HTTP to av_controller
            # / adb / disk read) — wrap in to_thread so the event loop stays
            # responsive. Without this, every per-frame screenshot blocks the
            # loop briefly and the cumulative blocking on a long scan partly
            # defeats the wait_for deadline.
            from shared.src.lib.utils.device_utils import capture_screenshot
            screenshot_path = await asyncio.to_thread(
                capture_screenshot, self.device, context
            ) or ""

            # `screenshot_path` is the per-leg evidence frame; it rides back on
            # this result's `screenshot_path` and the report derives its
            # verification_screenshots list from results (1:1), so there is no
            # separate accumulator to append to.

            # Build verification evidence for KPI report (NEW)
            verification_evidence = {
                'type': verification_type,
                'command': verification.get('command'),
                'success': verification_result.get('success', False),
                'params': verification.get('params', {}),
            }
            
            # Add type-specific evidence
            if verification_type == 'image':
                verification_evidence.update({
                    'reference_image_path': details.get('reference_image_path'),  # Local cropped reference
                    'source_image_path': details.get('source_image_path'),  # Local cropped source
                    'threshold': verification_result.get('user_threshold'),
                    'matching_score': verification_result.get('matching_result', 0.0),
                    # The ACTUAL area scanned (DB-resolved, with fuzzy fx/fy/fwidth/fheight)
                    # — the KPI card draws this rectangle on the full capture. Falls back
                    # to the edge's params.area only when no resolved area is present.
                    'search_area': details.get('resolved_area') or verification.get('params', {}).get('area'),
                    'image_filter': verification_result.get('imageFilter', 'none'),
                    # Focus detection (present only when the reference has area.focus)
                    'focus_score': details.get('focus_score'),
                    'focus_threshold': details.get('focus_threshold'),
                })
            elif verification_type == 'text':
                # Keys mirror the image branch so kpi_report_template's text card
                # can show "Score / Threshold" with the same lookup shape.
                verification_evidence.update({
                    'source_image_path': details.get('source_image_path'),
                    'searched_text': verification_result.get('searchedText', ''),
                    'extracted_text': verification_result.get('extractedText', ''),
                    'language': verification_result.get('detected_language', 'unknown'),
                    'confidence': verification_result.get('language_confidence', 0),
                    'threshold': verification_result.get('user_threshold'),
                    'matching_score': verification_result.get('matching_result', 0.0),
                    # OCR search area — the KPI card outlines it on the full capture,
                    # mirroring the image branch (and the verification failure report).
                    'search_area': details.get('resolved_area') or verification.get('params', {}).get('area'),
                    # Focus detection (present only when the text reference has area.focus)
                    'focus_score': details.get('focus_score'),
                    'focus_threshold': details.get('focus_threshold'),
                })

            flattened_result = {
                'success': verification_result.get('success', False),
                'message': verification_result.get('message'),
                'error': verification_result.get('error'),
                'threshold': verification_result.get('user_threshold'),
                'matching_result': verification_result.get('matching_result'),  # ✅ Add for report generator
                'resultType': 'PASS' if verification_result.get('success', False) else 'FAIL',
                'sourceImageUrl': verification_result.get('sourceUrl'),
                'referenceImageUrl': verification_result.get('referenceUrl'),
                'resultOverlayUrl': verification_result.get('overlayUrl'),
                # Focus detection (present only when the reference has area.focus)
                'focusScore': details.get('focus_score'),
                'focusThreshold': details.get('focus_threshold'),
                'extractedText': verification_result.get('extractedText', ''),
                'searchedText': verification_result.get('searchedText', ''),
                'imageFilter': verification_result.get('imageFilter', 'none'),
                'detectedLanguage': verification_result.get('detected_language'),
                'languageConfidence': verification_result.get('language_confidence'),
                # ADB-specific fields
                'search_term': verification_result.get('search_term'),
                'wait_time': verification_result.get('wait_time'),
                'total_matches': verification_result.get('total_matches'),
                'matches': verification_result.get('matches'),
                # Appium-specific fields
                'platform': verification_result.get('platform'),
                # Audio/Video-specific fields  
                'motion_threshold': verification_result.get('motion_threshold'),
                'duration': verification_result.get('duration'),
                'frequency': verification_result.get('frequency'),
                'audio_level': verification_result.get('audio_level'),
                # General fields
                'verification_type': verification_result.get('verification_type', verification_type),
                'execution_time_ms': verification_result.get('execution_time_ms'),
                'details': verification_result.get('details', {}),
                'screenshot_path': screenshot_path,  # Always present
                'verification_evidence': verification_evidence,  # ✅ NEW: Evidence data for KPI report
                'output_data': verification_result.get('output_data', {})  # ✅ Include output_data from controller (getMenuInfo, etc.)
            }
            
            # Clean up context reference to avoid memory leaks
            if hasattr(controller, '_current_context'):
                delattr(controller, '_current_context')
            
            # Stash config/details for potential report generation after batch
            # evaluation. Attached for both pass and fail (image/text only): the
            # failure path consumes it for failed legs, the opt-in success path
            # for passing legs (false-positive review). Cheap to always attach —
            # generation itself stays gated by the batch-level conditions.
            if verification_type in ['image', 'text']:
                flattened_result['_report_config'] = verification_config
                flattened_result['_report_details'] = flattened_result.get('details', {})
            
            return flattened_result
            
        except Exception as e:
            # EXCEPTION HANDLER: This should only trigger for unexpected crashes, not normal verification failures
            # Normal failures should return {'success': False} from the controller, not throw exceptions
            print(f"[@lib:verification_executor:_execute_single_verification] ⚠️ UNEXPECTED EXCEPTION in verification:")
            print(f"[@lib:verification_executor:_execute_single_verification]   Verification type: {verification.get('verification_type', 'unknown')}")
            print(f"[@lib:verification_executor:_execute_single_verification]   Command: {verification.get('command', 'unknown')}")
            print(f"[@lib:verification_executor:_execute_single_verification]   Exception: {str(e)}")
            print(f"[@lib:verification_executor:_execute_single_verification]   Full traceback:")
            import traceback
            traceback.print_exc()
            
            # Capture error screenshot but DON'T add to validation context (use context=None)
            # This screenshot is for debugging the exception, not for the validation report
            from shared.src.lib.utils.device_utils import capture_screenshot
            screenshot_path = capture_screenshot(self.device, context=None) or ""
            if screenshot_path:
                print(f"[@lib:verification_executor:_execute_single_verification] 📸 Exception screenshot captured (for debugging): {screenshot_path}")

            return {
                'success': False,
                'message': f"Verification execution failed with exception",
                'error': str(e),
                'verification_type': verification.get('verification_type', 'unknown'),
                'resultType': 'FAIL',
                'screenshot_path': screenshot_path  # Always present
            }
    
