"""
Image Helpers

Core image processing helpers for 3 main operations:
1. Template matching (image verification)
2. Crop image to area
3. Process image (filters, background removal) 
4. Save/download images

Includes: template matching, cropping, filtering, background removal, URL downloading
"""

import os
import re
import requests
import tempfile
import time
import cv2
import numpy as np
import shutil
import subprocess
from typing import Dict, Any, Optional, Tuple, List
from urllib.parse import urlparse


class ImageHelpers:
    """Core image processing helpers for verification operations."""
    
    def __init__(self, captures_path: str, av_controller):
        """Initialize image helpers with captures path and AV controller."""
        self.captures_path = captures_path
        self.av_controller = av_controller
    
    def round_area_coordinates(self, area: Dict[str, Any], max_decimals: int = 2) -> Dict[str, Any]:
        """
        Round area coordinates to specified decimal places.
        
        Args:
            area: Area dictionary with coordinates
            max_decimals: Maximum decimal places (default: 2)
        
        Returns:
            Area dict with rounded coordinates
        """
        if not area:
            return area
        
        rounded_area = {}
        for key, value in area.items():
            if isinstance(value, (int, float)):
                # Round to max_decimals places
                rounded_area[key] = round(value, max_decimals)
            else:
                rounded_area[key] = value
        
        return rounded_area
       
    def download_image(self, source_url: str) -> str:
        """Download image from URL only."""
        try:
            response = requests.get(source_url, timeout=30)
            response.raise_for_status()
            
            with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
                tmp.write(response.content)
                return tmp.name
                
        except Exception as e:
            print(f"[@image_helpers] Error downloading image from URL: {e}")
            raise
    
    def save_image_reference(self, image_path: str, reference_name: str, userinterface_name: str, team_id: str, area: Dict[str, Any] = None, shared: bool = False) -> Dict[str, Any]:
        """
        Save image reference with R2 upload and database save.

        Args:
            image_path: Local path to the image file
            reference_name: Name of the reference
            userinterface_name: Origin user interface name (e.g., 'example_mobile').
                Records the row's origin even when shared=True.
            team_id: Team ID
            area: Optional area definition
            shared: When True, the reference becomes visible+editable by every UI in
                the team whose models[] intersects with userinterface_name's models[].

        Returns:
            Dict with success status and details
        """
        try:
            print(f"[@image_helpers] Uploading reference to R2: {reference_name} for userinterface: {userinterface_name}")
            
            # Round all area coordinates to 2 decimal places (max precision needed)
            if area:
                area = self.round_area_coordinates(area, max_decimals=2)
                print(f"[@image_helpers] Rounded area coordinates (2 decimals): {area}")
            
            # Snapshot the previous reference (image + area) into version history
            # BEFORE the live R2 key is overwritten below — at this point the old
            # bytes are still live. No-op on first capture. Best-effort.
            from shared.src.lib.database.verifications_references_db import snapshot_reference_version
            snapshot_reference_version(reference_name, userinterface_name, 'reference_image', team_id)

            # Upload to R2 using cloudflare utils
            from shared.src.lib.utils.cloudflare_utils import upload_reference_image
            from shared.src.lib.utils.reference_utils import reference_storage_key
            # Rename-stable storage folder = userinterface id (falls back to name if unresolved)
            _ui_folder = reference_storage_key(userinterface_name, team_id)

            # Use reference name with .jpg extension for R2
            r2_filename = f"{reference_name}.jpg"
            upload_result = upload_reference_image(image_path, _ui_folder, r2_filename)
            
            if not upload_result.get('success'):
                return {
                    'success': False,
                    'error': f"R2 upload failed: {upload_result.get('error')}"
                }
            
            r2_url = upload_result.get('url', '')
            r2_path = upload_result.get('remote_path', '')
            
            print(f"[@image_helpers] Successfully uploaded to R2: {r2_url}")
            
            # Upload filtered versions to R2
            import os
            base_path, ext = os.path.splitext(image_path)
            
            # Upload greyscale version
            greyscale_path = f"{base_path}_greyscale{ext}"
            if os.path.exists(greyscale_path):
                greyscale_filename = f"{reference_name}_greyscale.jpg"
                upload_reference_image(greyscale_path, _ui_folder, greyscale_filename)
            
            # Upload binary version
            binary_path = f"{base_path}_binary{ext}"
            if os.path.exists(binary_path):
                binary_filename = f"{reference_name}_binary.jpg"
                upload_reference_image(binary_path, _ui_folder, binary_filename)
            
            # Save reference to database
            from shared.src.lib.database.verifications_references_db import save_reference
            
            db_result = save_reference(
                name=reference_name,
                userinterface_name=userinterface_name,
                reference_type='reference_image',
                team_id=team_id,
                r2_path=r2_path,
                r2_url=r2_url,
                area=area,
                shared=shared,
            )
            
            if not db_result.get('success'):
                return {
                    'success': False,
                    'error': f"Database save failed: {db_result.get('error')}"
                }
            
            print(f"[@image_helpers] Successfully saved reference to database: {reference_name}")
            
            return {
                'success': True,
                'reference_name': reference_name,
                'r2_url': r2_url,
                'r2_path': r2_path,
                'reference_id': db_result.get('reference_id')
            }
            
        except Exception as e:
            print(f"[@image_helpers] Error saving image reference: {e}")
            return {'success': False, 'error': str(e)}
    
    # =============================================================================
    # Core Operation 1: Template Matching
    # =============================================================================
    
    # Templates smaller than this many pixels are too small for TM_CCOEFF_NORMED:
    # mean-subtraction near-zeros the score (or makes it very noisy), so the same
    # screen state can swing 0.65↔0.78 across captures. For tiny references we
    # use L1 channel-distance instead — deterministic, has no zero-std pathology.
    SMALL_TEMPLATE_PIXEL_THRESHOLD = 1000

    def match_template_in_area(self, image_source_path: str, template_path: str,
                              area: Dict[str, Any] = None, threshold: float = 0.8) -> Dict[str, Any]:
        try:
            source_img = cv2.imread(image_source_path)
            template_img = cv2.imread(template_path)

            if source_img is None or template_img is None:
                return {'found': False, 'error': 'Failed to load images', 'confidence': 0.0}

            if area:
                x, y = int(area['x']), int(area['y'])
                width, height = int(area['width']), int(area['height'])

                src_height, src_width = source_img.shape[:2]
                if x < 0 or y < 0 or x + width > src_width or y + height > src_height:
                    return {'found': False, 'error': 'Search area out of bounds', 'confidence': 0.0}

                search_area = source_img[y:y+height, x:x+width]
                offset_x, offset_y = x, y
            else:
                search_area = source_img
                offset_x, offset_y = 0, 0

            # Auto-fallback for small templates — see _l1_match_in_region.
            template_h, template_w = template_img.shape[:2]
            if template_h * template_w <= self.SMALL_TEMPLATE_PIXEL_THRESHOLD:
                max_val, max_loc = self._l1_match_in_region(search_area, template_img)
                print(f"[@template_match] small template ({template_w}x{template_h}={template_h*template_w}px) → L1 matcher, score={max_val:.3f}")
            else:
                result = cv2.matchTemplate(search_area, template_img, cv2.TM_CCOEFF_NORMED)
                _, max_val, _, max_loc = cv2.minMaxLoc(result)

            found = max_val >= threshold
            
            if found:
                match_x = offset_x + max_loc[0]
                match_y = offset_y + max_loc[1]
                template_height, template_width = template_img.shape[:2]
                
                return {
                    'found': True,
                    'confidence': float(max_val),
                    'location': {
                        'x': match_x,
                        'y': match_y,
                        'width': template_width,
                        'height': template_height
                    },
                    'center': {
                        'x': match_x + template_width // 2,
                        'y': match_y + template_height // 2
                    }
                }
            else:
                return {'found': False, 'confidence': float(max_val), 'threshold': threshold}
                
        except Exception as e:
            return {'found': False, 'error': f'Matching error: {str(e)}', 'confidence': 0.0}

    def smart_fuzzy_search(self, source_img: np.ndarray, reference_img: np.ndarray, 
                          exact_area: Dict[str, Any], fuzzy_area: Dict[str, Any], 
                          threshold: float = 0.8) -> Tuple[bool, float, Optional[Dict[str, int]]]:
        """
        Simple fuzzy search using OpenCV's matchTemplate.
        OpenCV automatically searches the ENTIRE fuzzy area for best match - no need for manual iterations!
        
        Strategy:
        1. Try exact position first (fast path)
        2. If no match, search entire fuzzy area in one OpenCV call
        """
        try:
            ref_h, ref_w = reference_img.shape[:2]
            ex, ey = int(exact_area['x']), int(exact_area['y'])
            ew, eh = int(exact_area['width']), int(exact_area['height'])
            fx, fy = int(fuzzy_area['fx']), int(fuzzy_area['fy'])
            fw, fh = int(fuzzy_area['fwidth']), int(fuzzy_area['fheight'])
            
            # Matcher selection. TM_CCOEFF_NORMED is intensity-correlation with mean
            # subtraction; on tiny references (e.g. a 20×4 highlight bar = 80 px) it
            # near-zeros the per-channel std-dev and the score becomes noise-driven —
            # 0.65 / 0.78 swings on identical UI states. L1 channel-distance behaves
            # deterministically at that scale. Threshold for the swap matches
            # match_template_in_area.
            ref_area = ref_h * ref_w
            use_l1_matcher = ref_area <= self.SMALL_TEMPLATE_PIXEL_THRESHOLD

            print(f"[@fuzzy] Starting fuzzy search - ref size: {ref_w}x{ref_h} ({ref_area}px), exact: ({ex},{ey}) {ew}x{eh}, fuzzy: ({fx},{fy}) {fw}x{fh}, threshold: {threshold}, matcher: {'l1_distance' if use_l1_matcher else 'tm_ccoeff_normed'}")

            # Step 1: Try exact position first (fast path optimization)
            exact_confidence = 0.0
            exact_region = source_img[ey:ey+eh, ex:ex+ew]
            if exact_region.shape[:2] == (eh, ew):
                if use_l1_matcher:
                    exact_confidence = self._l1_match_score(exact_region, reference_img)
                else:
                    result = cv2.matchTemplate(exact_region, reference_img, cv2.TM_CCOEFF_NORMED)
                    exact_confidence = float(result[0][0])

                print(f"[@fuzzy] Exact position confidence: {exact_confidence:.3f}")
                if exact_confidence >= threshold:
                    print(f"[@fuzzy] ✓ Exact match found: {exact_confidence:.3f}")
                    return True, exact_confidence, {'x': ex, 'y': ey, 'width': ref_w, 'height': ref_h}
            
            # Step 2: Search entire fuzzy area (OpenCV does the sliding window for us!)
            print(f"[@fuzzy] Searching entire fuzzy area...")
            search_region = source_img[fy:fy+fh, fx:fx+fw]
            
            # Log source image and search region dimensions
            src_h, src_w = source_img.shape[:2]
            print(f"[@fuzzy] Source image size: {src_w}x{src_h}")
            print(f"[@fuzzy] Search region extracted: ({fx},{fy}) to ({fx+fw},{fy+fh}) = {search_region.shape[1]}x{search_region.shape[0]}")
            print(f"[@fuzzy] Template size to find: {ref_w}x{ref_h}")
            
            if search_region.shape[0] < ref_h or search_region.shape[1] < ref_w:
                print(f"[@fuzzy] ✗ Search region {search_region.shape} too small for template {ref_h}x{ref_w}")
                return False, exact_confidence, {'x': ex, 'y': ey, 'width': ref_w, 'height': ref_h}
            
            # Calculate how many positions will be checked
            positions_y = search_region.shape[0] - ref_h + 1
            positions_x = search_region.shape[1] - ref_w + 1
            total_positions = positions_x * positions_y
            print(f"[@fuzzy] Will check {total_positions} positions ({positions_x}x{positions_y} grid)")
            
            if use_l1_matcher:
                # Sliding-window L1 distance — cheap because small refs over a
                # bounded fuzzy area means low total positions to check.
                max_val, max_loc = self._l1_match_in_region(search_region, reference_img)
                print(f"[@fuzzy] L1 matching: checked all {total_positions} positions, best score={max_val:.3f}")
            else:
                # OpenCV automatically searches ENTIRE region - this is the standard approach!
                result = cv2.matchTemplate(search_region, reference_img, cv2.TM_CCOEFF_NORMED)
                min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)
                print(f"[@fuzzy] TEMPLATE matching: OpenCV checked all {total_positions} positions")
                print(f"[@fuzzy] Match score range: min={min_val:.3f}, max={max_val:.3f}")
            
            # Convert match location back to full image coordinates
            match_x = fx + max_loc[0]
            match_y = fy + max_loc[1]
            best_location = {'x': match_x, 'y': match_y, 'width': ref_w, 'height': ref_h}
            
            print(f"[@fuzzy] Best match found at:")
            print(f"[@fuzzy]   - Relative to search region: ({max_loc[0]},{max_loc[1]})")
            print(f"[@fuzzy]   - Absolute in source image: ({match_x},{match_y})")
            print(f"[@fuzzy]   - Confidence: {max_val:.3f}")
            print(f"[@fuzzy]   - Distance from exact position: dx={match_x-ex}px, dy={match_y-ey}px")
            
            found = max_val >= threshold
            if found:
                print(f"[@fuzzy] ✓ Match found in fuzzy area: {max_val:.3f} >= {threshold:.3f}")
            else:
                print(f"[@fuzzy] ✗ No match found. Best confidence: {max_val:.3f} < {threshold:.3f} (required)")
            
            return found, max_val, best_location
            
        except Exception as e:
            print(f"[@fuzzy] ERROR: Fuzzy search crashed: {e}")
            import traceback
            traceback.print_exc()
            return False, 0.0, None

    def _pixel_match_score(self, source_region: np.ndarray, reference_img: np.ndarray) -> float:
        """
        Calculate pixel-based matching score (0.0 to 1.0).
        More reliable than template matching for very small images.
        Uses the same logic as the overlay visualization.
        """
        try:
            # Ensure same dimensions
            if source_region.shape != reference_img.shape:
                return 0.0

            # Convert to grayscale
            source_gray = cv2.cvtColor(source_region, cv2.COLOR_BGR2GRAY)
            ref_gray = cv2.cvtColor(reference_img, cv2.COLOR_BGR2GRAY)

            # Calculate absolute difference
            diff = cv2.absdiff(source_gray, ref_gray)

            # Count matching pixels (difference <= 10)
            matching_pixels = np.sum(diff <= 10)
            total_pixels = source_gray.shape[0] * source_gray.shape[1]

            return matching_pixels / total_pixels
        except Exception as e:
            print(f"[@fuzzy] Pixel match error: {e}")
            return 0.0

    # Structural-similarity guard for the L1 path. A real content match has a
    # source window with texture comparable to the reference. L1 distance alone
    # rewards average brightness/colour similarity, so a dark/uniform region of
    # the source frame can score 0.84+ against a textured icon whose mean BGR
    # also happens to be dark — pure false positive (Netflix logo matching
    # background pixels). Penalise when the window is much smoother than the
    # ref; skip the guard when the ref itself is near-uniform (rare, but then
    # L1 brightness similarity is the right metric).
    L1_GUARD_REF_STD_FLOOR = 20.0     # below this the ref has no texture to guard
    L1_GUARD_WINDOW_STD_RATIO = 0.6   # window must have ≥ 60% of ref's std-dev

    # Spatial-coverage guard for the L1 path. L1 score is a MEAN over the window,
    # so a window that is only half-correct (e.g. the right half is the red bar,
    # the left half is dark background) still averages over threshold. The
    # structural std guard above does NOT catch this: a half-dark/half-coloured
    # window has high variance, so it passes. Coverage requires the match to hold
    # across most of the window — fraction of pixels whose per-channel abs-diff is
    # within tolerance must clear the floor. A real match (even with shade drift)
    # stays ~1.0; the half-wrong false positive saturates near 0.5 at any
    # tolerance, so the floor separates them with wide margin.
    # (Observed: settings_info_red false positive = 0.51 coverage @ L1 0.803;
    #  uniform shade-drift up to -40/channel = 1.0 coverage.)
    L1_COVERAGE_COLOR_TOL = 40        # per-channel abs-diff for a pixel to "match"
    L1_COVERAGE_FLOOR = 0.7           # fraction of pixels that must match

    def _l1_match_score(self, source_region: np.ndarray, reference_img: np.ndarray) -> float:
        """
        Score = 1 − mean(|source − reference|) / 255 over all pixels and channels.

        Used as a TM_CCOEFF_NORMED replacement for small references where the
        correlation matcher is unstable (uniform/low-variance patches near-zero
        std-dev once mean is subtracted). L1 distance is deterministic at any
        scale and tolerates per-platform colour-shade drift well enough at
        threshold ≥ 0.7.

        Both inputs must be the same shape (HxWxC).
        """
        try:
            if source_region.shape != reference_img.shape:
                return 0.0
            diff = cv2.absdiff(source_region, reference_img)
            score = 1.0 - float(diff.mean()) / 255.0
            ref_std = float(reference_img.std())
            if ref_std >= self.L1_GUARD_REF_STD_FLOOR:
                win_std = float(source_region.std())
                if win_std < self.L1_GUARD_WINDOW_STD_RATIO * ref_std:
                    print(f"[@l1_match] structural guard: window std={win_std:.1f} < {self.L1_GUARD_WINDOW_STD_RATIO:.2f} × ref std={ref_std:.1f} — rejecting (raw L1 was {score:.3f})")
                    return 0.0
            coverage = self._l1_pixel_coverage(source_region, reference_img)
            if coverage < self.L1_COVERAGE_FLOOR:
                print(f"[@l1_match] coverage guard: {coverage:.2f} < {self.L1_COVERAGE_FLOOR:.2f} (per-ch tol {self.L1_COVERAGE_COLOR_TOL}) — rejecting partial/half-window match (raw L1 was {score:.3f})")
                return 0.0
            return score
        except Exception as e:
            print(f"[@l1_match] error: {e}")
            return 0.0

    def _l1_pixel_coverage(self, source_region: np.ndarray, reference_img: np.ndarray) -> float:
        """Fraction of pixels whose per-channel abs-diff is within L1_COVERAGE_COLOR_TOL.

        Spatial complement to the mean L1 score: a half-correct window has a
        passing mean but low coverage. See the L1_COVERAGE_* constants block.
        """
        if source_region.shape != reference_img.shape:
            return 0.0
        within = (cv2.absdiff(source_region, reference_img) <= self.L1_COVERAGE_COLOR_TOL).all(axis=2)
        return float(within.mean())

    def _l1_match_in_region(self, search_region: np.ndarray, reference_img: np.ndarray) -> Tuple[float, Tuple[int, int]]:
        """
        Sliding-window L1 match over `search_region`. Returns (best_score, (x, y))
        of the top-left of the best-matching window, in search_region coords.

        Cheap for small references: O((W − rw + 1)(H − rh + 1) · rw · rh) — for a
        20×4 reference inside a 1920×80 search area this is ~9k positions × 80
        pixels = sub-millisecond on numpy/cv2.

        The structural guard is applied once at the best location instead of
        per-window: if even the strongest L1 candidate has insufficient texture,
        no weaker candidate will either, and we keep the inner loop tight.
        """
        ref_h, ref_w = reference_img.shape[:2]
        sr_h, sr_w = search_region.shape[:2]
        if sr_h < ref_h or sr_w < ref_w:
            return 0.0, (0, 0)
        best_score = -1.0
        best_loc = (0, 0)
        for y in range(sr_h - ref_h + 1):
            for x in range(sr_w - ref_w + 1):
                window = search_region[y:y+ref_h, x:x+ref_w]
                score = 1.0 - float(cv2.absdiff(window, reference_img).mean()) / 255.0
                if score > best_score:
                    best_score = score
                    best_loc = (x, y)
        bx, by = best_loc
        best_window = search_region[by:by+ref_h, bx:bx+ref_w]
        ref_std = float(reference_img.std())
        if ref_std >= self.L1_GUARD_REF_STD_FLOOR:
            win_std = float(best_window.std())
            if win_std < self.L1_GUARD_WINDOW_STD_RATIO * ref_std:
                print(f"[@l1_match] structural guard: best-window std={win_std:.1f} < {self.L1_GUARD_WINDOW_STD_RATIO:.2f} × ref std={ref_std:.1f} — rejecting (raw L1 was {best_score:.3f})")
                return 0.0, best_loc
        coverage = self._l1_pixel_coverage(best_window, reference_img)
        if coverage < self.L1_COVERAGE_FLOOR:
            print(f"[@l1_match] coverage guard: best-window {coverage:.2f} < {self.L1_COVERAGE_FLOOR:.2f} (per-ch tol {self.L1_COVERAGE_COLOR_TOL}) — rejecting partial/half-window match (raw L1 was {best_score:.3f})")
            return 0.0, best_loc
        return max(best_score, 0.0), best_loc

    # =============================================================================
    # Focus / "selected element" detection
    # =============================================================================
    #
    # Template matching answers "is this element on screen?" but NOT "is it the
    # selected/focused one?". A focused element adds a saturated accent indicator
    # at its EDGES — a coloured border (YouTube), a bottom underline bar (Search),
    # or a background fill (Apple TV+). That accent is a small fraction of the
    # tile's pixels, so TM/L1 still scores 0.85-0.95 on the unfocused tile and the
    # verification passes when it shouldn't (the Netflix-shown-but-not-selected bug).
    #
    # We learn the accent automatically from the single FOCUSED reference the user
    # captures (they just tick "Focus"). The key trick: only look at the PERIMETER
    # band, never the interior. That excludes the element's own colours (e.g. the
    # red YouTube logo sits in the centre and must NOT be mistaken for a red focus
    # border) and unifies all three styles — border / underline / fill all live at
    # the edges. The saturation+value gate means "a grey bar exists" or "a near-black
    # red-hue background" never counts; only a genuinely saturated accent does.
    #
    # Validated on real focused/unfocused pairs (focus_score focused → unfocused):
    #   border 18.4%→0.6% · underline 90.5%→0% · underline+decoy-bar 54.9%→0% ·
    #   fill 95.5%→0%. A single threshold ~0.10 separates all four with wide margin.
    # =============================================================================

    FOCUS_BAND_FRAC = 0.18          # outer ring kept; inner (1-2·frac) hollowed out
    FOCUS_SAT_MIN = 80              # HSV saturation floor for an "accent" pixel
    FOCUS_VAL_MIN = 80              # HSV value floor for an "accent" pixel
    FOCUS_HUE_TOL = 12              # ± hue tolerance (OpenCV 0-179 scale) at verify
    FOCUS_DEFAULT_THRESHOLD = 0.10  # min accent coverage in learned region to be "focused"
    FOCUS_MIN_ACCENT_PIXELS = 20    # below this there's no learnable accent

    def _perimeter_band_mask(self, h: int, w: int, frac: float) -> np.ndarray:
        """Boolean mask: True on the outer `frac` ring, False in the interior."""
        m = np.ones((h, w), dtype=bool)
        mh, mw = int(h * frac), int(w * frac)
        if 0 < mh < h - mh and 0 < mw < w - mw:
            m[mh:h - mh, mw:w - mw] = False
        return m

    def _accent_pixels(self, hsv: np.ndarray, hue: int, hue_tol: int,
                       sat_min: int, val_min: int) -> np.ndarray:
        """Boolean mask of saturated pixels whose hue is within tol of `hue`
        (circular distance, so red near 0/179 wraps correctly)."""
        H = hsv[:, :, 0].astype(int)
        dh = np.minimum(np.abs(H - hue), 180 - np.abs(H - hue))
        return (dh <= hue_tol) & (hsv[:, :, 1] >= sat_min) & (hsv[:, :, 2] >= val_min)

    def _accent_coverage_in_region(self, hsv: np.ndarray, hue: int, hue_tol: int,
                                   sat_min: int, val_min: int, region,
                                   band_frac: float = None) -> float:
        """
        Fraction of pixels inside the normalized [y0,y1,x0,x1] region that are accent.

        When band_frac is given, accent is restricted to the perimeter band so the
        element's interior content never counts — e.g. for a full-border style the
        learned region spans the whole tile, but the central logo (the red YouTube/
        NETFLIX mark) must be excluded or an unfocused tile leaks coverage.
        """
        h, w = hsv.shape[:2]
        y0, y1 = int(region[0] * h), int(region[1] * h)
        x0, x1 = int(region[2] * w), int(region[3] * w)
        y0, y1 = max(0, y0), min(h, max(y0 + 1, y1))
        x0, x1 = max(0, x0), min(w, max(x0 + 1, x1))
        accent = self._accent_pixels(hsv, hue, hue_tol, sat_min, val_min)
        if band_frac is not None:
            accent = accent & self._perimeter_band_mask(h, w, band_frac)
        sub = accent[y0:y1, x0:x1]
        return float(sub.mean()) if sub.size else 0.0

    def learn_focus_accent(self, img_bgr: np.ndarray, band_frac: float = None,
                           sat_min: int = None, val_min: int = None,
                           hue_tol: int = None, threshold: float = None) -> Optional[Dict[str, Any]]:
        """
        Learn the focus-indicator accent from a single FOCUSED reference crop.

        Finds the dominant saturated hue in the perimeter band (border / underline /
        fill) and records the normalized bounding region of those accent pixels, so
        verification can re-measure accent coverage in exactly that region.

        Returns the params dict to store under area['focus'], or None when the crop
        has no clear saturated accent (caller should then warn the user that focus
        could not be learned — likely the area wasn't drawn to include the indicator).
        """
        band_frac = self.FOCUS_BAND_FRAC if band_frac is None else band_frac
        sat_min = self.FOCUS_SAT_MIN if sat_min is None else sat_min
        val_min = self.FOCUS_VAL_MIN if val_min is None else val_min
        hue_tol = self.FOCUS_HUE_TOL if hue_tol is None else hue_tol
        threshold = self.FOCUS_DEFAULT_THRESHOLD if threshold is None else threshold

        if img_bgr is None or img_bgr.size == 0:
            return None
        h, w = img_bgr.shape[:2]
        band = self._perimeter_band_mask(h, w, band_frac)
        hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
        H = hsv[:, :, 0].astype(int)

        sel = band & (hsv[:, :, 1] >= sat_min) & (hsv[:, :, 2] >= val_min)
        hues = H[sel]
        if hues.size < self.FOCUS_MIN_ACCENT_PIXELS:
            print(f"[@focus] learn: no saturated accent in perimeter band ({hues.size} px) — skipping")
            return None

        # Circular histogram peak: shift by 90 so red (0/179) doesn't split across edges.
        peak = np.bincount((hues + 90) % 180, minlength=180).argmax()
        hue = int((peak - 90) % 180)

        accent = self._accent_pixels(hsv, hue, hue_tol, sat_min, val_min) & band
        if accent.sum() < self.FOCUS_MIN_ACCENT_PIXELS:
            print(f"[@focus] learn: accent for hue={hue} too sparse ({int(accent.sum())} px) — skipping")
            return None

        ys, xs = np.where(accent)
        region = [ys.min() / h, (ys.max() + 1) / h, xs.min() / w, (xs.max() + 1) / w]
        ref_cov = self._accent_coverage_in_region(hsv, hue, hue_tol, sat_min, val_min, region, band_frac)

        params = {
            'hue': hue,
            'hue_tol': int(hue_tol),
            'sat_min': int(sat_min),
            'val_min': int(val_min),
            'band_frac': round(float(band_frac), 3),
            'region': [round(float(r), 4) for r in region],
            'threshold': round(float(threshold), 3),
            'ref_coverage': round(float(ref_cov), 4),
        }
        print(f"[@focus] learn: hue={hue} region={params['region']} ref_coverage={ref_cov:.3f} → {params}")
        return params

    def measure_focus(self, img_bgr: np.ndarray, focus_params: Dict[str, Any]) -> Tuple[float, np.ndarray]:
        """
        Measure accent coverage of a source crop against learned focus params.

        Returns (focus_score, accent_mask) where focus_score is the accent coverage
        inside the learned region and accent_mask is over the full crop (for overlays).
        """
        hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
        hue = int(focus_params['hue'])
        hue_tol = int(focus_params.get('hue_tol', self.FOCUS_HUE_TOL))
        sat_min = int(focus_params.get('sat_min', self.FOCUS_SAT_MIN))
        val_min = int(focus_params.get('val_min', self.FOCUS_VAL_MIN))
        region = focus_params.get('region', [0.0, 1.0, 0.0, 1.0])
        band_frac = focus_params.get('band_frac', self.FOCUS_BAND_FRAC)
        score = self._accent_coverage_in_region(hsv, hue, hue_tol, sat_min, val_min, region, band_frac)
        accent = self._accent_pixels(hsv, hue, hue_tol, sat_min, val_min) & self._perimeter_band_mask(*hsv.shape[:2], band_frac)
        return score, accent

    # =============================================================================
    # Screen fingerprint — Localize (probabilistic node identification)
    # =============================================================================
    #
    # A node's identity is two stacked layers (validated on 70 example_tv screens,
    # 84% pinpoint / 100% candidate-set):
    #   SCREEN layer  — a 256-bit dHash of the whole frame. Separates structurally
    #                   distinct screens; collapses sibling screens (same chrome,
    #                   different selection) into one family.
    #   FOCUS  layer  — the moving selection accent dHash throws away: the nav
    #                   underline x-position, or the focused tile/button (its
    #                   normalized position + an OCR label). This splits siblings.
    #
    # compute_fingerprint() runs at capture time; match_fingerprint() ranks a live
    # frame's fingerprint against the stored node fingerprints by EXCLUSION — it
    # returns every node not ruled out, never guesses between true ties. This is a
    # WHOLE-FRAME extractor, distinct from learn_focus_accent() which is for tight
    # verification crops (perimeter band); the focus marker here can sit anywhere.
    # =============================================================================

    FINGERPRINT_VERSION = 6   # v6: full-frame + v5 multi-region + v4 focus + focused-tile CROP (app grid)
    FP_DARK_EDGE_MIN = 3.0    # mean Canny edge below this = low-content frame (unidentifiable)

    # --- Special capture-side states (default, device-agnostic) ---------------
    # Two "you're not on any UI node" states are worth NAMING instead of returning
    # a bare "unknown": the capture card's no-input test pattern (SMPTE colour
    # bars) and a black/asleep device output. They are generated by the capture
    # hardware / device-off, so they look the SAME on every device & userinterface
    # — one classifier serves all (the user's "fingerprint it once, default for
    # all"). A stored dHash can't do it: SMPTE-bar grayscale luminance decreases
    # monotonically left→right, so its difference-hash is all-zeros — identical to
    # a black frame's. The only separable signal is simple frame statistics:
    #   black     : near-uniform AND dark           (mean & std tiny, sat ~0)
    #   no_signal : vivid, smooth, high-variance     (sat very high, Canny ~0)
    # Thresholds validated on the example_tv corpus (70 screens) with zero false
    # positives — the most saturated real screen (sat 158) has Canny 5.4, well
    # above the no_signal smoothness ceiling.
    FP_BLACK_MEAN_MAX = 25.0     # black: mean brightness below this …
    FP_BLACK_STD_MAX = 12.0      # … and near-uniform (low spatial std)
    FP_NOSIG_SAT_MIN = 160.0     # no_signal: mean HSV saturation above this …
    FP_NOSIG_CANNY_MAX = 2.0     # … smooth solid bands (few edges) …
    FP_NOSIG_STD_MIN = 40.0      # … but high brightness variance across the bars

    FP_DHASH_GRID = 16                 # 16x16 -> 256-bit dHash
    FP_DHASH_BITS = 256
    # Region fingerprint (the validated model): each node carries a region the
    # human drew once; we dHash ONLY that region (a well-chosen region is both
    # language- and content-robust — translated labels and moving heroes fall
    # outside it). Default region = whole frame.
    FP_REGION_GRID = (32, 8)           # region resized to 32x8 -> 256-bit dHash
    FP_REGION_BITS = 256
    FP_FULL_REGION = (0.0, 1.0, 0.0, 1.0)   # [y0,y1,x0,x1] default
    FP_CANDIDATE_MARGIN = 14           # nodes within (best + this) of the nearest = candidates (ties)
    FP_EXCLUDE_MARGIN = 28             # nodes beyond (best + this) = confidently excluded
    # Minimum confidence to report a match. Applied in identify_screen (the shared
    # algo) so BOTH the Localize button and the monitor overlay abstain identically
    # on weak matches — a nearest node still far in dHash (live video / no real
    # match) scores low; below this it is reported as no match ("unknown"), never
    # surfaced. Filtering lives here, not in any UI.
    FP_MIN_CONFIDENCE = 0.55
    FP_ACCENT_SAT_MIN = 150            # focus accent must be vivid (rejects muddy photo colour)
    FP_ACCENT_VAL_MIN = 120
    FP_ACCENT_HUE = 0                  # default brand accent = red (OpenCV 0-179, red wraps 0/179)
    FP_ACCENT_HUE_TOL = 8
    FP_NAV_BAND = (0.10, 0.18)         # vertical band a nav-tab underline lives in
    #   widened 0.16->0.18: some STB renders (example-v1) draw the underline lower,
    #   so the narrower band missed it entirely (focus=none → tabs indistinguishable)
    FP_NAV_X_TOL = 0.03                # nav-underline x match tolerance (settings tabs ~0.06 apart)
    FP_NAV_MAX_SPREAD = 0.25           # a localized underline, not scattered photo-red, spans < this of width
    FP_BOX_MIN_AREA = 0.01             # a focus box must cover >= this fraction of the frame
    FP_BOX_MAX_W = 0.70
    FP_BOX_MAX_H = 0.60

    # --- Title / text layer (Localize layer 3: which SCREEN, when underline ties) ---
    # The screen title is a left-aligned heading at the very top-left. A NARROW left
    # crop recovers low-contrast titles (grey 'Replay') via CLAHE+psm7 AND excludes
    # centered nav tabs (a different screen's "TV Guide" tab sits at x~0.27, not here).
    FP_TITLE_CROP = (0.02, 0.12, 0.03, 0.22)   # [y0,y1,x0,x1] title zone (far top-left)
    FP_TEXT_BAND = 0.16                # top fraction OCR'd for the structured token list
    FP_TEXT_MIN_CONF = 50             # tesseract per-word confidence floor for tokens

    def _dhash_hex(self, gray: np.ndarray) -> str:
        """256-bit difference hash of a grayscale frame, as a 64-char hex string."""
        g = self.FP_DHASH_GRID
        r = cv2.resize(gray, (g + 1, g), interpolation=cv2.INTER_AREA)
        bits = (r[:, 1:] > r[:, :-1]).flatten()
        val = 0
        for b in bits:
            val = (val << 1) | int(b)
        return format(val, 'x').zfill(self.FP_DHASH_BITS // 4)

    @staticmethod
    def _dhash_hamming(hex_a: str, hex_b: str) -> int:
        """Hamming distance between two dHash hex strings."""
        return bin(int(hex_a, 16) ^ int(hex_b, 16)).count('1')

    FP_REGION_MIN_BITS = 20   # a region dHash with fewer set bits than this is near-uniform (black /
                              # empty) — non-discriminative: it matches ANY black region at ~0 (youtube_home's
                              # dark bottom bar = poweroff). Calibrated: pure black popcount ~0, but a sparse
                              # title-on-black (the EPG "TV Guide" top region, the one discriminator) is ~34,
                              # so 20 drops the former and keeps the latter.

    def _region_dists(self, live_regions: Dict[str, str], regs: Dict[str, str]):
        """Sorted per-region distances, EXCLUDING regions that are degenerate (black/empty) on either
        side. A black candidate node (poweroff/standby) thus contributes no usable region and drops out."""
        return sorted(self._dhash_hamming(live_regions[r], regs[r]) for r in live_regions if r in regs
                      and bin(int(live_regions[r], 16)).count('1') >= self.FP_REGION_MIN_BITS
                      and bin(int(regs[r], 16)).count('1') >= self.FP_REGION_MIN_BITS)

    # v5 standard region set [y0,y1,x0,x1]. The fingerprint stores ALL five; the matcher decides which
    # to TRUST at match time (intrinsic stability) and which DISCRIMINATES (relative, vs the current node
    # set) — so adding nodes never re-evaluates old fingerprints. Audit (90 example_tv nodes): left/center
    # carry identity, top/bottom are weakest (shared chrome) but kept for other layouts. dHash is coarse,
    # so on STRUCTURED screens it absorbs full text translation (settings EN↔DE drifts ≤12 bits).
    FP_V5_REGIONS = {'full': (0, 1, 0, 1), 'top': (0, 0.20, 0, 1), 'center': (0.22, 0.78, 0.20, 0.80),
                     'left': (0, 1, 0, 0.20), 'bottom': (0.80, 1, 0, 1)}
    FP_2ND_REGION_SLACK = 30   # the 2nd-best region may be this far past the floor (content churn) and
                               # still count as the same screen; beyond it, a lone tight region is a fluke

    def _region_dhashes(self, gray: np.ndarray) -> Dict[str, str]:
        """The five v5 region dHashes (same square _dhash_hex used by the audit, so distances/floor match)."""
        h, w = gray.shape
        out = {}
        for name, (y0, y1, x0, x1) in self.FP_V5_REGIONS.items():
            crop = gray[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w)]
            out[name] = self._dhash_hex(crop if crop.size else gray)
        return out

    def _region_dhash(self, gray: np.ndarray, region) -> str:
        """256-bit dHash of a normalized [y0,y1,x0,x1] sub-region (resized to 32x8)."""
        y0, y1, x0, x1 = region
        H, W = gray.shape
        crop = gray[int(y0 * H):int(y1 * H), int(x0 * W):int(x1 * W)]
        if crop.size == 0:
            crop = gray
        gw, gh = self.FP_REGION_GRID
        r = cv2.resize(crop, (gw + 1, gh), interpolation=cv2.INTER_AREA)
        bits = (r[:, 1:] > r[:, :-1]).flatten()
        val = 0
        for b in bits:
            val = (val << 1) | int(b)
        return format(val, 'x').zfill(self.FP_REGION_BITS // 4)

    # Adaptive region: hero/carousel/video screens (home, movies) carry their
    # identity in the top nav strip — the full frame is dominated by changing
    # media. We pick the match region PER SCREEN from a single image: a large
    # connected photographic blob => 'nav', else 'full'.
    FP_NAVHASH_Y = 0.13            # nav-strip region (top fraction)
    FP_NAVHASH_GRID = (32, 6)      # -> 192-bit nav-strip dHash
    FP_NAVHASH_BITS = 192
    FP_NAV_MATCH_BAND = 30         # nav-strip match band (192-bit); home self ~24, others >=35
    FP_NAV_EXCLUDE = 60
    FP_MEDIA_THRESHOLD = 0.20      # biggest media-blob fraction => region 'nav'

    def _nav_dhash(self, gray: np.ndarray) -> str:
        """192-bit dHash of just the top nav strip (language- and content-robust)."""
        H = gray.shape[0]
        gw, gh = self.FP_NAVHASH_GRID
        r = cv2.resize(gray[0:int(self.FP_NAVHASH_Y * H), :], (gw + 1, gh), interpolation=cv2.INTER_AREA)
        bits = (r[:, 1:] > r[:, :-1]).flatten()
        val = 0
        for b in bits:
            val = (val << 1) | int(b)
        return format(val, 'x').zfill(self.FP_NAVHASH_BITS // 4)

    def _media_blob_fraction(self, img_bgr: np.ndarray) -> float:
        """Largest CONNECTED colorful/photographic region in the content area
        (below the nav), as a fraction. High => a big hero/carousel/video element
        dominates (so the screen's stable identity is its chrome). Separates a big
        movie still (one blob) from flat colorful UI tiles (many small blobs)."""
        H = img_bgr.shape[0]
        content = img_bgr[int(0.16 * H):int(0.95 * H), :]
        small = cv2.resize(content, (64, 36))
        hsv = cv2.cvtColor(small, cv2.COLOR_BGR2HSV)
        mask = ((hsv[:, :, 1] > 60) & (hsv[:, :, 2] > 50)).astype(np.uint8)
        n, _, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
        big = max([stats[i, cv2.CC_STAT_AREA] for i in range(1, n)], default=0)
        return big / (64.0 * 36.0)

    def _accent_mask(self, img_bgr: np.ndarray, hue: int = None, hue_tol: int = None) -> np.ndarray:
        """Vivid accent-colour mask over the FULL frame (handles red hue wrap)."""
        hue = self.FP_ACCENT_HUE if hue is None else hue
        hue_tol = self.FP_ACCENT_HUE_TOL if hue_tol is None else hue_tol
        hsv = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
        s, v = self.FP_ACCENT_SAT_MIN, self.FP_ACCENT_VAL_MIN
        lo, hi = (hue - hue_tol) % 180, (hue + hue_tol) % 180
        if lo <= hi:
            mask = cv2.inRange(hsv, (lo, s, v), (hi, 255, 255))
        else:  # wraps 0/179 (red)
            mask = cv2.inRange(hsv, (0, s, v), (hi, 255, 255)) | cv2.inRange(hsv, (lo, s, v), (179, 255, 255))
        return mask

    def _ocr_token(self, img_bgr: np.ndarray) -> str:
        """OCR a small crop and return its strongest single-line token (lowercased).

        Mirrors text_helpers' tesseract usage (psm 7, stdout) so we stay consistent
        with the rest of the verification stack.
        """
        if img_bgr is None or img_bgr.size == 0:
            return ''
        gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
        gray = cv2.resize(gray, None, fx=2.5, fy=2.5, interpolation=cv2.INTER_CUBIC)
        tmp = None
        try:
            tmp = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
            tmp.close()
            cv2.imwrite(tmp.name, gray)
            out = subprocess.run(['tesseract', tmp.name, 'stdout', '--psm', '7'],
                                 capture_output=True, text=True, timeout=15)
            text = ' '.join(out.stdout.split()).lower() if out.returncode == 0 else ''
            return text[:24]
        except Exception as e:
            print(f"[@fingerprint] OCR token failed: {e}")
            return ''
        finally:
            if tmp and os.path.exists(tmp.name):
                os.unlink(tmp.name)

    def _focus_signature(self, img_bgr: np.ndarray) -> Dict[str, Any]:
        """Detect the focus accent and return a focus signature.

        kind 'nav'  : a localized horizontal underline -> {'kind','x'} (tab position)
        kind 'box'  : the largest accent rectangle/border/button -> {'kind','x','y','label'}
        kind 'none' : no focus accent found (content-less / fullscreen video)
        """
        h, w = img_bgr.shape[:2]
        red = self._accent_mask(img_bgr)

        # 1) nav-tab underline (robust): a THIN, WIDE red run in the nav/tab band.
        #    Band 0.08-0.21 covers the home menu (y~.13) AND settings tabs (y~.17).
        #    Morph-close stitches the dashed underline; aspect + vertical score reject
        #    tall content-red blobs (carousel/posters). Returns x + normalized width.
        nb0, nb1 = int(0.08 * h), int(0.21 * h)
        band = cv2.morphologyEx(red[nb0:nb1, :], cv2.MORPH_CLOSE,
                                cv2.getStructuringElement(cv2.MORPH_RECT, (9, 3)))
        cnts, _ = cv2.findContours(band, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        best_u = None
        for c in cnts:
            x, y, bw, bh = cv2.boundingRect(c)
            if bw < 25 or bw > 0.20 * w or bh < 2 or bh > 12 or bw / max(bh, 1) < 6:
                continue
            ay = nb0 + y + bh / 2.0
            vscore = 1.0 / (1.0 + abs(ay - 0.12 * h))
            score = cv2.contourArea(c) + 5000 * vscore + bw
            if best_u is None or score > best_u[0]:
                best_u = (score, round((x + bw / 2) / w, 3), round(bw / w, 3))
        if best_u:
            return {'kind': 'nav', 'x': best_u[1], 'width': best_u[2]}

        # 2) focus box/button: largest vivid-accent region (border or fill)
        m = cv2.morphologyEx(red, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
        cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        best = None
        for c in cnts:
            x, y, bw, bh = cv2.boundingRect(c)
            area = bw * bh
            if area < self.FP_BOX_MIN_AREA * w * h or bw > self.FP_BOX_MAX_W * w or bh > self.FP_BOX_MAX_H * h:
                continue
            if best is None or area > best[0]:
                best = (area, (x, y, bw, bh))
        if best:
            x, y, bw, bh = best[1]
            inside = self._ocr_token(img_bgr[y:y + bh, x:x + bw])               # button text / logo
            below = self._ocr_token(img_bgr[y + bh:min(h, y + bh + 45),
                                             max(0, x - 5):min(w, x + bw + 5)])  # tile label below
            label = inside if len(inside) >= 3 else below
            return {
                'kind': 'box',
                'x': round(float((x + bw / 2) / w), 2),
                'y': round(float((y + bh / 2) / h), 2),
                'label': label if len(label) >= 3 else '',
            }
        return {'kind': 'none'}

    FP_CROP_INSET = 0.15   # drop the focus RING (same red border on every focused tile) -> hash the logo

    def _focus_crop_hex(self, img_bgr: np.ndarray) -> Optional[str]:
        """v6 layer: dHash of the FOCUSED TILE's logo, or None. Locates the focus box with the shared
        focus_detector (top candidate), insets to drop the common red ring, and hashes the interior.
        Used by compute_fingerprint (stored as fp['crop']) and by the live v6 match path. Fully
        non-fatal — any failure / no focus / no detector -> None, and v6 then falls back to v5."""
        if img_bgr is None or img_bgr.size == 0:
            return None
        try:
            try:
                from .focus_detector import detect_focus      # package import (production)
            except Exception:
                from focus_detector import detect_focus        # path import (offline/bench)
            cands = detect_focus(img_bgr)
            if not cands:
                return None
            x, y, w, h = cands[0].box
            ix, iy = int(w * self.FP_CROP_INSET), int(h * self.FP_CROP_INSET)
            crop = img_bgr[y + iy:y + h - iy, x + ix:x + w - ix]
            if crop.size == 0 or (w - 2 * ix) < 8 or (h - 2 * iy) < 8:
                crop = img_bgr[y:y + h, x:x + w]
            if crop.size == 0 or w < 8 or h < 8:
                return None
            return self._dhash_hex(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY))
        except Exception:
            return None

    # Auto region default for hero/carousel screens: the left-nav strip
    # (untranslated tabs + the active underline) — language- and content-robust.
    FP_AUTO_NAV_REGION = (0.0, 0.14, 0.0, 0.45)

    @staticmethod
    def region_from_verifications(verifications, img_w: int, img_h: int):
        """Best localize region from a node's existing IMAGE verification `area` —
        the spatial discriminator the human ALREADY drew (tab underline, focused
        tile). Prefers the fuzzy box. Text verifications are ignored (shared title).
        TINY areas (a thin underline) are rejected: too few bits, so they become
        the nearest neighbour for unrelated frames (false positives) — those nodes
        fall back to auto + the nav-underline focus layer. Returns [y0,y1,x0,x1]/None."""
        for v in (verifications or []):
            if (v.get('verification_type') or '').lower() != 'image':
                continue
            area = ((v.get('params') or {}).get('area')) or {}
            if area.get('fwidth') and area.get('fheight'):
                x, y, w, h = area.get('fx'), area.get('fy'), area['fwidth'], area['fheight']
            elif area.get('width') and area.get('height'):
                x, y, w, h = area.get('x'), area.get('y'), area['width'], area['height']
            else:
                continue
            if None in (x, y) or w <= 0 or h <= 0:
                continue
            # reject tiny regions (< 2% of frame) — non-discriminative in NN matching
            if (w / img_w) * (h / img_h) < 0.02:
                continue
            return [round(y / img_h, 4), round((y + h) / img_h, 4),
                    round(x / img_w, 4), round((x + w) / img_w, 4)]
        return None
    # Expected same-node drift (EN/GE, build-to-build) until multi-render data lets
    # us measure it. A region is non-discriminative if a DIFFERENT node hashes
    # within this distance through it (a wrong node as close as the node's own drift).
    FP_SELF_DRIFT_FLOOR = 14
    FP_NAV_REGION_FLOOR = 60           # NAV gate TRIGGER (used in identify_screen, not the matcher):
                                       # a nav match whose best region is within this many bits is
                                       # accepted outright (clearly the same screen). BEYOND it, a TITLE
                                       # match is required — because a content-heavy menu legitimately
                                       # drifts here (home's rotating hero → ~70 bits even when correct:
                                       # do NOT hard-reject), while a spurious underline on live video is
                                       # ~100+ off AND has no menu title (measured: live SRF = 118, home =
                                       # 68, home_tvguide = 71). The title is the content-robust tiebreak.

    def evaluate_region(self, my_gray: np.ndarray, region, other_grays: Dict[str, np.ndarray]) -> Dict[str, Any]:
        """Diagnostic: is `region` discriminative for THIS node vs the others?

        Hashes every OTHER node's screenshot through THIS region and reports the
        nearest, plus the set that lands within the self-drift floor (confusable).
        Pure / device-independent. other_grays: {node_id: gray}. This is the
        authoring-feedback half — it does NOT change matching.
        """
        my = self._region_dhash(my_gray, region)
        dists = sorted(
            (self._dhash_hamming(my, self._region_dhash(g, region)), oid)
            for oid, g in other_grays.items()
        )
        other_min = dists[0][0] if dists else self.FP_REGION_BITS
        confusable = [oid for d, oid in dists if d <= self.FP_SELF_DRIFT_FLOOR]
        return {
            'other_min': other_min,
            'confusable': confusable,
            'discriminative': bool(other_min > self.FP_SELF_DRIFT_FLOOR),
        }

    def compute_fingerprint(self, img_bgr: np.ndarray, region=None) -> Optional[Dict[str, Any]]:
        """Compute the Localize fingerprint for a device frame (v4).

        Two layers: full-frame dHash = the screen FAMILY; focus signature = the
        SIBLING discriminator (nav-underline x+width, or focused box). The per-node
        region model was dropped (Option B) — `region` is accepted but ignored so
        existing callers don't break. Returns None on bad input.
        """
        if img_bgr is None or img_bgr.size == 0:
            return None
        gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
        fp = {
            'v': self.FINGERPRINT_VERSION,
            'dhash': self._dhash_hex(gray),
            'regions': self._region_dhashes(gray), # v5: per-region dHashes (screen identity, content-churn
                                                    # & language robust on structured screens; see FINGERPRINT)
            'crop': self._focus_crop_hex(img_bgr),  # v6: focused-tile logo dHash (app-grid sibling); may be None
            'focus': self._focus_signature(img_bgr),
            'title': self._title_text(img_bgr),      # layer 3: which screen (raw, device language)
            'text': self._band_tokens(img_bgr),      # structured top-band tokens (kept for later)
        }
        print(f"[@fingerprint] v{fp['v']} dhash={fp['dhash'][:12]}… "
              f"focus={fp['focus']} title={fp['title']!r}")
        return fp

    @staticmethod
    def _normalize_text(s: str) -> str:
        """Lowercase, keep letters/digits/spaces, collapse whitespace. Language-neutral."""
        return ' '.join(re.sub(r'[^0-9A-Za-zÀ-ÿ ]', ' ', s or '').lower().split())

    def _tesseract(self, gray: np.ndarray, mode: str) -> str:
        """Run tesseract on a grayscale crop. mode '7'=single line, 'tsv'=boxes+conf."""
        tmp = None
        try:
            tmp = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
            tmp.close()
            cv2.imwrite(tmp.name, gray)
            args = ['tesseract', tmp.name, 'stdout'] + (['tsv'] if mode == 'tsv' else ['--psm', mode])
            out = subprocess.run(args, capture_output=True, text=True, timeout=15)
            return out.stdout if out.returncode == 0 else ''
        except Exception as e:
            print(f"[@fingerprint] tesseract({mode}) failed: {e}")
            return ''
        finally:
            if tmp and os.path.exists(tmp.name):
                os.unlink(tmp.name)

    def _title_text(self, img_bgr: np.ndarray) -> str:
        """The screen TITLE: leftmost top heading, OCR'd robustly.

        A narrow far-left crop + CLAHE + upscale + single-line OCR. CLAHE recovers
        low-contrast grey titles; the narrow crop excludes centered nav tabs (so a
        different screen's same-word tab does not collide). Returns '' when there is
        no left title (e.g. an app home whose top-left is just icons)."""
        h, w = img_bgr.shape[:2]
        y0, y1, x0, x1 = self.FP_TITLE_CROP
        crop = img_bgr[int(y0 * h):int(y1 * h), int(x0 * w):int(x1 * w)]
        if crop.size == 0:
            return ''
        g = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        g = cv2.createCLAHE(3.0, (8, 8)).apply(g)
        g = cv2.resize(g, None, fx=2.5, fy=2.5, interpolation=cv2.INTER_CUBIC)
        return self._normalize_text(self._tesseract(g, '7'))[:48]

    def _band_tokens(self, img_bgr: np.ndarray) -> List[Dict[str, Any]]:
        """Structured top-band text: [{token,x,y,w,h,size}] (positions normalized 0-100).

        Kept on the fingerprint for future scoring (font-size / position aware filters)
        without needing a re-capture. CLAHE-enhanced so low-contrast chrome survives."""
        h, w = img_bgr.shape[:2]
        band = cv2.cvtColor(img_bgr[0:int(self.FP_TEXT_BAND * h), :], cv2.COLOR_BGR2GRAY)
        band = cv2.createCLAHE(2.5, (8, 8)).apply(band)
        tokens = []
        for line in self._tesseract(band, 'tsv').splitlines()[1:]:
            c = line.split('\t')
            if len(c) < 12:
                continue
            try:
                x, y, bw, bh, conf = int(c[6]), int(c[7]), int(c[8]), int(c[9]), float(c[10])
            except ValueError:
                continue
            tok = re.sub(r'[^0-9A-Za-zÀ-ÿ]', '', c[11]).lower()
            if conf < self.FP_TEXT_MIN_CONF or len(tok) < 2:
                continue
            tokens.append({'token': tok, 'x': round(100 * x / w), 'y': round(100 * y / h),
                           'w': round(100 * bw / w), 'h': bh, 'size': bh})
        return tokens

    @staticmethod
    def title_score(a: str, b: str) -> float:
        """Similarity of two normalized title strings (0..1). 1.0 = identical.

        Char-level (difflib) so it tolerates machine-translation synonyms — a German
        'Filme' translates to 'Films' but the English UI says 'Movies'; char overlap
        still scores that ~0.7 while unrelated titles stay <0.25 — and OCR noise.
        Both titles must already be in the SAME (pivot) language (the caller
        translates). Empty on either side -> 0.0 (no signal, never a match)."""
        a, b = (a or '').strip(), (b or '').strip()
        if not a or not b:
            return 0.0
        import difflib
        return round(difflib.SequenceMatcher(None, a, b).ratio(), 3)

    # Matching bands (256-bit dHash). Tuned on the example_tv corpus, then
    # widened 24->32 to tolerate cross-render drift (live STB vs stored refs:
    # clock/selection/watermark differences push the "same" screen ~30 bits).
    FP_SCREEN_BAND = 32        # <= this Hamming dist = same screen layer (a candidate)
    FP_EXCLUDE_BAND = 60       # >  this = confidently a different screen (excluded)

    def _sample_dhashes(self, fp: Dict[str, Any]) -> List[str]:
        """Per-node sample dHash hexes (variance mask). [] when single-sample."""
        out = []
        for s in (fp.get('samples') or []):
            h = s.get('dhash') if isinstance(s, dict) else s
            if h:
                out.append(h)
        return out

    def variance_mask(self, sample_hexes: List[str]) -> Tuple[int, int, int]:
        """From N sample dHashes, return (consensus_bits, stable_mask, stable_count).

        A bit is STABLE when all samples agree on it; volatile bits (dynamic
        background: clock / carousel / video) are masked out. consensus = the
        majority bit per position. With <2 samples there's nothing to compare:
        treat all bits as stable.
        """
        nbits = self.FP_DHASH_BITS
        ints = [int(h, 16) for h in sample_hexes if h]
        n = len(ints)
        if n < 2:
            single = ints[0] if ints else 0
            return single, (1 << nbits) - 1, nbits
        consensus = 0
        stable = 0
        for pos in range(nbits):
            ones = sum((v >> pos) & 1 for v in ints)
            if ones * 2 >= n:
                consensus |= 1 << pos
            if ones == 0 or ones == n:
                stable |= 1 << pos
        return consensus, stable, bin(stable).count('1')

    def _masked_distance(self, live_hex: str, fp: Dict[str, Any]) -> int:
        """dHash Hamming, masking volatile bits when the node has >=2 samples.

        Masked distance is rescaled to the full 256-bit range so the same
        FP_SCREEN_BAND / FP_EXCLUDE_BAND thresholds apply regardless of how many
        bits survived the mask.
        """
        samples = self._sample_dhashes(fp)
        if len(samples) < 2:
            return self._dhash_hamming(live_hex, fp['dhash'])
        consensus, stable, stable_count = self.variance_mask(samples)
        diff = bin(((int(live_hex, 16) ^ consensus) & stable)).count('1')
        return int(round(diff * self.FP_DHASH_BITS / max(stable_count, 1)))

    @staticmethod
    def _focus_agreement(a: Dict[str, Any], b: Dict[str, Any]) -> float:
        """How much two focus signatures agree: 1 identical, 0 contradict, 0.5 unknown."""
        if not a or not b:
            return 0.5
        ka, kb = a.get('kind', 'none'), b.get('kind', 'none')
        if ka == 'none' or kb == 'none':
            return 0.5                                   # unknown focus: neither confirm nor exclude
        if ka != kb:
            return 0.3
        if ka == 'nav':
            if abs(a.get('x', -1) - b.get('x', -2)) > ImageHelpers.FP_NAV_X_TOL:
                return 0.0
            wa, wb = a.get('width'), b.get('width')      # same x but very different underline
            if wa is not None and wb is not None and abs(wa - wb) > 0.06:
                return 0.0                                # width = label width = different tab
            return 1.0
        # box: agree on the focused-tile POSITION (grid cell). The OCR'd label is NOT used — it is
        # unreliable (the same Netflix tile OCRs as 'netflix' on one capture, 'ans' on another), which
        # wrongly filtered out the correct node (apps_netflix) even though its box + v6 CROP were
        # identical. WHICH tile is now decided by the v6 crop tie-break + child-priority, not by OCR.
        same_pos = abs(a.get('x', -1) - b.get('x', -2)) <= 0.08 and abs(a.get('y', -1) - b.get('y', -2)) <= 0.08
        return 1.0 if same_pos else 0.0

    # Human labels + one-line hints for the named special states (shared by the
    # localize result, the offline tester, and the frontend headline).
    SPECIAL_STATE_LABELS = {
        'no_signal': 'No Signal',
        'blackscreen': 'Black Screen',
    }
    SPECIAL_STATE_HINTS = {
        'no_signal': 'No HDMI input signal.',
        'blackscreen': 'Blacksreen.',
    }

    def classify_special_state(self, img_bgr: np.ndarray) -> Optional[str]:
        """Name a capture-side non-UI state from frame statistics, else None.

        Returns 'blackscreen' (black / asleep output) or 'no_signal' (the capture
        card's SMPTE colour-bar test pattern). Device- and UI-agnostic — these
        states are produced by the capture hardware / a powered-down device, so
        the same stat thresholds apply everywhere (no per-device reference). See
        the FP_BLACK_*/FP_NOSIG_* constants for why a stored dHash can't do this.
        """
        if img_bgr is None or img_bgr.size == 0:
            return None
        gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
        mean, std = float(gray.mean()), float(gray.std())
        # Black first (cheapest, mutually exclusive with the vivid no-signal bars).
        if mean < self.FP_BLACK_MEAN_MAX and std < self.FP_BLACK_STD_MAX:
            return 'blackscreen'
        sat = float(cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)[:, :, 1].mean())
        canny = float(cv2.Canny(gray, 50, 150).mean())
        if (sat > self.FP_NOSIG_SAT_MIN and canny < self.FP_NOSIG_CANNY_MAX
                and std > self.FP_NOSIG_STD_MIN):
            return 'no_signal'
        return None

    def match_fingerprint(self, live_gray: np.ndarray, live_focus: Dict[str, Any],
                          node_fps: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Identify the live frame (v4): a nav underline IS the identity; else dHash.

        Two disjoint paths, chosen by the live focus:
          NAV  — the live frame shows a nav-tab underline. On menu screens the
                 full-frame dHash is content-dominated (carousel/clock): the SAME
                 screen drifts ~80 bits while DIFFERENT screens collide <10, so
                 dHash cannot pick the family. The underline (x + width) is the
                 identity, so we match EXCLUSIVELY by it and bypass the dHash band.
                 dHash is used only to break a genuine multi-way underline tie (two
                 different nav bars with a tab at the same x). No underline match
                 ⇒ abstain (reject the dHash-near impostors). Fail-safe.
          dHASH — no underline (content / video / focused-box screens): rank by
                 full-frame dHash, keep the near band, box/OCR focus filters within.

        Never guesses between genuine ties. Low-content frames -> empty.
        live_gray: grayscale of the live frame. node_fps: [{node_id,label,fingerprint}].
        Returns {candidates:[{node_id,label,confidence}], excluded_count, total}.
        """
        live_focus = live_focus or {}
        # dark / low-content guard: nothing to recognise on a near-empty frame
        if float(cv2.Canny(live_gray, 50, 150).mean()) < self.FP_DARK_EDGE_MIN:
            n = len(node_fps)
            return {'candidates': [], 'excluded_count': n, 'total': n, 'reason': 'low-content frame'}
        live_full = self._dhash_hex(live_gray)
        ranked = []
        for nf in node_fps:
            fp = nf.get('fingerprint') or {}
            if not fp.get('dhash') or fp.get('v') != self.FINGERPRINT_VERSION:
                continue                                     # only current-version fingerprints
            d = self._dhash_hamming(live_full, fp['dhash'])
            fa = self._focus_agreement(live_focus, fp.get('focus') or {})
            ranked.append({'node_id': nf.get('node_id'), 'label': nf.get('label'),
                           'dist': d, 'fa': fa})
        total = len(ranked)
        if not ranked:
            return {'candidates': [], 'excluded_count': 0, 'total': 0}

        def _conf(r):
            return round((1.0 - r['dist'] / self.FP_DHASH_BITS) * (0.6 + 0.4 * r['fa']), 3)

        def _pack(kept, excluded):
            cands = sorted(({'node_id': r['node_id'], 'label': r['label'],
                             'confidence': _conf(r), 'dhash_dist': r['dist']} for r in kept),
                           key=lambda c: -c['confidence'])
            return {'candidates': cands, 'excluded_count': excluded, 'total': total}

        # ── NAV PATH — the live frame shows a nav underline. The underline (x+width)
        # IS the screen identity; dHash is content-dominated on menus and must NOT
        # gate the decision. Return EVERY underline-agreeing sibling (ordered by dHash
        # for confidence only) — dHash here cannot be trusted to exclude the right one
        # (movies/replay/tvshop share x≈0.145 and differ only by a changing hero, so
        # the right screen can be the FARTHEST by dHash). The TITLE layer in localize()
        # then decides which sibling. No underline match ⇒ abstain (never fall back to
        # the unreliable dHash).
        if live_focus.get('kind') == 'nav':
            agree = [r for r in ranked if r['fa'] >= 0.99]        # x AND width agree
            if not agree:
                return {'candidates': [], 'excluded_count': total, 'total': total,
                        'reason': 'nav underline matched no node'}
            return _pack(agree, total - len(agree))

        # ── dHASH PATH — no nav underline (content / video / focused-box screens).
        # Rank by full-frame dHash, keep the near band; box/OCR focus filters within
        # the band. Three-way bucketing: candidate / excluded / uncertain-middle.
        ranked.sort(key=lambda r: r['dist'])
        best = ranked[0]['dist']
        kept, excluded = [], 0
        for r in ranked:
            in_band = r['dist'] <= best + self.FP_CANDIDATE_MARGIN
            if in_band and r['fa'] >= 0.5:
                kept.append(r)
            elif r['dist'] > best + self.FP_EXCLUDE_MARGIN or r['fa'] < 0.5:
                excluded += 1
        return _pack(kept, excluded)

    def title_pivot(self, text: str) -> str:
        """Translate a short screen title to the English pivot for matching.

        Best-effort + cached per raw title (a static menu re-OCRs the same title
        every frame; translate it at most once). Never raises: on any failure it
        returns the normalized raw text so same-language comparison still works.
        Shared by `identify_screen` so device-control and the monitor overlay pivot
        titles identically.
        """
        if not hasattr(self, '_pivot_cache'):
            self._pivot_cache = {}
        text = (text or '').strip()
        if not text:
            return ''
        if text in self._pivot_cache:
            return self._pivot_cache[text]
        out = self._normalize_text(text)
        try:
            from backend_host.src.lib.utils.translation_utils import translate_text
            r = translate_text(text, 'auto', 'en', method='auto')
            if r.get('success') and r.get('translated_text'):
                out = self._normalize_text(r['translated_text'])
        except Exception as e:
            print(f"[@image_helpers:title_pivot] translate failed ({e}); using raw")
        self._pivot_cache[text] = out
        return out

    def identify_screen(self, img_bgr: np.ndarray, node_fps: List[Dict[str, Any]]) -> Dict[str, Any]:
        """THE Localize identification: which node does this frame match?

        Single shared implementation used by BOTH NavigationExecutor.localize
        (device control / MCP) and the monitor overlay (monitor_localize) so the
        two always produce identical results from the same frame + node set.
        Pipeline: dHash+focus match → title disambiguation (look-alike menus) →
        dHash fallback narrowing → named capture-state fallback (no/black signal).
        Caller supplies node_fps (each {node_id,label,fingerprint}) loaded from its
        own cache; everything from the frame down is identical here.

        Returns the match_fingerprint dict (candidates ranked by confidence,
        excluded_count, total) plus `live_focus` and, when nothing matched,
        `state`/`state_label`/`state_hint`. No confidence floor — like the button.
        """
        gray = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
        live_focus = self._focus_signature(img_bgr)
        live_crop = self._focus_crop_hex(img_bgr)                                  # v6: focused-tile logo
        result = self.match_fingerprint_v6(gray, self._region_dhashes(gray), live_focus, live_crop, node_fps)  # v6

        is_nav = (live_focus.get('kind') == 'nav')
        fp_by_id = {nf['node_id']: (nf.get('fingerprint') or {}) for nf in node_fps}

        # Title scores (layer 3 — which SCREEN). OCR the live title ONCE and score
        # each candidate's stored title against it (both pivoted to English). Used to
        # (a) disambiguate look-alike siblings and (b) score NAV-path confidence
        # below. Only worth the OCR on the nav path or a genuine multi-way tie — a
        # single dHASH-path match needs no title.
        cands = result.get('candidates') or []
        live_title = ''   # OCR'd lazily below, then reused by every title-dependent step

        # NAV far-region / title gate. The underline picks the tab, but a SPURIOUS underline
        # on non-menu content (a red logo over live video) also "agrees" on x and would return
        # the nearest tab as a false positive (the `home_settings`-on-live bug). Proof of
        # same-screen is region distance to the menu chrome — BUT content-heavy menus
        # legitimately drift (home's huge rotating hero → ~70 bits even when CORRECT), so a
        # bare region floor wrongly rejects the real home. Resolve with the content-ROBUST
        # TITLE: a far-region nav match is kept only if the menu title corroborates; else
        # abstain. Live video has no menu title → rejected; home ("q home tv") is kept though
        # its hero rotated. (Caught by localize_regression_test.py, missed by self-match.)
        if is_nav and cands and min(c.get('dist', 999) for c in cands) > self.FP_NAV_REGION_FLOOR:
            live_title = self.title_pivot(self._title_text(img_bgr))
            if live_title:
                for c in cands:
                    c['title_score'] = self.title_score(
                        live_title, self.title_pivot(fp_by_id.get(c['node_id'], {}).get('title', '')))
            kept = [c for c in cands if c.get('title_score', 0.0) >= 0.5]
            if len(kept) < len(cands):
                result['excluded_count'] = result.get('excluded_count', 0) + (len(cands) - len(kept))
            result['candidates'] = kept
            cands = kept
            if not kept:
                result['reason'] = 'nav underline far from chrome, no title match (spurious underline / non-menu content)'

        # v5 resolves most screens by region + focus; OCR the title ONLY on a genuine tie — a DIFFERENT
        # screen within a few bits of v5's top (true look-alikes: replay/home/movies share chrome). Clear
        # winners (home, settings, the EPG) skip tesseract entirely.
        _top = cands[0] if cands else None
        v5_tie = bool(_top) and any(
            c.get('node_id') != _top.get('node_id') and c.get('label') != _top.get('label')
            and (c.get('dist', 999) - _top.get('dist', 0)) <= 3 for c in cands[1:])
        if cands and v5_tie:
            if not live_title:
                live_title = self.title_pivot(self._title_text(img_bgr))
            if live_title:
                for c in cands:
                    if 'title_score' not in c:
                        stored = self.title_pivot(fp_by_id.get(c['node_id'], {}).get('title', ''))
                        c['title_score'] = self.title_score(live_title, stored)

        # Title disambiguation. The nav path returns ALL underline siblings (look-alike
        # menus — tv guide / movies / replay share chrome AND dHash) and the right one
        # can be the FARTHEST by dHash, so the TITLE decides. Fail-safe: only filter
        # when one title clearly wins.
        if len(cands) > 1 and live_title:
            best = max(c.get('title_score', 0.0) for c in cands)
            if best >= 0.5:                                   # a real title match exists
                kept = [c for c in cands if c.get('title_score', 0.0) >= best - 0.34]
                if 0 < len(kept) < len(cands):
                    result['excluded_count'] = result.get('excluded_count', 0) + (len(cands) - len(kept))
                    result['candidates'] = kept

        # Fallback dHash narrowing — when the title couldn't decide (no title / tie),
        # fall back to the dHash near-band so a clean single-frame match still resolves
        # to one. Title first, dHash only on what it left ambiguous.
        cands = result.get('candidates') or []
        if len(cands) > 1 and all(c.get('dhash_dist') is not None for c in cands):
            best_d = min(c['dhash_dist'] for c in cands)
            near = [c for c in cands if c['dhash_dist'] <= best_d + self.FP_CANDIDATE_MARGIN]
            if 0 < len(near) < len(cands):
                result['excluded_count'] = result.get('excluded_count', 0) + (len(cands) - len(near))
                result['candidates'] = near

        # NAV-path confidence. A menu's full-frame dHash is content noise — it differs
        # ~half its bits from its own reference as promos/tiles/carousels rotate — so
        # the dHash-derived confidence is meaningless for nav screens (a correct match
        # like tvshop reads ~50%). The underline + title ARE the identity here, so
        # score confidence from the title: 0.6 for a clean underline win, up to 1.0
        # with a matching title. dHASH-path (static focused screens, where dHash IS
        # reliable) keeps its dHash-based confidence untouched.
        if is_nav:
            cands = result.get('candidates') or []
            for c in cands:
                c['confidence'] = round(0.6 + 0.4 * c.get('title_score', 0.0), 3)
            cands.sort(key=lambda c: -c['confidence'])
            result['candidates'] = cands

        # Confidence floor — drop any candidate below the minimum. A nearest match
        # that is still far in dHash (live video / no real match) scores low and is
        # not a real match. Applied here so BOTH callers abstain identically; counts
        # the dropped ones as excluded. If this empties the list, the capture-state
        # fallback below names the screen (or it reports "unknown").
        cands = result.get('candidates') or []
        if cands:
            keep = [c for c in cands if c.get('confidence', 0) >= self.FP_MIN_CONFIDENCE]
            if len(keep) < len(cands):
                result['excluded_count'] = result.get('excluded_count', 0) + (len(cands) - len(keep))
                result['candidates'] = keep

        # Named capture-side state when nothing matched (no/black signal) instead of
        # a bare "unknown". Device/UI-agnostic; only ever appears on an empty result.
        if not result.get('candidates'):
            state = self.classify_special_state(img_bgr)
            if state:
                result['state'] = state
                result['state_label'] = self.SPECIAL_STATE_LABELS.get(state)
                result['state_hint'] = self.SPECIAL_STATE_HINTS.get(state)

        result['live_focus'] = live_focus
        return result
    def match_fingerprint_v5(self, live_gray: np.ndarray, live_regions: Dict[str, str],
                             live_focus: Dict[str, Any], node_fps: List[Dict[str, Any]]) -> Dict[str, Any]:
        """v5 localize. Same two disjoint paths as v4, but the dHASH path is multi-region:
          NAV  — live frame shows a nav underline. The underline (x+width) IS the identity (tabs and
                 top-nav screens). Return every underline-agreeing sibling; no underline match ⇒ abstain.
                 (Unchanged — the underline is content/language invariant geometry.)
          dHASH — no underline. Rank by the BEST stable region instead of the full frame, so content
                 carousels and language changes don't sink the match. Screen score = the 2nd-smallest
                 region distance: a true same-screen match agrees in ≥2 regions (stable chrome); a lone
                 coincidental content-region hit is not enough. A focused box then filters within.
        Discrimination is decided HERE, against the current node set — stored fingerprints are never
        re-evaluated when nodes are added. Returns {candidates:[{node_id,label,dist}], reason}.
        """
        live_focus = live_focus or {}
        n = len(node_fps)
        def _pack5(cands, reason=None):                     # full v4-compatible contract for callers
            out = [{'node_id': c['node_id'], 'label': c['label'], 'dist': c['dist'], 'dhash_dist': c['dist'],
                    'confidence': round(max(0.0, 1.0 - c['dist'] / self.FP_DHASH_BITS), 3)} for c in cands]
            return {'candidates': out, 'excluded_count': n - len(out), 'total': n, 'reason': reason}
        if float(cv2.Canny(live_gray, 50, 150).mean()) < self.FP_DARK_EDGE_MIN:
            return _pack5([], 'low-content frame')
        def _regs_of(nf):
            fp = nf.get('fingerprint') or {}
            r = fp.get('regions') or {}
            return r if r else ({'full': fp['dhash']} if fp.get('dhash') else {})  # v4 node: full-frame only
        def _region_score(nf):
            d = self._region_dists(live_regions, _regs_of(nf))
            return d[0] if d else 999   # BEST non-degenerate region: one strongly-matching stable region
                                        # is identity (EPG: title region ~6 while the program grid churns)
        # ── NAV PATH: underline x narrows to same-tab-position siblings; REGION dHash tie-breaks (no OCR)
        if live_focus.get('kind') == 'nav':
            agree = [nf for nf in node_fps
                     if self._focus_agreement(live_focus, (nf.get('fingerprint') or {}).get('focus') or {}) >= 0.99]
            if not agree:
                return _pack5([], 'nav underline matched no node')
            # Return all underline-agreeing siblings ranked by region distance (the 'dist'
            # field). The far-region SANITY GATE that rejects a spurious underline on
            # non-menu content (red logo over live video) lives in identify_screen, NOT
            # here — it needs the TITLE to avoid rejecting a legit content-heavy menu
            # (home: a huge rotating hero drifts the region to ~70 even when correct),
            # and the matcher is title-agnostic by design.
            agree.sort(key=_region_score)
            return _pack5([{'node_id': nf.get('node_id'), 'label': nf.get('label'), 'dist': _region_score(nf)}
                           for nf in agree])
        # ── dHASH PATH (multi-region)
        scored = []
        for nf in node_fps:
            d = self._region_dists(live_regions, _regs_of(nf))   # degenerate (black) regions excluded
            if not d:
                continue
            scored.append({'node_id': nf.get('node_id'), 'label': nf.get('label'),
                           'score': d[0], 'second': d[1] if len(d) > 1 else d[0],
                           'focus': (nf.get('fingerprint') or {}).get('focus')})
        if not scored:
            return _pack5([], 'no v5 region fingerprints')
        # Qualify: ONE region matches tightly (≤ floor) AND a 2nd region is not a different screen
        # (≤ floor + FP_2ND_REGION_SLACK). The 2nd-region guard rejects a single low-content/black-region
        # coincidence (a dark area matching at 0 while the frames are 70+ apart full-frame) WITHOUT
        # demanding two TIGHT regions — the EPG has only one stable region (its title); the grid churns.
        qual = [s for s in scored if s['score'] <= self.FP_SELF_DRIFT_FLOOR
                and s['second'] <= self.FP_SELF_DRIFT_FLOOR + self.FP_2ND_REGION_SLACK]
        if not qual:
            return _pack5([], f"no qualifying screen (best region {min(s['score'] for s in scored)})")
        qual.sort(key=lambda s: s['score'])
        band = qual[0]['score'] + self.FP_CANDIDATE_MARGIN
        screen = [s for s in qual if s['score'] <= band]
        if len(screen) > 1 and live_focus.get('kind') not in (None, 'none'):   # focused box -> which element
            refined = [s for s in screen if self._focus_agreement(live_focus, s.get('focus') or {}) >= 0.99]
            if refined:
                screen = refined
        return _pack5([{'node_id': s['node_id'], 'label': s['label'], 'dist': s['score']}
                       for s in sorted(screen, key=lambda s: s['score'])])

    def match_fingerprint_v6(self, live_gray: np.ndarray, live_regions: Dict[str, str],
                             live_focus: Dict[str, Any], live_crop: Optional[str],
                             node_fps: List[Dict[str, Any]]) -> Dict[str, Any]:
        """v6 = v5 + a focused-element CROP tie-break. AUDIT-ONLY: the per-node crop dHash is
        injected into fp['crop'] by the bench harness (not stored in the DB yet), and `live_crop`
        is the focus-crop dHash of the live frame, computed by the caller from the BGR image
        (the focus detector needs colour, which this matcher does not receive).

        Rationale: on the app grid every tile shares the SAME chrome, so v5's region score ties
        them (apps_joyn ≈ apps_hbomax within the floor) and v5 picks the wrong one on drift. The
        only signal that separates them is the FOCUSED TILE's logo. So among v5's candidates,
        re-rank by the focused-crop dHash distance; region distance breaks crop ties. Only the
        candidates that actually carry a crop are reordered (a crop-less candidate keeps its v5
        place), and with no live_crop / <2 candidates v6 == v5 exactly — so it never regresses v5.

        GATE — crop only when focus kind == 'box' (a discrete focused TILE: the app grid). On 'nav'
        menus / content screens the "focused element" is a churning poster, so its crop is unstable
        and re-ranking by it WRECKS them (measured: ungated v6 broke replay/movies on drift, 46->43).
        A nav underline IS the identity there; the crop must never override it.
        """
        res = self.match_fingerprint_v5(live_gray, live_regions, live_focus, node_fps)
        cands = res.get('candidates') or []
        if (live_focus or {}).get('kind') != 'box' or not live_crop or len(cands) < 2:
            return res
        by_id = {nf.get('node_id'): nf for nf in node_fps}

        def node_crop(c):
            return (by_id.get(c['node_id'], {}).get('fingerprint') or {}).get('crop')

        with_crop = [c for c in cands if node_crop(c)]
        without = [c for c in cands if not node_crop(c)]
        if len(with_crop) < 2:
            return res
        with_crop.sort(key=lambda c: (self._dhash_hamming(live_crop, node_crop(c)), c.get('dist', 0)))
        res['candidates'] = with_crop + without
        res['reason'] = (res.get('reason') or '') + ' +v6crop'
        return res

    # =============================================================================
    # Icon detection — shape match of a transport glyph over arbitrary video
    # =============================================================================
    #
    # Template matching (TM/L1/pixel-diff) answers "is THIS bitmap on screen?".
    # It fails for transport-control icons (play ► / pause ❚❚ / stop ■ / fast-
    # forward ►► / rewind ◄◄ / question ?) because they are drawn over LIVE VIDEO:
    # the pixels behind and around the glyph change every frame, so a raw-pixel
    # matcher gets dragged around by the background instead of the symbol.
    #
    # The fix the user asked for: throw the background away first (binarize to a
    # clean glyph silhouette), then compare SHAPES, not pixels.
    #
    # Pipeline per frame (source area already cropped by the caller):
    #   1. binarize_glyph()  — isolate the white/light glyph from the dimmed OSD
    #      background: grayscale → Otsu (auto-adapts to brightness drift),
    #      AND-gated with a low-saturation / high-value mask (drops COLOURED
    #      bright video), morphological close+open, then keep only plausibly-
    #      sized, roughly-central connected components (pause/FF legitimately
    #      have two blobs — both kept; border-hugging background bleed dropped).
    #   2. normalize_glyph() — crop to the glyph bbox and fit it, aspect-ratio
    #      PRESERVED, centred into a 64×64 canvas. This makes the match position-
    #      and scale-invariant (OSD placement varies across devices) while the
    #      preserved aspect keeps play (tall) distinct from fast-forward (wide).
    #   3. match_icon()      — tolerant Intersection-over-Union of the source
    #      silhouette against the chosen built-in glyph. IoU is deliberately
    #      rotation-SENSITIVE (a rotated triangle is a different symbol), which
    #      is exactly why it beats Hu-moment cv2.matchShapes here. Score 0..1,
    #      1.0 = identical silhouette — same convention as image threshold.
    #
    # The reference glyphs are synthesised with cv2 drawing (no asset files to
    # ship) because transport symbols are universal standard shapes, and run
    # through the identical normalize step once, then cached.
    # =============================================================================

    ICON_NAMES = ['play', 'pause', 'stop', 'fast_forward', 'rewind', 'question_mark']

    ICON_NORM_SIZE = 64             # canonical square the silhouette is fit into
    ICON_SAT_MAX = 90               # HSV saturation ceiling for a "white glyph" pixel
    ICON_VAL_MIN = 110              # HSV value floor for a "white glyph" pixel
    ICON_MIN_COMP_FRAC = 0.004      # connected component must be ≥ this frac of the area
    ICON_MAX_COMP_FRAC = 0.75       # ... and ≤ this (rejects whole-frame floods)
    ICON_DILATE_TOL = 2             # px dilation before IoU — tolerates stroke-width drift

    def _builtin_glyph_mask(self, name: str, size: int = 200) -> Optional[np.ndarray]:
        """Synthesise a filled white glyph (uint8 0/255) on a black square canvas."""
        c = np.zeros((size, size), dtype=np.uint8)
        m = int(size * 0.20)            # margin from the canvas edge
        if name == 'play':
            pts = np.array([[m, m], [m, size - m], [size - m, size // 2]], dtype=np.int32)
            cv2.fillPoly(c, [pts], 255)
        elif name == 'pause':
            bw = int(size * 0.18); gap = int(size * 0.14)
            x1 = size // 2 - gap // 2 - bw
            x2 = size // 2 + gap // 2
            cv2.rectangle(c, (x1, m), (x1 + bw, size - m), 255, -1)
            cv2.rectangle(c, (x2, m), (x2 + bw, size - m), 255, -1)
        elif name == 'stop':
            cv2.rectangle(c, (m, m), (size - m, size - m), 255, -1)
        elif name in ('fast_forward', 'rewind'):
            mid = size // 2
            tw = int(size * 0.30)       # width of each triangle
            top, bot = m, size - m
            # two side-by-side triangles; rewind is the horizontal mirror of FF
            t1 = np.array([[m, top], [m, bot], [m + tw, mid]], dtype=np.int32)
            t2 = np.array([[m + tw, top], [m + tw, bot], [m + 2 * tw, mid]], dtype=np.int32)
            cv2.fillPoly(c, [t1, t2], 255)
            if name == 'rewind':
                c = cv2.flip(c, 1)
        elif name in ('question_mark', 'question'):
            cv2.putText(c, '?', (int(size * 0.27), int(size * 0.80)),
                        cv2.FONT_HERSHEY_SIMPLEX, size / 80.0, 255, int(size * 0.07), cv2.LINE_AA)
        else:
            return None
        return c

    def _reference_glyph(self, name: str) -> Optional[np.ndarray]:
        """Normalised 64×64 silhouette of a built-in glyph, cached per name."""
        if not hasattr(self, '_glyph_cache'):
            self._glyph_cache = {}
        if name not in self._glyph_cache:
            raw = self._builtin_glyph_mask(name)
            self._glyph_cache[name] = self.normalize_glyph(raw)[0] if raw is not None else None
        return self._glyph_cache[name]

    def binarize_glyph(self, crop_bgr: np.ndarray) -> np.ndarray:
        """
        Isolate a white/light transport glyph from its (typically dimmed) OSD
        background. Returns a cleaned binary mask (uint8 0/255) the size of the crop.
        """
        gray = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2GRAY)
        # Otsu: glyph is the bright class over the darkened scrim. Auto-adapts so
        # brightness drift between frames/devices doesn't need a fixed threshold.
        _, otsu = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        # Low-saturation / high-value gate: keeps white/grey, drops COLOURED bright
        # video that Otsu would otherwise let through.
        hsv = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2HSV)
        white = ((hsv[:, :, 1] < self.ICON_SAT_MAX) &
                 (hsv[:, :, 2] > self.ICON_VAL_MIN)).astype(np.uint8) * 255
        mask = cv2.bitwise_and(otsu, white)
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, k)   # reconnect anti-aliased gaps
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, k)    # kill speckle
        return self._filter_glyph_components(mask)

    def _filter_glyph_components(self, mask: np.ndarray) -> np.ndarray:
        """Keep plausibly-sized, roughly-central blobs; drop specks, floods and
        border-hugging background bleed."""
        n, labels, stats, centroids = cv2.connectedComponentsWithStats(mask, 8)
        h, w = mask.shape
        out = np.zeros_like(mask)
        total = float(h * w)
        cx, cy = w / 2.0, h / 2.0
        for i in range(1, n):
            x, y, bw, bh, area_px = stats[i]
            frac = area_px / total
            if frac < self.ICON_MIN_COMP_FRAC or frac > self.ICON_MAX_COMP_FRAC:
                continue
            touches_border = (x <= 1 or y <= 1 or x + bw >= w - 1 or y + bh >= h - 1)
            ccx, ccy = centroids[i]
            central = abs(ccx - cx) < 0.42 * w and abs(ccy - cy) < 0.45 * h
            if touches_border and not central:
                continue
            out[labels == i] = 255
        return out

    def normalize_glyph(self, mask: np.ndarray, size: int = None) -> Tuple[Optional[np.ndarray], Dict[str, Any]]:
        """
        Crop to the glyph bbox and fit it (aspect ratio PRESERVED) centred into a
        size×size canvas. Returns (canvas_uint8_0_255 or None, meta) where meta has
        aspect ratio, connected-component count and fill fraction for logging.
        """
        size = self.ICON_NORM_SIZE if size is None else size
        if mask is None:
            return None, {'empty': True}
        ys, xs = np.where(mask > 0)
        if xs.size == 0:
            return None, {'empty': True}
        x0, x1, y0, y1 = int(xs.min()), int(xs.max()), int(ys.min()), int(ys.max())
        glyph = mask[y0:y1 + 1, x0:x1 + 1]
        gh, gw = glyph.shape
        n_comp = cv2.connectedComponentsWithStats(glyph, 8)[0] - 1
        meta = {'aspect': round(gw / gh, 3) if gh else 0.0,
                'n_comp': int(n_comp),
                'fill': round(float(glyph.mean()) / 255.0, 3),
                'empty': False}
        scale = size / float(max(gh, gw))
        nh, nw = max(1, int(round(gh * scale))), max(1, int(round(gw * scale)))
        resized = cv2.resize(glyph, (nw, nh), interpolation=cv2.INTER_AREA)
        canvas = np.zeros((size, size), dtype=np.uint8)
        oy, ox = (size - nh) // 2, (size - nw) // 2
        canvas[oy:oy + nh, ox:ox + nw] = resized
        canvas = ((canvas > 127).astype(np.uint8)) * 255
        return canvas, meta

    def _tolerant_iou(self, a: np.ndarray, b: np.ndarray) -> float:
        """IoU of two 0/255 masks with a small dilation tolerance so a slightly
        thicker/thinner stroke isn't penalised."""
        ab = (a > 0); bb = (b > 0)
        union = np.logical_or(ab, bb).sum()
        if union == 0:
            return 0.0
        if self.ICON_DILATE_TOL > 0:
            k = cv2.getStructuringElement(
                cv2.MORPH_ELLIPSE,
                (2 * self.ICON_DILATE_TOL + 1, 2 * self.ICON_DILATE_TOL + 1))
            ad = cv2.dilate(a, k) > 0
            bd = cv2.dilate(b, k) > 0
            inter = (np.logical_and(ab, bd).sum() + np.logical_and(bb, ad).sum()) / 2.0
        else:
            inter = np.logical_and(ab, bb).sum()
        return float(min(1.0, inter / float(union)))

    def match_icon(self, crop_bgr: np.ndarray, icon_name: str) -> Tuple[float, Dict[str, Any]]:
        """
        Score how well the chosen built-in glyph appears in an already-cropped
        source area. Returns (iou_score 0..1, details) where details carries the
        normalised source silhouette + meta for debugging/overlays.
        """
        ref = self._reference_glyph(icon_name)
        if ref is None:
            return 0.0, {'error': f"unknown icon '{icon_name}' (valid: {', '.join(self.ICON_NAMES)})"}
        if crop_bgr is None or crop_bgr.size == 0:
            return 0.0, {'empty_crop': True}
        src_mask = self.binarize_glyph(crop_bgr)
        src_norm, meta = self.normalize_glyph(src_mask)
        if src_norm is None:
            # No glyph isolated → 0.0 (correct "absent" signal for disappear).
            return 0.0, {**meta, 'icon': icon_name}
        score = self._tolerant_iou(src_norm, ref)
        details = {'icon': icon_name, 'iou': round(score, 4), **meta,
                   'source_norm': src_norm, 'reference_norm': ref}
        print(f"[@icon] '{icon_name}': iou={score:.3f} "
              f"(src aspect={meta['aspect']} n_comp={meta['n_comp']} fill={meta['fill']})")
        return score, details

    # =============================================================================
    # Core Operation 2: Image Cropping
    # =============================================================================
    
    def crop_image_to_area(self, image_source_path: str, image_cropped_path: str, area: Dict[str, Any]) -> bool:
        """
        Core function: Crop image to specific area.
        1. Load source image
        2. Validate area bounds
        3. Crop and save to target path
        """
        try:
            if not os.path.exists(image_source_path):
                print(f"[@image_helpers] Source image not found: {image_source_path}")
                return False
            
            if not self.validate_area(area):
                print(f"[@image_helpers] Invalid area coordinates: {area}")
                return False
            
            # Load image
            img = cv2.imread(image_source_path)
            if img is None:
                print(f"[@image_helpers] Failed to load image: {image_source_path}")
                return False
            
            # Extract coordinates
            x = int(area['x'])
            y = int(area['y'])
            width = int(area['width'])
            height = int(area['height'])
            
            # Validate bounds
            img_height, img_width = img.shape[:2]
            if x < 0 or y < 0 or x + width > img_width or y + height > img_height:
                print(f"[@image_helpers] Crop area out of bounds: {area} for image {img_width}x{img_height}")
                return False
            
            # Crop image
            cropped_img = img[y:y+height, x:x+width]
            
            # Save cropped image
            success = cv2.imwrite(image_cropped_path, cropped_img)
            if success:
                print(f"[@image_helpers] Successfully cropped image: {image_cropped_path}")
                return True
            else:
                print(f"[@image_helpers] Failed to save cropped image: {image_cropped_path}")
                return False
                
        except Exception as e:
            print(f"[@image_helpers] Error cropping image: {e}")
            return False
    
    # =============================================================================
    # Core Operation 3: Image Processing (Filters)
    # =============================================================================
    
    def apply_image_filter(self, image_path: str, filter_type: str) -> bool:
        """
        Core function: Apply image filter.
        1. Load image
        2. Apply filter (greyscale/binary)
        3. Save filtered image
        """
        try:
            if filter_type == 'none' or not filter_type:
                return True  # No filtering needed
                
            # Read image
            img = cv2.imread(image_path)
            if img is None:
                print(f"[@image_helpers] Failed to load image for filtering: {image_path}")
                return False
            
            if filter_type == 'greyscale':
                # Convert to grayscale
                processed_img = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                # Convert back to 3-channel for consistent format
                processed_img = cv2.cvtColor(processed_img, cv2.COLOR_GRAY2BGR)
                
            elif filter_type == 'binary':
                # Convert to grayscale first
                gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                # Apply binary threshold
                _, binary = cv2.threshold(gray, 127, 255, cv2.THRESH_BINARY)
                # Convert back to 3-channel
                processed_img = cv2.cvtColor(binary, cv2.COLOR_GRAY2BGR)
                
            else:
                print(f"[@image_helpers] Unknown filter type: {filter_type}")
                return False
            
            # Save processed image
            success = cv2.imwrite(image_path, processed_img)
            if success:
                print(f"[@image_helpers] Applied {filter_type} filter to: {image_path}")
            else:
                print(f"[@image_helpers] Failed to save filtered image: {image_path}")
            
            return success
            
        except Exception as e:
            print(f"[@image_helpers] Error applying filter: {e}")
            return False
    
    def remove_background(self, image_path: str, method: str = 'opencv') -> bool:
        """
        Core function: Remove background from image.
        1. Load image
        2. Apply background removal (opencv or rembg)
        3. Save processed image
        """
        try:
            if not os.path.exists(image_path):
                print(f"[@image_helpers] Image not found for background removal: {image_path}")
                return False
            
            if method == 'opencv':
                return self._remove_background_opencv(image_path)
            elif method == 'rembg':
                return self._remove_background_rembg(image_path)
            else:
                print(f"[@image_helpers] Unknown background removal method: {method}")
                return False
                
        except Exception as e:
            print(f"[@image_helpers] Error in background removal: {e}")
            return False
    
    def _remove_background_opencv(self, image_path: str) -> bool:
        """Remove background using OpenCV-based method."""
        try:
            # Load image
            img = cv2.imread(image_path)
            if img is None:
                return False
            
            # Convert to HSV for better color segmentation
            hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
            
            # Create mask for background (assuming white/light background)
            lower_white = np.array([0, 0, 200])
            upper_white = np.array([180, 30, 255])
            mask = cv2.inRange(hsv, lower_white, upper_white)
            
            # Invert mask to get foreground
            mask_inv = cv2.bitwise_not(mask)
            
            # Apply mask
            result = cv2.bitwise_and(img, img, mask=mask_inv)
            
            # Make background transparent by converting to RGBA
            result_rgba = cv2.cvtColor(result, cv2.COLOR_BGR2BGRA)
            result_rgba[:, :, 3] = mask_inv  # Set alpha channel
            
            # Save as PNG to preserve transparency
            success = cv2.imwrite(image_path, result_rgba)
            if success:
                print(f"[@image_helpers] Background removed using OpenCV: {image_path}")
            
            return success
            
        except Exception as e:
            print(f"[@image_helpers] OpenCV background removal error: {e}")
            return False
    
    def _remove_background_rembg(self, image_path: str) -> bool:
        """Remove background using rembg library."""
        try:
            # Use rembg command line tool
            output_path = f"{image_path}_nobg.png"
            result = subprocess.run(
                ['rembg', 'i', image_path, output_path],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            if result.returncode == 0 and os.path.exists(output_path):
                # Replace original with processed
                shutil.move(output_path, image_path)
                print(f"[@image_helpers] Background removed using rembg: {image_path}")
                return True
            else:
                print(f"[@image_helpers] rembg failed: {result.stderr}")
                return False
                
        except subprocess.TimeoutExpired:
            print(f"[@image_helpers] rembg timeout for: {image_path}")
            return False
        except Exception as e:
            print(f"[@image_helpers] rembg error: {e}")
            return False
    
    # =============================================================================
    # Core Operation 4: Image Saving/Copying
    # =============================================================================
    
    def copy_image_file(self, image_source_path: str, image_target_path: str) -> bool:
        """
        Core function: Copy image file.
        1. Validate source exists
        2. Create target directory
        3. Copy file
        """
        try:
            if not os.path.exists(image_source_path):
                print(f"[@image_helpers] Source image not found: {image_source_path}")
                return False
            
            # Copy the image
            shutil.copy2(image_source_path, image_target_path)
            print(f"[@image_helpers] Copied image: {image_source_path} -> {image_target_path}")
            
            return True
            
        except Exception as e:
            print(f"[@image_helpers] Error copying image: {e}")
            return False
    
    def create_filtered_versions(self, image_path: str) -> None:
        """Create greyscale and binary versions of an image."""
        try:
            # Get base path and extension
            base_path, ext = os.path.splitext(image_path)
            
            # Create greyscale version
            greyscale_path = f"{base_path}_greyscale{ext}"
            shutil.copy2(image_path, greyscale_path)
            if self.apply_image_filter(greyscale_path, 'greyscale'):
                print(f"[@image_helpers] Created greyscale version: {greyscale_path}")
            
            # Create binary version
            binary_path = f"{base_path}_binary{ext}"
            shutil.copy2(image_path, binary_path)
            if self.apply_image_filter(binary_path, 'binary'):
                print(f"[@image_helpers] Created binary version: {binary_path}")
                
        except Exception as e:
            print(f"[@image_helpers] Error creating filtered versions: {e}")
    
    # =============================================================================
    # Utility Functions
    # =============================================================================
    
    def validate_area(self, area: Dict[str, Any]) -> bool:
        """Validate that area contains required coordinates."""
        if not area:
            return False
        required_keys = ['x', 'y', 'width', 'height']
        return all(key in area and isinstance(area[key], (int, float)) for key in required_keys)
    
    def get_unique_filename(self, base_name: str, extension: str = '.png') -> str:
        """Generate unique filename with timestamp."""
        timestamp = int(time.time() * 1000)
        return f"{base_name}_{timestamp}{extension}"
