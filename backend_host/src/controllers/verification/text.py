"""
Text Verification Controller

Clean text controller that uses helpers for all operations.
Provides route interfaces and core domain logic.
"""

import os
import re
import time
import cv2
from typing import Dict, Any, Optional, Tuple, List
from .text_helpers import TextHelpers


# Per-field self-healing rules for getMenuInfo.
# When a parsed value fails its regex, retry OCR on the same image with a
# character whitelist and pull the first regex match out of the cleaner pass.
# Keys are matched against parse_menu_info's normalized output
# (lowercase, spaces→_, () stripped).
_MENU_INFO_FIELD_RULES = [
    {
        'keys': ('serial number', 'seriennummer'),
        'regex': re.compile(r'\b[A-Fa-f0-9]{6}-[A-Z]+-\d+\b'),
        'whitelist': 'ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-',
    },
]


class TextVerificationController:
    """Pure text verification controller that uses OCR to detect text on screen."""
    
    def __init__(self, av_controller, **kwargs):
        """
        Initialize the Text Verification controller.
        
        Args:
            av_controller: AV controller for capturing images (dependency injection)
        """
        # Dependency injection
        from shared.src.lib.utils.storage_path_utils import get_capture_storage_path
        
        self.av_controller = av_controller
        
        # Use centralized path resolution (handles hot/cold storage automatically)
        self.captures_path = get_capture_storage_path(av_controller.video_capture_path, 'captures')
        
        # Set verification type for controller lookup
        self.verification_type = 'text'
        
        # Initialize helpers
        self.helpers = TextHelpers(self.captures_path)

        print(f"[@controller:TextVerification] Initialized with captures path: {self.captures_path}")
        
        # Controller is always ready

    def get_status(self) -> Dict[str, Any]:
        """Get the current status of the text verification controller."""
        return {
            "connected": True,
            "av_controller": self.av_controller.device_name if self.av_controller else None,
            "controller_type": "text",
            "captures_path": self.captures_path
        }

    def waitForTextToAppear(self, text: str, timeout: float = 10.0, area: dict = None,
                           image_list: List[str] = None,
                           verification_index: int = 0, image_filter: str = 'none',
                           threshold: float = 0.8) -> Tuple[bool, str, dict]:
        """
        Wait for specific text to appear either in provided image list or by capturing new frames.
        Supports pipe-separated terms for fallback (e.g., "Settings|Einstellungen|Paramètres").

        Args:
            text: Text pattern to look for (can use pipe-separated terms: "text1|text2|text3")
            timeout: Maximum time to wait in seconds
            area: Optional area to search (x, y, width, height)
            image_list: Optional list of source image paths to search
            verification_index: Index of verification for naming
            image_filter: Optional image filter to apply
            threshold: Match score required to pass (0.0-1.0). Default 0.8 mirrors
                image verification; pass 1.0 for the legacy strict-substring behavior.

        Returns:
            Tuple of (success, message, additional_data). `additional_data` always
            contains `matching_result` (best score seen across frames/terms) and
            `user_threshold`, in the same shape as image verification, so the
            executor + failure-report renderer can surface "Score X / Required Y".
        """
        # Check if text is provided
        if not text or text.strip() == '':
            error_msg = "No text specified. Please provide text to search for."
            print(f"[@controller:TextVerification] {error_msg}")
            return False, error_msg, {
                "searchedText": text or "",
                "image_filter": image_filter,
                "matching_result": 0.0,
                "user_threshold": threshold,
            }

        # SAFEGUARD: Cap timeout at reasonable maximum (30 seconds) to prevent infinite waits
        if timeout > 30:
            print(f"[@controller:TextVerification] WARNING: Timeout {timeout}s exceeds maximum (30s), capping at 30s")
            timeout = 30

        # Check if we have pipe-separated terms
        if '|' in text:
            terms = [term.strip() for term in text.split('|') if term.strip()]
            print(f"[@controller:TextVerification] Using fallback strategy with {len(terms)} terms: {terms}")
        else:
            terms = [text.strip()]
            print(f"[@controller:TextVerification] Looking for text pattern: '{text}' (threshold={threshold:.2f})")

        if image_filter and image_filter != 'none':
            print(f"[@controller:TextVerification] Using image filter: {image_filter}")

        # best_score tracks the closest miss across all frames AND all terms, so
        # the failure report shows "how close did we get". On success we overwrite
        # with the winning score (always >= threshold).
        best_score = 0.0

        additional_data = {
            "searchedText": text,  # Frontend-expected property name (original search term)
            "attempted_terms": terms,
            "image_filter": image_filter,
            "detected_language": 'en',
            "language_confidence": 0.0,
            "matching_result": best_score,
            "user_threshold": threshold,
        }
        
        # Focus gate (set only when this reference was captured with "Focus"):
        # a frame whose OCR passes is only a real hit if the learned colour accent
        # is also present in the padded text area — otherwise the text is shown but
        # NOT the selected/focused one.
        focus_params = area.get('focus') if isinstance(area, dict) else None
        if focus_params:
            additional_data["focus_threshold"] = float(
                focus_params.get('threshold', self._get_image_helpers().FOCUS_DEFAULT_THRESHOLD))

        if image_list:
            closest_text = ""
            best_source_path = None
            best_mtime = None
            # First/last frame snapshots for the wait-timeline failure report.
            first_info = None
            last_info = None
            # Focus tracking: best accent score seen, and whether any frame had the
            # text but failed the focus gate (drives the "found but NOT focused" msg).
            best_focus_score = 0.0
            text_ok_focus_failed = False
            base_path = image_list[0]
            try:
                base_mtime = os.path.getmtime(base_path)
            except OSError:
                base_mtime = time.time()

            def _attempt(source_path, match_index, mtime=None):
                """Run OCR on one capture; update closest_text/best_source_path/best_score; return (success, return_tuple_or_None).

                On match returns (True, response_tuple_to_propagate_to_caller).
                On no-match returns (False, None) and the caller continues polling/walking.
                """
                nonlocal closest_text, best_source_path, best_score, best_mtime, first_info, last_info
                nonlocal best_focus_score, text_ok_focus_failed
                if not os.path.exists(source_path):
                    return False, None

                if best_source_path is None:
                    best_source_path = source_path

                extracted_text, lang_code, lang_conf = self._extract_text_from_area(source_path, area, image_filter)
                stripped = extracted_text.strip()

                # Score every candidate term against this frame; keep the best.
                # We need the *frame's* best (to decide success vs miss) AND the
                # *run's* best (to populate matching_result for the failure report).
                frame_best_score = 0.0
                frame_best_term = terms[0]
                for term in terms:
                    s = self.helpers.text_match_score(extracted_text, term)
                    if s > frame_best_score:
                        frame_best_score = s
                        frame_best_term = term

                # First/last snapshots (each frame carries its own extracted OCR text,
                # so the timeline shows what the screen actually read at start vs end).
                frame_mtime = mtime if mtime is not None else base_mtime
                frame_snapshot = {'path': source_path, 'score': frame_best_score,
                                  'text': stripped, 'mtime': frame_mtime}
                if first_info is None:
                    first_info = frame_snapshot
                last_info = frame_snapshot

                # Update "closest miss" snapshot when this frame is closer than
                # anything we've seen. Length is a tiebreaker so the report
                # doesn't lock onto a tiny extraction when nothing scored.
                if (frame_best_score > best_score) or (
                    frame_best_score == best_score and len(stripped) > len(closest_text)
                ):
                    closest_text = stripped
                    best_source_path = source_path
                    best_score = frame_best_score
                    best_mtime = frame_mtime
                    additional_data["detected_language"] = lang_code
                    additional_data["language_confidence"] = lang_conf
                    additional_data["matching_result"] = best_score

                if frame_best_score >= threshold:
                    term = frame_best_term
                    # Focus gate: text is present, but is it the SELECTED label?
                    focus_score = None
                    if focus_params:
                        focus_pass, focus_score = self._check_text_focus(source_path, area, focus_params)
                        if focus_score is not None and focus_score > best_focus_score:
                            best_focus_score = focus_score
                        if not focus_pass:
                            # Present but not focused — keep looking across frames.
                            text_ok_focus_failed = True
                            return False, None
                    if len(terms) > 1:
                        print(f"[@controller:TextVerification] Best of {len(terms)} terms: '{term}' "
                              f"score={frame_best_score:.3f} >= threshold={threshold:.3f}")
                    print(f"[@controller:TextVerification] SUCCESS: Text matched on '{term}' "
                          f"in {source_path}: extracted='{stripped}' score={frame_best_score:.3f}")
                    if area:
                        cropped = self._save_cropped_source_image(source_path, area, verification_index)
                        additional_data["source_image_path"] = cropped or source_path
                    else:
                        additional_data["source_image_path"] = source_path
                    if match_index is not None and match_index > 0:
                        try:
                            match_timestamp = os.path.getmtime(source_path)
                        except OSError:
                            match_timestamp = None
                        if match_timestamp is not None:
                            additional_data["kpi_match_timestamp"] = match_timestamp
                        additional_data["kpi_match_index"] = match_index
                        print(f"[@controller:TextVerification] KPI: Match at index {match_index}")
                    additional_data["extractedText"] = stripped
                    additional_data["successful_term"] = term
                    additional_data["fallback_strategy"] = len(terms) > 1
                    additional_data["detected_language"] = lang_code
                    additional_data["language_confidence"] = lang_conf
                    additional_data["matching_result"] = frame_best_score
                    focus_info = ""
                    if focus_params:
                        additional_data["focus_score"] = focus_score
                        ft = float(focus_params.get('threshold',
                                                    self._get_image_helpers().FOCUS_DEFAULT_THRESHOLD))
                        focus_info = f", focus: {focus_score:.3f} (required: {ft:.2f})"
                    return True, (
                        True,
                        f"Text pattern '{text}' found using term '{term}' "
                        f"(score {frame_best_score:.3f} >= threshold {threshold:.3f}){focus_info}: '{stripped}'",
                        additional_data,
                    )
                return False, None

            # Score the initial shared capture first.
            ok, response = _attempt(base_path, match_index=0, mtime=base_mtime)
            if ok:
                return response

            # Two iteration modes (mirrors image controller):
            # 1) Multi-element image_list / timeout==0: walk the provided slice.
            # 2) Single-element + timeout>0: poll the hot/captures dir for NEW
            #    frames as FFmpeg writes them (cold/captures only contains
            #    explicitly-promoted frames from take_screenshot, so the old
            #    sequential-index expansion never saw post-action captures).
            if timeout > 0 and len(image_list) == 1:
                hot_dir = self._derive_hot_captures_dir(base_path)
                try:
                    floor_mtime = os.path.getmtime(base_path)
                except OSError:
                    floor_mtime = time.time()

                processed = {os.path.realpath(base_path)}
                deadline = time.time() + timeout
                poll_interval_s = 0.05
                match_index = 0

                print(f"[@controller:TextVerification] Polling {hot_dir} for new captures (timeout: {timeout}s)")

                while time.time() < deadline:
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
                        match_index += 1
                        ok, response = _attempt(fp, match_index=match_index, mtime=mtime)
                        if ok:
                            return response
            else:
                for idx, source_path in enumerate(image_list[1:], start=1):
                    try:
                        ts = os.path.getmtime(source_path)
                    except OSError:
                        ts = None
                    ok, response = _attempt(source_path, match_index=idx, mtime=ts)
                    if ok:
                        return response

            # ALWAYS save the best source for comparison (same as image verification)
            if best_source_path:
                if area:
                    cropped_source_path = self._save_cropped_source_image(best_source_path, area, verification_index)
                    if cropped_source_path:
                        additional_data["source_image_path"] = cropped_source_path
                    else:
                        # Fallback to original if cropping failed
                        additional_data["source_image_path"] = best_source_path
                else:
                    # No area - use original source image
                    additional_data["source_image_path"] = best_source_path

                # Wait-timeline evidence: when we polled new captures over the timeout
                # window, expose first / closest-match / last frames (each with its own
                # extracted OCR text) so the report shows how the screen evolved.
                if timeout > 0 and len(image_list) == 1:
                    best_info = {'path': best_source_path, 'score': best_score,
                                 'text': closest_text,
                                 'mtime': best_mtime if best_mtime is not None else base_mtime}
                    additional_data["frames"] = self._build_text_wait_frames(
                        base_mtime,
                        [('first', first_info), ('best', best_info), ('last', last_info)],
                        area, verification_index,
                        best_crop=additional_data.get("source_image_path"),
                    )

            # Set failure data
            additional_data["extractedText"] = closest_text  # Frontend-expected property name
            additional_data["matching_result"] = best_score  # best across all frames+terms
            # Distinguish "text never matched" from "text matched but never focused"
            # (mirrors image's focus failure message).
            if focus_params and text_ok_focus_failed:
                ft = float(focus_params.get('threshold',
                                            self._get_image_helpers().FOCUS_DEFAULT_THRESHOLD))
                additional_data["focus_score"] = best_focus_score
                return (
                    False,
                    f"Text pattern '{text}' found but element is NOT focused — "
                    f"focus: {best_focus_score:.3f} (required: {ft:.2f})",
                    additional_data,
                )
            return (
                False,
                f"Text pattern '{text}' not found (best score {best_score:.3f} < threshold {threshold:.3f})",
                additional_data,
            )

        else:
            # Capture new image if no image list provided
            print(f"[@controller:TextVerification] No image list provided, using single screenshot")

            # Take screenshot (already taken in execute_verification)
            capture_path = self.av_controller.take_screenshot()
            if not capture_path:
                return False, "Failed to capture screen for text verification", additional_data

            # Extract text from area
            extracted_text, lang_code, lang_conf = self._extract_text_from_area(capture_path, area, image_filter)
            additional_data["detected_language"] = lang_code
            additional_data["language_confidence"] = lang_conf

            # Score every candidate term; pick the best, same as image_list branch.
            frame_best_score = 0.0
            frame_best_term = terms[0]
            for term in terms:
                s = self.helpers.text_match_score(extracted_text, term)
                if s > frame_best_score:
                    frame_best_score = s
                    frame_best_term = term
            additional_data["matching_result"] = frame_best_score

            # ALWAYS save source for comparison (same as image verification) —
            # both branches need it for the failure-report composite.
            if area:
                cropped_source_path = self._save_cropped_source_image(capture_path, area, verification_index)
                additional_data["source_image_path"] = cropped_source_path or capture_path
            else:
                additional_data["source_image_path"] = capture_path
            additional_data["extractedText"] = extracted_text.strip()

            if frame_best_score >= threshold:
                # Focus gate (mirrors the image_list branch): text present, but selected?
                if focus_params:
                    focus_pass, focus_score = self._check_text_focus(capture_path, area, focus_params)
                    additional_data["focus_score"] = focus_score
                    if not focus_pass:
                        ft = float(focus_params.get('threshold',
                                                    self._get_image_helpers().FOCUS_DEFAULT_THRESHOLD))
                        return (
                            False,
                            f"Text pattern '{text}' found but element is NOT focused — "
                            f"focus: {focus_score:.3f} (required: {ft:.2f})",
                            additional_data,
                        )
                print(f"[@controller:TextVerification] Text matched in captured frame: "
                      f"term='{frame_best_term}' score={frame_best_score:.3f} extracted='{extracted_text.strip()}'")
                return (
                    True,
                    f"Text pattern '{text}' found using term '{frame_best_term}' "
                    f"(score {frame_best_score:.3f} >= threshold {threshold:.3f}): '{extracted_text.strip()}'",
                    additional_data,
                )
            return (
                False,
                f"Text pattern '{text}' not found (best score {frame_best_score:.3f} < threshold {threshold:.3f})",
                additional_data,
            )

    def waitForTextToDisappear(self, text: str, timeout: float = 10.0, area: dict = None,
                              image_list: List[str] = None,
                              verification_index: int = 0, image_filter: str = 'none',
                              threshold: float = 0.8) -> Tuple[bool, str, dict]:
        """Wait for text to disappear - checks all images.

        Same `threshold` semantics as waitForTextToAppear: a frame counts as
        "text present" iff its match score >= threshold. Both the per-frame
        `matching_result` and the threshold flow through into additional_data
        so the failure report can show Score / Required like image verification.
        """
        if not text or text.strip() == '':
            error_msg = "No text specified. Please provide text to search for."
            print(f"[@controller:TextVerification] {error_msg}")
            return False, error_msg, {
                "searchedText": text or "",
                "image_filter": image_filter,
                "matching_result": 0.0,
                "user_threshold": threshold,
            }

        # SAFEGUARD: Cap timeout at reasonable maximum (30 seconds) to prevent infinite waits
        if timeout > 30:
            print(f"[@controller:TextVerification] WARNING: Timeout {timeout}s exceeds maximum (30s), capping at 30s")
            timeout = 30

        print(f"[@controller:TextVerification] Looking for text pattern to disappear: '{text}' (threshold={threshold:.2f})")

        # Expand image_list based on timeout
        images_to_check = image_list.copy() if image_list else []

        if timeout > 0 and len(image_list) == 1:
            fps = getattr(self.av_controller, 'screenshot_fps', 5)
            max_images = int(timeout * fps)

            base_path = image_list[0]
            for i in range(1, max_images):
                next_path = self._get_next_capture(base_path, i)
                if next_path:
                    images_to_check.append(next_path)

        # Check all images
        found_in_any = False
        last_found_idx = -1
        wait_ms = int(1000 / getattr(self.av_controller, 'screenshot_fps', 5)) if timeout > 0 else 0
        additional_data = {
            "searchedText": text,
            "image_filter": image_filter,
            "matching_result": 0.0,
            "user_threshold": threshold,
        }

        for idx, source_path in enumerate(images_to_check):
            if idx > 0 and not os.path.exists(source_path):
                if wait_ms > 0:
                    time.sleep(wait_ms / 1000.0)

            if not os.path.exists(source_path):
                continue

            found, message, check_data = self.waitForTextToAppear(
                text, 0, area, [source_path], verification_index,
                image_filter, threshold,
            )

            additional_data.update(check_data)
            # user_threshold is the run's threshold, not the inner call's — keep it sticky.
            additional_data["user_threshold"] = threshold

            if found:
                found_in_any = True
                last_found_idx = idx
        
        success = not found_in_any
        
        # KPI: If disappeared after first check
        if success and last_found_idx >= 0 and last_found_idx < len(images_to_check) - 1:
            disappear_path = images_to_check[last_found_idx + 1]
            if os.path.exists(disappear_path):
                additional_data["kpi_match_timestamp"] = os.path.getmtime(disappear_path)
                additional_data["kpi_match_index"] = last_found_idx + 1
                print(f"[@controller:TextVerification] KPI: Disappeared at index {last_found_idx + 1}")
        
        if success:
            return True, f"Text disappeared", additional_data
        else:
            return False, f"Text still present", additional_data

    def waitForTextToAppearThenDisappear(self, text: str, timeout: float = 10.0, area: dict = None,
                                         image_list: List[str] = None,
                                         verification_index: int = 0, image_filter: str = 'none',
                                         threshold: float = 0.8) -> Tuple[bool, str, dict]:
        """Wait for text to appear then disappear within a single timeout window.

        Text mirror of ImageVerification.waitForImageToAppearThenDisappear: a
        state machine (WAITING_FOR_APPEAR → WAITING_FOR_DISAPPEAR) walks every
        frame in the window. Both events must occur within `timeout`. Per-frame
        presence is evaluated by waitForTextToAppear(text, 0, …) so threshold /
        OCR semantics match the plain appear verification exactly.

        On success, additional_data carries `kpi_appear_timestamp` /
        `kpi_appear_index` (the action→appear anchor the KPI executor reads) and
        `kpi_disappear_timestamp` / `kpi_disappear_index`.
        """
        if not text or text.strip() == '':
            error_msg = "No text specified. Please provide text to search for."
            print(f"[@controller:TextVerification] {error_msg}")
            return False, error_msg, {
                "searchedText": text or "",
                "image_filter": image_filter,
                "matching_result": 0.0,
                "user_threshold": threshold,
            }

        # SAFEGUARD: Cap timeout at reasonable maximum (30 seconds)
        if timeout > 30:
            print(f"[@controller:TextVerification] WARNING: Timeout {timeout}s exceeds maximum (30s), capping at 30s")
            timeout = 30

        print(f"[@controller:TextVerification] Waiting for text to appear then disappear: '{text}' "
              f"(timeout: {timeout}s, threshold={threshold:.2f})")

        # Walk captures forward bounded by the WALL-CLOCK `timeout` (not a fixed
        # `timeout × screenshot_fps` frame count, which under-scans whenever the real
        # grabber rate exceeds screenshot_fps — see
        # ImageVerification.waitForImageToAppearThenDisappear).
        fps = getattr(self.av_controller, 'screenshot_fps', 5)
        poll_s = max(0.02, 1.0 / fps) if fps > 0 else 0.05
        frame_grace_s = max(1.0, 4 * poll_s)  # per-frame wait cap: skip a dropped frame number, don't block the scan
        explicit_frames = image_list if (image_list and len(image_list) > 1) else None
        base_path = image_list[0] if image_list else None
        deadline = time.time() + timeout if timeout > 0 else None

        # State machine
        state = "WAITING_FOR_APPEAR"
        appear_index = None
        appear_timestamp = None
        appear_source_path = None
        disappear_index = None
        disappear_timestamp = None

        additional_data = {
            "searchedText": text,
            "image_filter": image_filter,
            "matching_result": 0.0,
            "user_threshold": threshold,
        }

        idx = 0
        while True:
            if explicit_frames is not None:
                if idx >= len(explicit_frames):
                    break
                source_path = explicit_frames[idx]
            else:
                source_path = base_path if idx == 0 else (self._get_next_capture(base_path, idx) if base_path else None)
            if not source_path:
                break

            if idx > 0 and explicit_frames is None and deadline is not None:
                frame_deadline = min(deadline, time.time() + frame_grace_s)
                while not os.path.exists(source_path) and time.time() < frame_deadline:
                    time.sleep(min(poll_s, max(0.0, frame_deadline - time.time())))

            if os.path.exists(source_path):
                present, _msg, check_data = self.waitForTextToAppear(
                    text, 0, area, [source_path], verification_index,
                    image_filter, threshold,
                )
                additional_data.update(check_data)
                additional_data["user_threshold"] = threshold  # sticky: run threshold, not inner call's

                if state == "WAITING_FOR_APPEAR":
                    if present:
                        state = "WAITING_FOR_DISAPPEAR"
                        appear_index = idx
                        appear_source_path = source_path
                        try:
                            appear_timestamp = os.path.getmtime(source_path)
                        except OSError:
                            appear_timestamp = None
                        print(f"[@controller:TextVerification] Text APPEARED at frame {idx}")
                elif state == "WAITING_FOR_DISAPPEAR":
                    if not present:
                        disappear_index = idx
                        try:
                            disappear_timestamp = os.path.getmtime(source_path)
                        except OSError:
                            disappear_timestamp = None
                        print(f"[@controller:TextVerification] Text DISAPPEARED at frame {idx}")
                        additional_data["kpi_appear_timestamp"] = appear_timestamp
                        additional_data["kpi_appear_index"] = appear_index
                        additional_data["kpi_disappear_timestamp"] = disappear_timestamp
                        additional_data["kpi_disappear_index"] = disappear_index
                        message = (f"Text appeared at frame {appear_index} and disappeared "
                                   f"at frame {disappear_index}")
                        return True, message, additional_data

            idx += 1
            if explicit_frames is None and (deadline is None or time.time() >= deadline):
                break

        # Failed — distinguish "never appeared" from "appeared but never left"
        if state == "WAITING_FOR_APPEAR":
            return False, f"Text never appeared within {timeout}s timeout", additional_data
        else:
            additional_data["kpi_appear_timestamp"] = appear_timestamp
            additional_data["kpi_appear_index"] = appear_index
            return False, (f"Text appeared at frame {appear_index} but never disappeared "
                           f"within timeout"), additional_data

    def detect_text(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Route interface for text detection."""
        try:
            # Use the controller's helper instance instead of creating a new one
            helpers = self.helpers
            
            # Get source filename from frontend
            image_source_url = data.get('image_source_url', '')
            area = data.get('area')
            
            if not image_source_url:
                return {'success': False, 'message': 'image_source_url is required'}
            
            print(f"[@controller:TextVerification] Detecting text in: {image_source_url}")
            
            # Handle URL-to-path conversion the same way as image verification
            if image_source_url.startswith(('http://', 'https://')):
                # URL case - download first
                image_source_path = helpers.download_image(image_source_url)
                print(f"[@controller:TextVerification] Downloaded image to: {image_source_path}")
            else:
                # Local filename case - use URL conversion utility like image verification
                try:
                    from shared.src.lib.utils.build_url_utils import convertHostUrlToLocalPath
                    from shared.src.lib.utils.storage_path_utils import get_cold_storage_path, get_capture_folder
                    
                    # Strip query parameters from filename (e.g., ?t=timestamp)
                    clean_filename = image_source_url.split('?')[0]
                    
                    # Build a proper URL first if it's just a filename
                    if not clean_filename.startswith('/'):
                        # Assume it's a filename from captures directory
                        image_source_path = os.path.join(self.captures_path, clean_filename)
                    else:
                        # Use URL conversion utility
                        image_source_path = convertHostUrlToLocalPath(clean_filename)
                    
                    print(f"[@controller:TextVerification] Resolved path: {image_source_path}")
                    
                    # Check hot storage first, then cold storage
                    if not os.path.exists(image_source_path):
                        # Try cold storage
                        device_folder = get_capture_folder(self.captures_path)
                        cold_path = os.path.join(get_cold_storage_path(device_folder, 'captures'), os.path.basename(image_source_path))
                        if os.path.exists(cold_path):
                            image_source_path = cold_path
                            print(f"[@controller:TextVerification] Found in cold storage: {cold_path}")
                        else:
                            return {'success': False, 'message': f'Local file not found in hot or cold: {image_source_path}'}
                        
                except Exception as e:
                    print(f"[@controller:TextVerification] Path resolution error: {e}")
                    return {'success': False, 'message': f'Path resolution failed: {str(e)}'}
            
            # Detect text in area (includes crop, filter, OCR, language detection)
            result = helpers.detect_text_in_area(image_source_path, area)
            
            if not result.get('extracted_text'):
                return {'success': False, 'message': 'No text detected in image', **result}
            
            return {
                'success': True,
                'source_was_url': image_source_url.startswith(('http://', 'https://')),
                'image_source_path': image_source_path,
                **result
            }
            
        except Exception as e:
            print(f"[@controller:TextVerification] Error in detect_text: {str(e)}")
            return {'success': False, 'message': f'Text detection failed: {str(e)}'}
    
    def save_text(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Route interface for saving text references."""
        try:
            text = data.get('text', '')
            reference_name = data.get('reference_name', 'text_reference')
            area = data.get('area')
            team_id = data.get('team_id')
            shared = bool(data.get('shared', False))
            
            if not text:
                return {'success': False, 'message': 'text is required for saving reference'}
            
            # Get userinterface_name from request data (frontend provides it)
            userinterface_name = data.get('userinterface_name')
            
            if not userinterface_name:
                return {'success': False, 'message': 'userinterface_name is required for saving reference'}
            
            if not team_id:
                return {'success': False, 'message': 'team_id is required for saving reference'}

            # Focus accent ("Focus" tick): learn the selected-state colour accent so
            # verify can gate on "is this the SELECTED label", not just "text present".
            # The accent is stored inside area['focus'] (travels with the reference,
            # same as image). check_focus is tri-state:
            #   True  → learn from the (padded) source frame now.
            #   False → user unticked: drop any stored accent.
            #   None  → not specified (e.g. the node-save sync, which carries no
            #           frame): preserve a previously-learned accent so it isn't
            #           silently dropped.
            check_focus = data.get('check_focus', None)
            image_source_url = data.get('image_source_url')
            focus_warning = None
            if isinstance(area, dict):
                if check_focus is True and image_source_url:
                    learned, focus_warning = self._learn_text_focus(image_source_url, area)
                    if learned:
                        area['focus'] = learned
                    else:
                        area.pop('focus', None)
                elif check_focus is True and not image_source_url:
                    focus_warning = "Focus requested but no source frame was provided to learn the accent."
                    area.pop('focus', None)
                elif check_focus is False:
                    area.pop('focus', None)
                elif 'focus' not in area:
                    existing = self._resolve_text_area_cached(reference_name, userinterface_name, team_id)
                    if existing and isinstance(existing, dict) and existing.get('focus'):
                        area['focus'] = existing['focus']
                        print(f"[@controller:TextVerification] Preserved existing focus accent for '{reference_name}'")

            # Save text reference using helpers (handles database save)
            save_result = self.helpers.save_text_reference(text, reference_name, userinterface_name, team_id, area, shared=shared)

            if not save_result.get('success'):
                return {
                    'success': False,
                    'message': save_result.get('error', 'Failed to save text reference')
                }

            return {
                'success': True,
                'message': f'Text reference saved successfully: {reference_name}',
                'reference_name': save_result.get('reference_name'),
                'reference_id': save_result.get('reference_id'),
                'text_data': save_result.get('text_data'),
                'area': area,  # includes area['focus'] when focus was learned
                'focus_learned': bool(isinstance(area, dict) and area.get('focus')),
                'focus_warning': focus_warning,
            }
            
        except Exception as e:
            return {'success': False, 'message': f'Text save failed: {str(e)}'}
    
    def execute_verification(self, verification_config: Dict[str, Any]) -> Dict[str, Any]:
        """Route interface for executing verification."""
        try:
            # Check if a source image path is provided in the config
            source_path = verification_config.get('source_image_path')
            
            if source_path:
                print(f"[@controller:TextVerification] Using provided source image: {source_path}")
                # Validate the provided source image exists
                if not os.path.exists(source_path):
                    return {
                        'success': False,
                        'message': f'Provided source image not found: {source_path}',
                        'screenshot_path': None
                    }
            else:
                # Fallback: automatically capture screenshot from AV controller
                print(f"[@controller:TextVerification] No source image provided, capturing screenshot automatically")
                source_path = self.av_controller.take_screenshot()
                if not source_path or not os.path.exists(source_path):
                    return {
                        'success': False,
                        'message': 'Failed to capture screenshot automatically for text verification',
                        'screenshot_path': None
                    }
                print(f"[@controller:TextVerification] Using automatically captured screenshot: {source_path}")
                # Persist the captured original path so downstream consumers (failure-report
                # generator) can upload it alongside the cropped source.
                verification_config['source_image_path'] = source_path
            
            # Extract parameters from nested structure
            params = verification_config.get('params', {})
            command = verification_config.get('command', 'waitForTextToAppear')
            
            # Check if this is getMenuInfo (different parameter requirements)
            if command == 'getMenuInfo':
                # Get Menu Info: OCR + parse key-values + auto-store to metadata
                area = params.get('area')
                # Optional char whitelist (forces OCR to emit only these chars).
                # Accept either 'char_whitelist' or 'ocr_whitelist' as the param key.
                char_whitelist = params.get('char_whitelist') or params.get('ocr_whitelist')
                context = verification_config.get('context')
                menu_result = self.getMenuInfo(area=area, context=context, source_path=source_path, char_whitelist=char_whitelist)
                
                # Convert to standard verification format for consistent logging
                return {
                    'success': menu_result['success'],
                    'message': menu_result['message'],
                    'screenshot_path': source_path,
                    'output_data': menu_result.get('output_data', {}),
                    'details': menu_result.get('output_data', {})  # For route processing
                }
            
            # Required parameters for standard text verifications
            text = params.get('text', '')
            if not text:
                return {
                    'success': False,
                    'message': 'No text specified for text verification',
                    'details': {'error': 'Missing text parameter'}
                }
            
            # Optional parameters with defaults.
            # `timeout` from params is in MILLISECONDS (matches the rest of the surface).
            # Internal waitForTextToAppear/Disappear uses seconds; convert at the boundary.
            # Default 0 = single-shot (no polling). Sub-second precision preserved as float.
            timeout = float(params.get('timeout', 0)) / 1000.0
            area = params.get('area')
            image_filter = params.get('image_filter', 'none')
            # Match score threshold. Default 0.8 mirrors image verification.
            # Floor 0.7 enforced server-side per project convention (see
            # feedback_image_threshold_floor memo — recapture references rather
            # than dropping below 0.7). Above 1.0 capped to 1.0 (strict mode).
            threshold = float(params.get('threshold', 0.8))
            if threshold < 0.7:
                print(f"[@controller:TextVerification] WARNING: threshold {threshold} below floor 0.7, clamping")
                threshold = 0.7
            elif threshold > 1.0:
                threshold = 1.0
            
            # Extract userinterface_name and team_id for reference resolution (NO LEGACY device_model)
            userinterface_name = verification_config.get('userinterface_name')
            team_id = verification_config.get('team_id')
            
            # ✅ PRIORITY: Always resolve reference_name FIRST (single source of truth)
            # Get reference_name and resolve area from verifications_references table
            area = None
            reference_name = params.get('reference_name')
            
            if reference_name:
                # ALWAYS resolve from verifications_references table (DB is source of truth)
                resolved_area = self._resolve_text_area_cached(reference_name, userinterface_name, team_id)
                if resolved_area:
                    area = resolved_area
                    print(f"[@controller:TextVerification] ✅ Resolved area from reference '{reference_name}': {resolved_area}")
                    # The search text is stored INSIDE the reference's area dict
                    # (see save_text_reference: extended_area = {**area, 'text': text}).
                    # Treat the reference as the single source of truth for the text
                    # too — same as the area above. Otherwise editing a reference's
                    # text wouldn't take effect until every node/edge embedding it is
                    # re-saved (the inline params.text snapshot goes stale, which is
                    # exactly the goto-uses-old-text desync).
                    resolved_text = resolved_area.get('text')
                    if resolved_text:
                        if resolved_text != text:
                            print(f"[@controller:TextVerification] ✅ Resolved search text from reference '{reference_name}': '{resolved_text}' (inline snapshot was: '{text}')")
                        text = resolved_text
                else:
                    print(f"[@controller:TextVerification] ⚠️ Warning: No area found for reference '{reference_name}'")
            
            # Fallback to params['area'] ONLY if no reference_name (backward compatibility)
            if not area:
                area = params.get('area')
                if area:
                    print(f"[@controller:TextVerification] Using hardcoded area (no reference): {area}")
            
            print(f"[@controller:TextVerification] Executing {command} with text: '{text}'")
            print(f"[@controller:TextVerification] Parameters: timeout={timeout}, area={area}, filter={image_filter}")
            print(f"[@controller:TextVerification] Using source image: {source_path}")
            
            # Execute verification based on command
            if command == 'waitForTextToAppear':
                success, message, details = self.waitForTextToAppear(
                    text=text,
                    timeout=timeout,
                    area=area,
                    image_list=[source_path],  # Use source_path as image list
                    verification_index=0,
                    image_filter=image_filter,
                    threshold=threshold,
                )
            elif command == 'waitForTextToDisappear':
                success, message, details = self.waitForTextToDisappear(
                    text=text,
                    timeout=timeout,
                    area=area,
                    image_list=[source_path],  # Use source_path as image list
                    verification_index=0,
                    image_filter=image_filter,
                    threshold=threshold,
                )
            elif command == 'waitForTextToAppearThenDisappear':
                success, message, details = self.waitForTextToAppearThenDisappear(
                    text=text,
                    timeout=timeout,
                    area=area,
                    image_list=[source_path],  # Use source_path as image list
                    verification_index=0,
                    image_filter=image_filter,
                    threshold=threshold,
                )
            else:
                return {'success': False, 'message': f'Unsupported verification command: {command}'}

            # Return frontend-expected format (consistent with image verification).
            # `matching_result` + `user_threshold` mirror image's keys exactly so
            # verification_executor.py renames user_threshold→threshold for the
            # failure-report renderer without any text-specific branching.
            return {
                'success': success,
                'message': message,
                'screenshot_path': source_path,
                'image_filter': details.get('image_filter', image_filter),  # Applied filter
                'matching_result': details.get('matching_result', 0.0),  # Best 0.0-1.0 score
                'user_threshold': details.get('user_threshold', threshold),  # User's threshold
                'extractedText': details.get('extractedText', ''),       # Frontend-expected property name
                'searchedText': details.get('searchedText', text),       # Frontend-expected property name
                'detected_language': details.get('detected_language', 'en'),
                'language_confidence': details.get('language_confidence', 0.0),
                'focus_score': details.get('focus_score'),          # accent coverage (None if no focus gate)
                'focus_threshold': details.get('focus_threshold'),  # required accent coverage
                'details': details  # Keep for route processing, will be removed by route
            }
                
        except Exception as e:
            print(f"[@controller:TextVerification] Execution error: {e}")
            return {
                'success': False,
                'message': f'Text verification execution error: {str(e)}',
                'screenshot_path': source_path if 'source_path' in locals() else None
            }

    def get_available_verifications(self) -> list:
        """Get list of available verification types with typed parameters."""
        from shared.src.lib.schemas.param_types import create_param, create_output, ParamType, OutputType
        
        return [
            {
                "command": "waitForTextToAppear",
                "label": "Wait for Text to Appear",
                "description": "Wait for specific text to appear on screen using OCR",
                "params": {
                    "text": create_param(
                        ParamType.STRING,
                        required=True,
                        default="",
                        description="Text to search for",
                        placeholder="Enter text to detect"
                    ),
                    "timeout": create_param(
                        ParamType.NUMBER,
                        required=False,
                        default=0,
                        description="Maximum time to wait (seconds)"
                    ),
                    "area": create_param(
                        ParamType.AREA,
                        required=False,
                        default=None,
                        description="Screen area to search in"
                    )
                },
                "verification_type": "text"
            },
            {
                "command": "waitForTextToDisappear",
                "label": "Wait for Text to Disappear",
                "description": "Wait for specific text to disappear from screen using OCR",
                "params": {
                    "text": create_param(
                        ParamType.STRING,
                        required=True,
                        default="",
                        description="Text to search for",
                        placeholder="Enter text to detect"
                    ),
                    "timeout": create_param(
                        ParamType.NUMBER,
                        required=False,
                        default=0,
                        description="Maximum time to wait (seconds)"
                    ),
                    "area": create_param(
                        ParamType.AREA,
                        required=False,
                        default=None,
                        description="Screen area to search in"
                    )
                },
                "verification_type": "text"
            },
            {
                "command": "waitForTextToAppearThenDisappear",
                "label": "Wait for Text to Appear Then Disappear",
                "description": "Wait for text to appear and then disappear within the timeout window (e.g. a transient loading/toast). Usable as a KPI reference — measures action→appear.",
                "params": {
                    "text": create_param(
                        ParamType.STRING,
                        required=True,
                        default="",
                        description="Text to search for",
                        placeholder="Enter text to detect"
                    ),
                    "timeout": create_param(
                        ParamType.NUMBER,
                        required=False,
                        default=10,
                        description="Maximum time to wait (seconds)"
                    ),
                    "threshold": create_param(
                        ParamType.NUMBER,
                        required=False,
                        default=0.8,
                        description="Match threshold (0.0 to 1.0)",
                        min=0.0,
                        max=1.0
                    ),
                    "area": create_param(
                        ParamType.AREA,
                        required=False,
                        default=None,
                        description="Screen area to search in"
                    )
                },
                "verification_type": "text"
            },
            {
                "command": "getMenuInfo",
                "label": "Get Menu Info (OCR)",
                "description": "Extract key-value pairs from menu/info screen using OCR and parse automatically",
                "params": {
                    "area": create_param(
                        ParamType.AREA,
                        required=False,
                        default=None,
                        description="Screen area to extract menu information from"
                    )
                },
                "outputs": [
                    create_output(
                        "parsed_data",
                        OutputType.OBJECT,
                        description="Parsed key-value pairs from OCR text"
                    ),
                    create_output(
                        "ocr_text",
                        OutputType.STRING,
                        description="Raw OCR text extracted"
                    ),
                    create_output(
                        "element_count",
                        OutputType.NUMBER,
                        description="Number of lines extracted from OCR"
                    )
                ],
                "verification_type": "text"
            }
        ] 

    def _extract_text_from_area(self, image_path: str, area: dict = None, image_filter: str = None) -> Tuple[str, str, float]:
        """
        Extract text + detected language from image area using TextHelpers.
        Uses SIMPLE OCR (fast, reliable for regular text).

        Returns:
            (extracted_text, detected_language_code, language_confidence_0_to_1)
        """
        try:
            result = self.helpers.detect_text_in_area(image_path, area, use_advanced_ocr=False)

            extracted_text = result.get('extracted_text', '')
            lang_code = result.get('detected_language', 'en')
            lang_confidence = float(result.get('language_confidence', 0.0))

            print(f"[@controller:TextVerification] OCR extracted: '{extracted_text.strip()}' "
                  f"lang={lang_code} conf={lang_confidence:.2f}")

            return extracted_text, lang_code, lang_confidence

        except Exception as e:
            print(f"[@controller:TextVerification] Error extracting text from area: {e}")
            return "", 'en', 0.0

    def _text_match(self, extracted_text: str, target_text: str,
                    threshold: float) -> Tuple[bool, float]:
        """
        Score-driven match wrapping TextHelpers.text_match_score.

        Returns (passed, score). `passed = score >= threshold`. `score == 1.0`
        means the normalized target was found verbatim as a substring (mirrors
        image-template scoring: 1.0 = perfect). Exception → (False, 0.0).
        """
        try:
            score = self.helpers.text_match_score(extracted_text, target_text)
            return score >= threshold, score
        except Exception as e:
            print(f"[@controller:TextVerification] Error in text matching: {e}")
            return False, 0.0

    def _build_text_wait_frames(self, base_mtime, specs, area, verification_index, best_crop=None):
        """Build first / best / last evidence frames for a polled waitForTextToAppear
        failure. Text has no pixel-diff overlay; each frame carries its own cropped
        source and the OCR text extracted from that frame. Crops are deduped by full
        frame path (first/best/last often coincide when the screen never changed)."""
        cache = {}
        frames = []
        for label, info in specs:
            if not info or not info.get('path'):
                continue
            path = info['path']
            if label == 'best' and best_crop:
                crop = best_crop
            elif path in cache:
                crop = cache[path]
            elif area:
                crop = self._save_cropped_source_image(path, area, f"{verification_index}_{label}") or path
                cache[path] = crop
            else:
                crop = path
                cache[path] = crop
            mtime = info.get('mtime')
            score = info.get('score')
            frames.append({
                'label': label,
                'full_path': path,
                'crop_path': crop,
                'overlay_path': None,
                'extracted_text': info.get('text', ''),
                'score': round(float(score), 4) if score is not None else None,
                'elapsed_s': round(max(0.0, mtime - base_mtime), 2) if mtime else 0.0,
            })
        return frames

    def _save_cropped_source_image(self, source_path: str, area: dict, verification_index: int) -> Optional[str]:
        """
        Save cropped source image for UI comparison using ImageHelpers.
        
        Args:
            source_path: Path to source image
            area: Area to crop
            verification_index: Index for naming
            
        Returns:
            str: Path to saved cropped image, None if failed
        """
        try:
            # Import ImageHelpers for cropping (reuse image cropping logic)
            from .image_helpers import ImageHelpers
            image_helpers = ImageHelpers(self.captures_path, self.av_controller)
            
            # Create results directory in COLD storage (persistent) - use same path as image controller
            from shared.src.lib.utils.storage_path_utils import get_cold_storage_path, get_capture_folder
            capture_folder = get_capture_folder(self.av_controller.video_capture_path)
            cold_captures_path = get_cold_storage_path(capture_folder, 'captures')
            results_dir = os.path.join(cold_captures_path, 'verification_results')
            os.makedirs(results_dir, exist_ok=True)
            
            # Create result file path with UNIQUE timestamp to avoid browser caching
            timestamp = int(time.time() * 1000)  # milliseconds
            cropped_result_path = f'{results_dir}/text_source_image_{verification_index}_{timestamp}.png'
            
            print(f"[@controller:TextVerification] Cropping source image: {source_path} -> {cropped_result_path}")
            
            # Use ImageHelpers to crop the image (reuse existing crop functionality)
            success = image_helpers.crop_image_to_area(source_path, cropped_result_path, area)
            
            if success:
                print(f"[@controller:TextVerification] Successfully cropped text source image")
                return cropped_result_path
            else:
                print(f"[@controller:TextVerification] Failed to crop source image")
                return None
                
        except Exception as e:
            print(f"[@controller:TextVerification] Error cropping source image: {e}")
            return None
    
    # =============================================================================
    # Focus / "selected label" detection for text
    # =============================================================================
    #
    # OCR answers "is this text on screen?" but NOT "is it the SELECTED/focused
    # label?". A focused label adds a saturated colour accent — a coloured
    # underline / border, a background pill/fill, or the glyphs themselves
    # changing colour. We reuse the image controller's HSV accent machinery
    # (ImageHelpers.learn_focus_accent / measure_focus) instead of re-inventing it.
    #
    # Two differences vs image focus:
    #   1. The user draws the text area tight around the glyphs, so a focus
    #      underline/border usually sits just OUTSIDE it. We PAD the area by
    #      FOCUS_PAD_PX on every side (clamped to the frame) before learning AND
    #      measuring, so the accent falls inside the crop.
    #   2. Text focus can live in the interior (coloured glyphs), not only at the
    #      edges, so we scan the WHOLE padded crop (band_frac >= 0.5 collapses the
    #      perimeter mask to cover everything) rather than the perimeter-only band
    #      image uses to dodge a centre logo.
    #
    # The learned params (incl. the pad used) ride along inside the reference's
    # area JSON, exactly like image — so they travel with the reference and the
    # verify-time crop is reconstructed identically.
    # =============================================================================

    FOCUS_PAD_PX = 30               # cover a focus underline/border just outside the tight text box
    FOCUS_BAND_FRAC_WHOLE = 0.5     # >= 0.5 makes the perimeter mask cover the whole padded crop

    def _get_image_helpers(self):
        """Lazily build a shared ImageHelpers (for crop + focus accent reuse)."""
        from .image_helpers import ImageHelpers
        if getattr(self, '_image_helpers', None) is None:
            self._image_helpers = ImageHelpers(self.captures_path, self.av_controller)
        return self._image_helpers

    def _pad_area(self, area: dict, img_w: int, img_h: int, pad: int = None) -> dict:
        """Expand an area by `pad` px on every side, clamped to the frame bounds."""
        pad = self.FOCUS_PAD_PX if pad is None else pad
        x = max(0, int(area['x']) - pad)
        y = max(0, int(area['y']) - pad)
        x2 = min(img_w, int(area['x']) + int(area['width']) + pad)
        y2 = min(img_h, int(area['y']) + int(area['height']) + pad)
        return {'x': x, 'y': y, 'width': max(1, x2 - x), 'height': max(1, y2 - y)}

    def _resolve_local_image_source(self, image_source_url: str) -> Optional[str]:
        """Resolve a frontend-supplied source URL/filename to an existing local path
        (hot then cold). Mirrors the resolution used by detect_text."""
        if not image_source_url:
            return None
        if image_source_url.startswith(('http://', 'https://')):
            try:
                return self.helpers.download_image(image_source_url)
            except Exception:
                return None
        from shared.src.lib.utils.build_url_utils import convertHostUrlToLocalPath
        from shared.src.lib.utils.storage_path_utils import get_cold_storage_path, get_capture_folder
        clean = image_source_url.split('?')[0]
        if not clean.startswith('/'):
            resolved = os.path.join(self.captures_path, clean)
        else:
            try:
                resolved = convertHostUrlToLocalPath(clean)
            except Exception:
                resolved = clean
        if os.path.exists(resolved):
            return resolved
        device_folder = get_capture_folder(self.captures_path)
        cold = os.path.join(get_cold_storage_path(device_folder, 'captures'), os.path.basename(resolved))
        return cold if os.path.exists(cold) else None

    def _learn_text_focus(self, image_source_url: str, area: dict) -> Tuple[Optional[dict], Optional[str]]:
        """Crop the PADDED area from the full source frame and learn the focus accent.

        Returns (focus_params_or_None, warning_or_None). The crop is whole-area
        (band_frac >= 0.5) so coloured glyphs, underlines and pills all count.
        """
        src = self._resolve_local_image_source(image_source_url)
        if not src:
            return None, "Focus requested but the source frame could not be located to learn the accent."
        img = cv2.imread(src, cv2.IMREAD_COLOR)
        if img is None:
            return None, "Focus requested but the source frame could not be read."
        h, w = img.shape[:2]
        padded = self._pad_area(area, w, h)
        crop = img[padded['y']:padded['y'] + padded['height'], padded['x']:padded['x'] + padded['width']]
        if crop.size == 0:
            return None, "Focus requested but the padded text area is empty."
        helpers = self._get_image_helpers()
        learned = helpers.learn_focus_accent(crop, band_frac=self.FOCUS_BAND_FRAC_WHOLE)
        if not learned:
            return None, ("Focus requested but no saturated colour accent was found within "
                          f"{self.FOCUS_PAD_PX}px of the text — the selected state may use only a "
                          "brightness change (no colour), or the indicator is further away.")
        learned['pad'] = self.FOCUS_PAD_PX
        print(f"[@controller:TextVerification] Learned text focus accent: {learned}")
        return learned, None

    def _check_text_focus(self, source_path: str, area: dict, focus_params: dict) -> Tuple[bool, float]:
        """Measure focus accent coverage in the padded text area of a source frame.

        Returns (focus_pass, focus_score). Reconstructs the same padded crop used
        at learn time (pad stored in focus_params) so the learned region lines up.
        """
        try:
            img = cv2.imread(source_path, cv2.IMREAD_COLOR)
            if img is None:
                return False, 0.0
            h, w = img.shape[:2]
            pad = int(focus_params.get('pad', self.FOCUS_PAD_PX))
            padded = self._pad_area(area, w, h, pad)
            crop = img[padded['y']:padded['y'] + padded['height'], padded['x']:padded['x'] + padded['width']]
            if crop.size == 0:
                return False, 0.0
            helpers = self._get_image_helpers()
            focus_score, _ = helpers.measure_focus(crop, focus_params)
            ft = float(focus_params.get('threshold', helpers.FOCUS_DEFAULT_THRESHOLD))
            focus_pass = focus_score >= ft
            print(f"[@controller:TextVerification] Focus check: score={focus_score:.3f} "
                  f"threshold={ft:.2f} → {'FOCUSED' if focus_pass else 'NOT focused'}")
            return focus_pass, focus_score
        except Exception as e:
            print(f"[@controller:TextVerification] Focus check error: {e}")
            return False, 0.0

    def _resolve_text_area_cached(self, reference_name: str, userinterface_name: str, team_id: str):
        """Resolve a text reference's area from the DB, honoring an optional
        per-batch cache.

        The verification executor sets `self._reference_cache = {}` for the
        duration of a shared-window run (one batch checked against many frames),
        so the same reference resolves from the DB ONCE instead of once per
        frame. Outside that window `_reference_cache` is None → no caching, no
        staleness (every other path behaves exactly as before).
        """
        from shared.src.lib.utils.reference_utils import resolve_reference_area_backend
        cache = getattr(self, '_reference_cache', None)
        if cache is None:
            return resolve_reference_area_backend(reference_name, userinterface_name, team_id)
        key = (reference_name, userinterface_name, team_id)
        if key not in cache:
            cache[key] = resolve_reference_area_backend(reference_name, userinterface_name, team_id)
        return cache[key]

    def _derive_hot_captures_dir(self, source_path: str) -> str:
        """Resolve the hot/captures directory from a capture path.

        take_screenshot() returns a *cold* path even when the source frame
        comes from hot/, so derive the hot dir for polling. Falls back to the
        source's own dir on SD-mode hosts where hot/ doesn't exist.
        """
        src_dir = os.path.dirname(source_path)
        if '/hot/' in src_dir or src_dir.endswith('/hot/captures'):
            return src_dir
        if src_dir.endswith('/captures'):
            candidate = src_dir[:-len('/captures')] + '/hot/captures'
            if os.path.isdir(candidate):
                return candidate
        return src_dir

    def _get_next_capture(self, filepath: str, offset: int) -> str:
        """Get next sequential capture filename"""
        match = re.search(r'capture_(\d{9})', filepath)
        if not match:
            return None
        num = int(match.group(1)) + offset
        return filepath.replace(match.group(0), f'capture_{num:09d}')
    
    def extract_ocr_dump(self, screenshot_path: str, confidence_threshold: int = 30) -> Dict[str, Any]:
        """
        Extract full OCR dump with bounding boxes (TV exploration).
        
        This is the TV equivalent of ADB dump - discovers all text elements with their areas.
        Used by exploration_executor for TV node verification.
        
        Args:
            screenshot_path: Path to screenshot
            confidence_threshold: Minimum OCR confidence (0-100)
            
        Returns:
            {
                'success': True,
                'elements': [
                    {'text': 'TV Guide', 'area': {...}, 'confidence': 85},
                    ...
                ]
            }
        """
        try:
            print(f"[@controller:TextVerification:extract_ocr_dump] Extracting OCR dump from: {screenshot_path}")
            
            if not os.path.exists(screenshot_path):
                return {
                    'success': False,
                    'elements': [],
                    'message': f'Screenshot not found: {screenshot_path}'
                }
            
            # Use helper to extract OCR dump
            elements = self.helpers.extract_full_ocr_dump(screenshot_path, confidence_threshold)
            
            print(f"[@controller:TextVerification:extract_ocr_dump] Extracted {len(elements)} elements")
            
            # Log sample elements
            if elements:
                print(f"[@controller:TextVerification:extract_ocr_dump] Sample elements:")
                for elem in elements[:5]:  # Show first 5
                    print(f"  • '{elem['text']}' at ({elem['area']['x']}, {elem['area']['y']}) conf={elem['confidence']}")
            
            return {
                'success': True,
                'elements': elements,
                'message': f'Extracted {len(elements)} text elements'
            }
            
        except Exception as e:
            print(f"[@controller:TextVerification:extract_ocr_dump] ERROR: {e}")
            import traceback
            traceback.print_exc()
            return {
                'success': False,
                'elements': [],
                'message': f'OCR dump extraction failed: {str(e)}'
            }
    
    def getMenuInfo(self, area: dict = None, context = None, source_path: str = None, char_whitelist: str = None) -> Dict[str, Any]:
        """
        Extract menu information from screen using OCR, parse key-value pairs, and auto-store to metadata.

        This combines OCR with automatic key-value parsing for menu/info screens.
        Typical use: Extract device info (serial number, MAC, firmware, etc.)

        Args:
            area: Optional area dict {'x', 'y', 'width', 'height'} for OCR region (None = full screenshot)
            context: Execution context (for metadata storage)
            source_path: Screenshot path (None = auto-capture)
            char_whitelist: Optional tesseract char whitelist forcing OCR to emit ONLY
                these characters (avoids stray symbols on version/serial strings). Keys
                are uppercase labels with spaces and values are alphanumeric + ".-_+", so
                pass a set covering both, incl. a space. None = unconstrained (default).
            
        Returns:
            Dict with:
                - success: bool
                - output_data: dict with parsed_data and ocr_text
                - message: str
                
        Example metadata output (FLAT JSON):
            {
                "serial_number": "ABC123",
                "mac_address": "00:11:22:33:44:55",
                "firmware_version": "1.2.3",
                "extraction_timestamp": "2025-10-28T10:30:00",
                "ocr_text": "Serial Number: ABC123\nMAC: 00:11:22:33:44:55",
                "device_name": "device1"
            }
        """
        print(f"[@controller:TextVerification:getMenuInfo] Params: area={area}, source_path={source_path}, context={context is not None}, char_whitelist={char_whitelist!r}")
        
        try:
            # Auto-capture screenshot if no source_path provided (same as OCR function)
            if not source_path:
                print(f"[@controller:TextVerification:getMenuInfo] No source_path → auto-capturing screenshot")
                source_path = self.av_controller.take_screenshot()
                if not source_path or not os.path.exists(source_path):
                    return {
                        'success': False,
                        'output_data': {'ocr_text': ''},
                        'message': 'Failed to auto-capture screenshot'
                    }
                print(f"[@controller:TextVerification:getMenuInfo] Auto-captured: {source_path}")
            
            # Validate source path exists
            if not os.path.exists(source_path):
                return {
                    'success': False,
                    'output_data': {'ocr_text': ''},
                    'message': f'Source image not found: {source_path}'
                }
            
            # Extract text using helper with ADVANCED OCR (multi-approach for difficult gray text)
            print(f"[@controller:TextVerification:getMenuInfo] OCR extraction with ADVANCED multi-approach...")
            result = self.helpers.detect_text_in_area(source_path, area, use_advanced_ocr=True, char_whitelist=char_whitelist)
            extracted_text = result.get('extracted_text', '')
            
            if not extracted_text:
                print(f"[@controller:TextVerification:getMenuInfo] FAIL: No text extracted")
                return {
                    'success': False,
                    'output_data': {'ocr_text': ''},
                    'message': 'No text detected in specified area'
                }
            
            print(f"[@controller:TextVerification:getMenuInfo] Extracted text ({len(extracted_text)} chars):")
            print(f"--- OCR TEXT START ---")
            print(extracted_text)
            print(f"--- OCR TEXT END ---")
            
            # Parse key-value pairs using helper
            print(f"[@controller:TextVerification:getMenuInfo] Parsing key-value pairs...")
            parsed_data = self.helpers.parse_menu_info(extracted_text)

            # Self-heal registered fields whose value fails its regex
            # (e.g. serial numbers where OCR confused 0/O or 1/I)
            self._heal_known_fields(parsed_data, source_path, area)

            print(f"[@controller:TextVerification:getMenuInfo] Parsed {len(parsed_data)} key-value pairs")
            for key, value in parsed_data.items():
                print(f"  • {key} = {value}")
            
            if not parsed_data:
                print(f"[@controller:TextVerification:getMenuInfo] WARNING: No key-value pairs found in OCR text")

            
            # Auto-store to context.metadata (FLAT JSON)
            if context:
                from datetime import datetime
                
                # Initialize metadata if not exists
                if not hasattr(context, 'metadata'):
                    context.metadata = {}
                
                # Append parsed data directly to metadata (flat structure)
                for key, value in parsed_data.items():
                    context.metadata[key] = value
                
                # Add extraction metadata
                context.metadata['extraction_timestamp'] = datetime.now().isoformat()
                context.metadata['ocr_text'] = extracted_text
                
                # Add device info if available
                if hasattr(context, 'selected_device') and context.selected_device:
                    device = context.selected_device
                    if hasattr(device, 'device_name'):
                        context.metadata['device_name'] = device.device_name
                
                if area:
                    context.metadata['ocr_area'] = str(area)
                
                print(f"[@controller:TextVerification:getMenuInfo] ✅ AUTO-APPENDED to context.metadata (FLAT)")
                print(f"[@controller:TextVerification:getMenuInfo] Metadata keys: {list(context.metadata.keys())}")
                print(f"[@controller:TextVerification:getMenuInfo] New fields added: {list(parsed_data.keys())}")
            else:
                print(f"[@controller:TextVerification:getMenuInfo] WARNING: No context provided, metadata not stored")

            
            # Prepare raw_dump structure (consistent with ADB)
            # Split OCR text into lines for structured debugging
            ocr_lines = extracted_text.split('\n')
            raw_dump = []
            for idx, line in enumerate(ocr_lines):
                raw_dump.append({
                    'index': idx,
                    'line_number': idx + 1,
                    'text': line,
                    'character_count': len(line),
                    'is_empty': len(line.strip()) == 0
                })
            
            # Prepare output data (CLEAN structure - only 3 fields displayed to user)
            output_data = {
                'parsed_data': parsed_data,           # Parsed key-value pairs
                'raw_dump': raw_dump,                 # Structured line-by-line dump
                'element_count': len(ocr_lines)       # Number of lines
            }
            
            print(f"[@controller:TextVerification:getMenuInfo] 📤 RETURNING output_data with {len(parsed_data)} parsed_data entries")
            print(f"[@controller:TextVerification:getMenuInfo] 📤 output_data keys: {list(output_data.keys())}")
            
            # Construct success message
            message = f'Parsed {len(parsed_data)} fields from {len(ocr_lines)} OCR lines'
            
            print(f"[@controller:TextVerification:getMenuInfo] ✅ SUCCESS: {message}")
            
            return {
                'success': True,
                'output_data': output_data,
                'message': message
            }
            
        except Exception as e:
            error_msg = f"Error extracting menu info: {str(e)}"
            print(f"[@controller:TextVerification:getMenuInfo] ERROR: {error_msg}")
            import traceback
            traceback.print_exc()

            return {
                'success': False,
                'output_data': {},
                'message': error_msg
            }

    def _heal_known_fields(self, parsed_data: Dict[str, str], source_path: str, area: Optional[dict]) -> None:
        """
        For each registered field rule, if the parsed value fails its regex, re-run
        OCR on the same image with a character whitelist and replace the value with
        the first regex match found in the cleaner pass. Mutates parsed_data in
        place. Unregistered fields are left untouched.
        """
        for rule in _MENU_INFO_FIELD_RULES:
            for key in rule['keys']:
                if key not in parsed_data:
                    continue
                value = parsed_data[key]
                if rule['regex'].fullmatch(value):
                    continue
                print(f"[@controller:TextVerification:heal] '{key}' = '{value}' fails regex, retrying OCR with whitelist")
                retry_text = self.helpers.ocr_with_whitelist(
                    source_path, area, whitelist=rule['whitelist']
                )
                match = rule['regex'].search(retry_text)
                if match:
                    healed = match.group(0)
                    print(f"[@controller:TextVerification:heal] '{value}' → '{healed}'")
                    parsed_data[key] = healed
                else:
                    print(f"[@controller:TextVerification:heal] No regex match in retry output, keeping original")

