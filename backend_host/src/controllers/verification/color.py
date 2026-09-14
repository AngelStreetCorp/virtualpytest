"""
Color Verification Controller

Detects whether a region on screen is a target color (within tolerance, with a
minimum coverage). Built for focus-underline / status-LED / blackscreen-style
checks where authoring an image reference is overkill: you only care that
"≥ N % of pixels in this region are within ±tol of #RRGGBB".

Why a dedicated primitive?
- `waitForImageToAppear` does template matching (TM_CCOEFF_NORMED) which is
  unstable on tiny uniform-color references — see image_helpers's L1 fallback.
- Color is a simpler, more honest contract: define the color + region + coverage
  threshold, no reference upload, no JPEG re-compression artefacts, no
  intensity-correlation algebra.
- Use cases: tab-focus underlines, LED on/off, "screen is black" checks,
  notification badges.
"""

import time
import os
import re
import cv2
import numpy as np
from typing import Dict, Any, Tuple


class ColorVerificationController:
    """Detect a target colour in a screen region with coverage threshold."""

    def __init__(self, av_controller, **kwargs):
        from shared.src.lib.utils.storage_path_utils import get_capture_storage_path

        self.av_controller = av_controller
        self.captures_path = get_capture_storage_path(av_controller.video_capture_path, 'captures')
        self.verification_type = 'color'
        print(f"[@controller:ColorVerification] Initialized")
        self.verification_session_id = f"color_verify_{int(time.time())}"

    def connect(self) -> bool:
        return True

    def disconnect(self) -> bool:
        return True

    def get_status(self) -> Dict[str, Any]:
        return {
            'connected': True,
            'av_controller': self.av_controller.device_name if self.av_controller else None,
            'controller_type': 'color',
            'captures_path': self.captures_path,
        }

    # ---------- core ----------

    @staticmethod
    def _parse_color(color: Any) -> Tuple[int, int, int]:
        """Accept '#RRGGBB' / 'RRGGBB' / [r,g,b] / {'r':,'g':,'b':} → (B,G,R)."""
        if isinstance(color, (list, tuple)) and len(color) == 3:
            r, g, b = [int(c) for c in color]
        elif isinstance(color, dict) and {'r', 'g', 'b'}.issubset(color):
            r, g, b = int(color['r']), int(color['g']), int(color['b'])
        elif isinstance(color, str):
            s = color.strip().lstrip('#')
            if not re.fullmatch(r'[0-9a-fA-F]{6}', s):
                raise ValueError(f"invalid hex colour: {color!r}")
            r, g, b = int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16)
        else:
            raise ValueError(f"unsupported colour format: {color!r}")
        return (b, g, r)  # OpenCV uses BGR

    def _coverage(self, source_path: str, area: Dict[str, Any], color_bgr: Tuple[int, int, int],
                  tolerance: int) -> Tuple[float, int, int]:
        """Returns (coverage_fraction, matching_pixels, total_pixels)."""
        img = cv2.imread(source_path, cv2.IMREAD_COLOR)
        if img is None:
            return 0.0, 0, 0
        if area:
            x, y = int(area['x']), int(area['y'])
            w, h = int(area['width']), int(area['height'])
            ih, iw = img.shape[:2]
            if x < 0 or y < 0 or x + w > iw or y + h > ih or w <= 0 or h <= 0:
                return 0.0, 0, 0
            patch = img[y:y + h, x:x + w]
        else:
            patch = img
        target = np.array(color_bgr, dtype=np.int16)
        diff = np.abs(patch.astype(np.int16) - target).max(axis=2)  # max channel delta per pixel
        matching = int((diff <= tolerance).sum())
        total = int(patch.shape[0] * patch.shape[1])
        return (matching / total) if total else 0.0, matching, total

    def waitForColorToAppear(self, color: Any, area: Dict[str, Any], tolerance: int = 30,
                             coverage: float = 0.7, timeout: float = 1.0,
                             invert: bool = False) -> Tuple[bool, str, Dict[str, Any]]:
        """
        Pass when ≥ `coverage` fraction of pixels in `area` are within ±`tolerance`
        per-channel of `color`. `timeout` is seconds to keep retrying. `invert=True`
        flips the predicate (use it for "screen is NOT colour X" checks like
        "blackscreen disappeared").
        """
        if timeout > 30:
            timeout = 30  # safety cap mirrors image controller
        try:
            color_bgr = self._parse_color(color)
        except ValueError as e:
            return False, str(e), {}

        deadline = time.time() + max(0.0, float(timeout))
        attempts = 0
        best = {'fraction': 0.0, 'matching': 0, 'total': 0, 'source_path': None}

        while True:
            attempts += 1
            source_path = self.av_controller.take_screenshot()
            if not source_path or not os.path.exists(source_path):
                return False, 'failed to capture source frame', {'attempts': attempts}
            fraction, matching, total = self._coverage(source_path, area, color_bgr, int(tolerance))
            if fraction > best['fraction']:
                best.update({'fraction': fraction, 'matching': matching, 'total': total, 'source_path': source_path})
            ok = (fraction >= float(coverage)) ^ bool(invert)
            if ok:
                return True, f"coverage {fraction:.3f} >= {coverage:.3f} (invert={invert})", {
                    'matching_result': fraction,
                    'user_threshold': coverage,
                    'matching_pixels': matching,
                    'total_pixels': total,
                    'attempts': attempts,
                    'source_image_path': source_path,
                    'color_bgr': list(color_bgr),
                    'tolerance': int(tolerance),
                    'invert': bool(invert),
                }
            if time.time() >= deadline:
                break

        return False, f"coverage {best['fraction']:.3f} < {coverage:.3f} after {attempts} attempts (invert={invert})", {
            'matching_result': best['fraction'],
            'user_threshold': coverage,
            'matching_pixels': best['matching'],
            'total_pixels': best['total'],
            'attempts': attempts,
            'source_image_path': best['source_path'],
            'color_bgr': list(color_bgr),
            'tolerance': int(tolerance),
            'invert': bool(invert),
        }

    def waitForColorToDisappear(self, color: Any, area: Dict[str, Any], tolerance: int = 30,
                                coverage: float = 0.7, timeout: float = 1.0) -> Tuple[bool, str, Dict[str, Any]]:
        return self.waitForColorToAppear(color, area, tolerance, coverage, timeout, invert=True)

    # ---------- route surface ----------

    def execute_verification(self, verification_config: Dict[str, Any]) -> Dict[str, Any]:
        try:
            params = verification_config.get('params', {}) or {}
            command = verification_config.get('command', 'waitForColorToAppear')

            color = params.get('color')
            if color is None:
                return {'success': False, 'message': 'color parameter is required', 'screenshot_path': None}
            area = params.get('area')
            if not area:
                return {'success': False, 'message': 'area parameter is required', 'screenshot_path': None}
            tolerance = int(params.get('tolerance', 30))
            coverage = float(params.get('coverage', 0.7))
            # `timeout` ms → seconds (matches image controller convention).
            timeout = float(params.get('timeout', 1000)) / 1000.0
            invert = bool(params.get('invert', False))

            if command == 'waitForColorToAppear':
                success, message, details = self.waitForColorToAppear(color, area, tolerance, coverage, timeout, invert)
            elif command == 'waitForColorToDisappear':
                success, message, details = self.waitForColorToDisappear(color, area, tolerance, coverage, timeout)
            else:
                return {'success': False, 'message': f'Unknown color verification command: {command}',
                        'screenshot_path': None}

            return {
                'success': success,
                'message': message,
                'screenshot_path': details.get('source_image_path'),
                'matching_result': details.get('matching_result', 0.0),
                'user_threshold': details.get('user_threshold', coverage),
                'details': details,
            }

        except Exception as e:
            print(f"[@controller:ColorVerification] Execution error: {e}")
            import traceback
            traceback.print_exc()
            return {'success': False, 'message': f'Color verification execution error: {e}',
                    'screenshot_path': None}

    def get_available_verifications(self) -> list:
        from shared.src.lib.schemas.param_types import create_param, ParamType
        return [
            {
                'command': 'waitForColorToAppear',
                'verification_type': 'color',
                'label': 'Wait for Color to Appear',
                'description': '≥ coverage fraction of pixels in area within ±tolerance per-channel of color',
                'params': {
                    'color': create_param(ParamType.STRING, required=True, default='#FF0000',
                                          description="Hex (#RRGGBB), '[r,g,b]', or {r,g,b}"),
                    'area': create_param(ParamType.AREA, required=True, default=None,
                                         description='Region of interest in source frame'),
                    'tolerance': create_param(ParamType.NUMBER, required=False, default=30,
                                              description='Max per-channel delta 0–255', min=0, max=255),
                    'coverage': create_param(ParamType.NUMBER, required=False, default=0.7,
                                             description='Minimum fraction of pixels matching (0–1)',
                                             min=0.0, max=1.0),
                    'timeout': create_param(ParamType.NUMBER, required=False, default=1000,
                                            description='Total wait time (ms)'),
                    'invert': create_param(ParamType.BOOLEAN, required=False, default=False,
                                           description='Invert predicate (color absent)'),
                },
            },
            {
                'command': 'waitForColorToDisappear',
                'verification_type': 'color',
                'label': 'Wait for Color to Disappear',
                'description': 'Inverse of waitForColorToAppear',
                'params': {
                    'color': create_param(ParamType.STRING, required=True, default='#FF0000', description='Color'),
                    'area': create_param(ParamType.AREA, required=True, default=None, description='Region'),
                    'tolerance': create_param(ParamType.NUMBER, required=False, default=30, min=0, max=255),
                    'coverage': create_param(ParamType.NUMBER, required=False, default=0.7, min=0.0, max=1.0),
                    'timeout': create_param(ParamType.NUMBER, required=False, default=1000),
                },
            },
        ]
