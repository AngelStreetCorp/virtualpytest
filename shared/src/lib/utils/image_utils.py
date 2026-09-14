"""
Image Utilities - Advanced Image Analysis & Quality Assessment

Provides comprehensive utilities for:
- Image quality assessment using multi-metric analysis:
  * BRISQUE (Blind/Referenceless Image Spatial Quality Evaluator)
  * Multi-algorithm sharpness detection (Laplacian, Tenengrad, FFT, Edge density)
  * Noise level estimation
  * Contrast analysis
- Image defect detection (blackscreen, freeze, macroblocks)
- Image preprocessing for detection algorithms
- Subtitle/OCR detection with language identification

All quality metrics are resolution-normalized and use weighted combinations for robust assessment.
"""

import os
import re
from typing import Optional, Tuple, Dict, Any
import cv2
import numpy as np

try:
    import pytesseract
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False

try:
    from langdetect import detect, LangDetectException
    LANG_DETECT_AVAILABLE = True
except ImportError:
    LANG_DETECT_AVAILABLE = False


# =============================================================================
# Image Quality Assessment Functions
# =============================================================================

def compute_composite_note(image_path: str, brisque_model_path: str = None, brisque_range_path: str = None) -> Optional[Dict[str, Any]]:
    """
    Compute a composite quality note for an image using multiple advanced metrics.

    Combines BRISQUE score, multi-metric sharpness analysis, noise level, and contrast 
    into a single quality score from 0-10 (10 being best quality).

    Sharpness Analysis:
        Uses 4 complementary algorithms with weighted combination:
        - Laplacian variance (10%): Edge variance detection
        - Tenengrad/Sobel (40%): Gradient magnitude strength
        - FFT high-frequency (30%): Frequency domain analysis (resolution-independent)
        - Edge density/Canny (20%): Perceptual edge detection
        All metrics are resolution-normalized to Full HD baseline.

    Quality Score Weights:
        - 50% BRISQUE (image naturalness & artifacts)
        - 30% Sharpness (multi-metric combined)
        - 10% Noise (signal-to-noise ratio)
        - 10% Contrast (tonal range & detail)

    Args:
        image_path: Path to the image file
        brisque_model_path: Path to BRISQUE model file (optional, uses default if not provided)
        brisque_range_path: Path to BRISQUE range file (optional, uses default if not provided)

    Returns:
        Dictionary with comprehensive quality analysis or None if image cannot be loaded:
        {
            'quality_note': float (0-10),
            'brisque_score': float,
            'sharpness': float,
            'noise_level': float,
            'contrast': float,
            'image_info': {
                'width': int,
                'height': int,
                'channels': int,
                'resolution': str
            },
            'sharpness_details': {
                'laplacian_var': float,
                'laplacian_note': float (0-10),
                'tenengrad': float,
                'tenengrad_note': float (0-10),
                'fft_ratio': float,
                'fft_note': float (0-10),
                'edge_density': float,
                'edge_note': float (0-10),
                'combined_note': float (0-10)
            },
            'notes': {
                'brisque_note': float (0-10),
                'sharpness_note': float (0-10),
                'noise_note': float (0-10),
                'contrast_note': float (0-10)
            }
        }
    """
    try:
        img = cv2.imread(image_path)
        if img is None:
            return None

        # Get basic image info
        height, width = img.shape[:2]
        channels = img.shape[2] if len(img.shape) > 2 else 1
        image_info = {
            'width': width,
            'height': height,
            'channels': channels,
            'resolution': f"{width}x{height}"
        }

        # Set default paths to BRISQUE model files if not provided
        if brisque_model_path is None:
            # Use absolute path from project root (go up 5 levels from shared/src/lib/utils/ to project root)
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))))
            brisque_model_path = os.path.join(project_root, "backend_host", "src", "lib", "opencv", "brisque_model_live.yml")
        if brisque_range_path is None:
            project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))))
            brisque_range_path = os.path.join(project_root, "backend_host", "src", "lib", "opencv", "brisque_range_live.yml")

        # 1. BRISQUE (50% weight, lower score = better)
        brisque_score = 50.0  # Default if BRISQUE fails
        try:
            if os.path.exists(brisque_model_path) and os.path.exists(brisque_range_path):
                print(f"[@image_utils] BRISQUE: Loading model '{brisque_model_path}' and range '{brisque_range_path}'")
                print(f"[@image_utils] BRISQUE: Model file exists: {os.path.exists(brisque_model_path)}")
                print(f"[@image_utils] BRISQUE: Range file exists: {os.path.exists(brisque_range_path)}")
                print(f"[@image_utils] BRISQUE: Image shape: {img.shape}, dtype: {img.dtype}")

                # Try to create BRISQUE quality object first
                try:
                    brisque_obj = cv2.quality.QualityBRISQUE_create(brisque_model_path, brisque_range_path)
                    print(f"[@image_utils] BRISQUE: QualityBRISQUE object created successfully")

                    # Compute quality
                    brisque_result = brisque_obj.compute(img)
                    print(f"[@image_utils] BRISQUE: brisque_obj.compute() returned: {brisque_result}")
                    print(f"[@image_utils] BRISQUE: result type: {type(brisque_result)}")
                except Exception as obj_e:
                    print(f"[@image_utils] BRISQUE: Error with QualityBRISQUE_create: {obj_e}")
                    # Fall back to the static method
                    print(f"[@image_utils] BRISQUE: Falling back to cv2.quality.QualityBRISQUE_compute static method")
                    brisque_result = cv2.quality.QualityBRISQUE_compute(
                        img, brisque_model_path, brisque_range_path
                    )

                print(f"[@image_utils] BRISQUE: Final result: {brisque_result}")
                print(f"[@image_utils] BRISQUE: result type: {type(brisque_result)}")

                if hasattr(brisque_result, 'shape'):
                    print(f"[@image_utils] BRISQUE: result shape: {brisque_result.shape}")
                if hasattr(brisque_result, '__len__'):
                    print(f"[@image_utils] BRISQUE: result length: {len(brisque_result)}")

                # Fix: Properly extract scalar value from BRISQUE result
                if hasattr(brisque_result, '__getitem__'):
                    print(f"[@image_utils] BRISQUE: result[0]: {brisque_result[0]} (type: {type(brisque_result[0])})")
                    raw_brisque = brisque_result[0]
                    if hasattr(raw_brisque, '__getitem__') and not isinstance(raw_brisque, (int, float)):
                        print(f"[@image_utils] BRISQUE: raw_brisque[0]: {raw_brisque[0]} (type: {type(raw_brisque[0])})")
                        brisque_score = float(raw_brisque[0])
                    else:
                        print(f"[@image_utils] BRISQUE: using raw_brisque directly: {raw_brisque}")
                        brisque_score = float(raw_brisque)
                else:
                    print(f"[@image_utils] BRISQUE: using result directly: {brisque_result}")
                    brisque_score = float(brisque_result)

                print(f"[@image_utils] BRISQUE: final extracted score: {brisque_score} (type: {type(brisque_score)})")

                # BRISQUE interpretation: lower score = better quality (0-100 scale)
                # If BRISQUE returns 0.0, it might mean perfect quality OR an error
                if isinstance(brisque_result, (tuple, list)) and len(brisque_result) == 4:
                    all_same = all(abs(x - brisque_result[0]) < 1e-6 for x in brisque_result)
                    if all_same and brisque_result[0] == 0.0:
                        print(f"[@image_utils] BRISQUE: ⚠️  WARNING - All 4 values are 0.0, this might indicate:")
                        print(f"[@image_utils] BRISQUE:   1) Perfect quality image (unlikely for blurry image)")
                        print(f"[@image_utils] BRISQUE:   2) Model loading issue")
                        print(f"[@image_utils] BRISQUE:   3) Image format issue")
                        print(f"[@image_utils] BRISQUE:   4) BRISQUE algorithm limitation")

                # Debug: Print raw BRISQUE value
                print(f"[@image_utils] BRISQUE raw score: {brisque_score:.2f}")
            else:
                print(f"[@image_utils] BRISQUE model files not found")
        except Exception as e:
            print(f"[@image_utils] BRISQUE error: {e}, using default score=50")

        # BRISQUE normalization: Lower BRISQUE score = better quality (0-30=Excellent, 30-60=Good, 60-80=Fair, 80+=Poor)
        # Convert to 0-10 scale where 0 BRISQUE → 10/10, 100 BRISQUE → 0/10
        brisque_note = max(0, min(10, 10 - (brisque_score / 10)))

        # 2. Sharpness: Multi-metric approach (30% weight in overall quality)
        # Uses 4 complementary algorithms to assess image sharpness robustly
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        
        # Resolution normalization factor (normalize to Full HD 1920x1080 baseline)
        # This ensures high-resolution images aren't penalized for larger pixel counts
        pixels = width * height
        resolution_factor = np.sqrt(pixels / (1920 * 1080))
        
        # Metric 1: Laplacian variance (10% weight)
        # Measures variance of Laplacian operator (2nd derivative of intensity)
        # Good for detecting edges but sensitive to noise and uniform areas
        lap_var = cv2.Laplacian(gray, cv2.CV_64F).var()
        lap_normalized = lap_var / resolution_factor
        lap_note = min(10, lap_normalized / 100)
        
        # Metric 2: Tenengrad (Sobel-based gradient magnitude) (40% weight - PRIMARY)
        # Measures gradient strength using Sobel operators
        # More robust to uniform areas, better for natural images
        # Higher weight because it's most reliable for camera images
        sobel_x = cv2.Sobel(gray, cv2.CV_64F, 1, 0, ksize=3)
        sobel_y = cv2.Sobel(gray, cv2.CV_64F, 0, 1, ksize=3)
        tenengrad = np.mean(sobel_x**2 + sobel_y**2)
        tenengrad_normalized = tenengrad / resolution_factor
        tenengrad_note = min(10, tenengrad_normalized / 50)  # Calibrated: >500 normalized → 10/10
        
        # Metric 3: FFT high-frequency content (30% weight)
        # Analyzes frequency domain - sharp images have more high-frequency content
        # Resolution-independent and not fooled by high contrast but blurry images
        # Most scientifically robust metric
        fft = np.fft.fft2(gray)
        fft_shift = np.fft.fftshift(fft)
        magnitude = np.abs(fft_shift)
        rows, cols = gray.shape
        crow, ccol = rows // 2, cols // 2
        # Create mask for high frequencies (outer 70% radius of spectrum, excluding DC and low-freq)
        mask = np.ones((rows, cols), dtype=bool)
        r_inner = int(min(rows, cols) * 0.3)  # Inner 30% is low frequency
        y, x = np.ogrid[:rows, :cols]
        mask_inner = (x - ccol)**2 + (y - crow)**2 <= r_inner**2
        mask[mask_inner] = False
        high_freq_power = np.sum(magnitude[mask])
        total_power = np.sum(magnitude)
        fft_ratio = high_freq_power / (total_power + 1e-10)
        fft_note = min(10, fft_ratio * 100)  # Calibrated: >0.1 ratio → 10/10
        
        # Metric 4: Edge density (Canny-based perceptual sharpness) (20% weight)
        # Counts strong edges per unit area - matches human perception
        # Good for detecting overall image detail but threshold-dependent
        edges = cv2.Canny(gray, 50, 150)
        edge_density = np.sum(edges > 0) / edges.size
        edge_note = min(10, edge_density * 100)  # Calibrated: >0.1 density → 10/10
        
        # Combined sharpness score using weighted average
        # Weights chosen based on metric reliability for camera quality assessment
        sharpness_note = (
            0.1 * lap_note +       # Laplacian: baseline, kept for completeness
            0.4 * tenengrad_note + # Tenengrad: primary metric, most reliable
            0.3 * fft_note +       # FFT: scientific, resolution-independent
            0.2 * edge_note        # Edge density: perceptual validation
        )
        
        # Store all individual sharpness metrics for detailed analysis and debugging
        # Includes both raw metric values and normalized 0-10 scores
        sharpness_details = {
            'laplacian_var': round(lap_var, 2),        # Raw Laplacian variance
            'laplacian_note': round(lap_note, 1),      # Normalized 0-10 score
            'tenengrad': round(tenengrad, 2),          # Raw Tenengrad score
            'tenengrad_note': round(tenengrad_note, 1),# Normalized 0-10 score
            'fft_ratio': round(fft_ratio, 4),          # Raw FFT high-freq ratio (0-1)
            'fft_note': round(fft_note, 1),            # Normalized 0-10 score
            'edge_density': round(edge_density, 4),    # Raw edge density (0-1)
            'edge_note': round(edge_note, 1),          # Normalized 0-10 score
            'combined_note': round(sharpness_note, 1)  # Final weighted combination
        }

        # Debug: Print raw sharpness values
        print(f"[@image_utils] Sharpness Metrics (resolution factor: {resolution_factor:.2f}):")
        print(f"[@image_utils]   - Laplacian variance: {lap_var:.2f} → {lap_note:.1f}/10")
        print(f"[@image_utils]   - Tenengrad (Sobel): {tenengrad:.2f} → {tenengrad_note:.1f}/10")
        print(f"[@image_utils]   - FFT high-freq: {fft_ratio:.4f} → {fft_note:.1f}/10")
        print(f"[@image_utils]   - Edge density: {edge_density:.4f} → {edge_note:.1f}/10")
        print(f"[@image_utils]   - Combined sharpness: {sharpness_note:.1f}/10")

        # 3. Noise Level Estimation (10% weight in overall quality)
        # Uses Non-local Means Denoising to estimate noise by comparing original vs denoised
        # Lower noise = higher quality. Measures signal-to-noise ratio.
        denoised = cv2.fastNlMeansDenoisingColored(img, None, h=10)
        noise_diff = cv2.absdiff(img, denoised)
        noise_level = np.mean(noise_diff)
        noise_note = max(0, 10 - noise_level / 5)  # Calibrated: <0.5 excellent, 0.5-2.0 good, 2.0-5.0 fair, >5.0 poor

        # Debug: Print raw noise value
        print(f"[@image_utils] Noise level: {noise_level:.2f}")

        # 4. Contrast Analysis (10% weight in overall quality)
        # Measures standard deviation of lightness in LAB color space
        # Higher contrast = better tonal range and detail separation
        lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB)
        lightness_std = np.std(lab[:, :, 0])
        contrast_note = min(10, lightness_std / 12)  # Calibrated: >60 excellent, 40-60 good, 25-40 fair, <25 poor

        # Debug: Print raw contrast value
        print(f"[@image_utils] Contrast (lightness std): {lightness_std:.2f}")

        # Composite Quality Score Calculation
        # Weighted combination optimized for camera image quality assessment
        # Result is 0-10 scale where 10 is perfect quality
        # 
        # Weight rationale:
        #   50% BRISQUE - Most important: measures overall image naturalness and artifacts
        #   30% Sharpness - Critical for usability: combined multi-metric focus quality
        #   10% Noise - Minor impact: usually acceptable in modern cameras
        #   10% Contrast - Minor impact: can be adjusted in post-processing
        overall_note = (0.5 * brisque_note +
                       0.3 * sharpness_note +
                       0.1 * noise_note +
                       0.1 * contrast_note)

        # Debug: Print final calculation with breakdown
        print(f"[@image_utils] Final score: {overall_note:.1f} = 0.5×{brisque_note:.1f} + 0.3×{sharpness_note:.1f} + 0.1×{noise_note:.1f} + 0.1×{contrast_note:.1f}")

        # Return comprehensive quality analysis dictionary
        # Includes: overall score, raw metric values, normalized scores, and detailed breakdowns
        return {
            'quality_note': round(overall_note, 1),         # Final composite score (0-10)
            'brisque_score': round(brisque_score, 2),       # Raw BRISQUE value (0-100, lower=better)
            'sharpness': round(lap_var, 2),                 # Raw Laplacian variance
            'noise_level': round(noise_level, 2),           # Raw noise estimate
            'contrast': round(lightness_std, 2),            # Raw contrast (lightness std dev)
            'image_info': image_info,                       # Image dimensions and properties
            'sharpness_details': sharpness_details,         # Multi-metric sharpness breakdown
            'notes': {                                      # Normalized scores (0-10) for each metric
                'brisque_note': round(brisque_note, 1),
                'sharpness_note': round(sharpness_note, 1),
                'noise_note': round(noise_note, 1),
                'contrast_note': round(contrast_note, 1)
            }
        }

    except Exception as e:
        print(f"[@image_utils] Error computing composite quality note for {image_path}: {e}")
        return None


# =============================================================================
# Image Analysis Functions
# =============================================================================

def load_and_downscale_image(image_path: str, target_size: Tuple[int, int] = (320, 180)):
    """
    Load image and downscale for efficient analysis.
    Reusable for freeze, blackscreen, and macroblocks detection.
    
    Args:
        image_path: Path to image file
        target_size: Target size (width, height)
    
    Returns:
        Downscaled grayscale image or None if error
    """
    try:
        img = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
        if img is None:
            return None
        
        # Downscale using INTER_AREA (best for downsampling)
        img_small = cv2.resize(img, target_size, interpolation=cv2.INTER_AREA)
        return img_small
    except Exception as e:
        print(f"[@image_utils] Error loading/downscaling {image_path}: {e}")
        return None


def analyze_blackscreen(image_path: str, threshold: int = 10, downscaled_img=None) -> Tuple[bool, float]:
    """
    Detect if image is mostly black - OPTIMIZED with optional downscaled input
    
    Args:
        image_path: Path to image (used if downscaled_img not provided)
        threshold: Darkness threshold (0-255)
        downscaled_img: Pre-downscaled image to reuse (saves computation)
    
    Returns:
        Tuple of (is_blackscreen, dark_percentage)
    """
    if downscaled_img is not None:
        img = downscaled_img
    else:
        img = load_and_downscale_image(image_path)
    
    if img is None:
        return False, 0.0
    
    very_dark_pixels = np.sum(img <= threshold)
    total_pixels = img.shape[0] * img.shape[1]
    dark_percentage = (very_dark_pixels / total_pixels) * 100
    
    is_blackscreen = dark_percentage > 95
    return is_blackscreen, dark_percentage


def analyze_freeze(capture_path: str, thumbnails_dir: str, fps: int = 5) -> Tuple[bool, Optional[dict]]:
    """
    Detect if image is frozen using thumbnails (5fps for v4l2, 2fps for VNC) - SIMPLE and EFFICIENT
    
    Takes last 3 thumbnails spaced 1 second apart.
    At 5fps: current, -5, -10 (1s apart each)
    At 2fps: current, -2, -4 (1s apart each)
    
    Args:
        capture_path: Path to current capture (e.g., /path/captures/capture_000009.jpg)
        thumbnails_dir: Path to thumbnails directory
        fps: Frames per second (5 for v4l2, 2 for x11grab/VNC)
    
    Returns:
        Tuple of (is_frozen, freeze_details)
    """
    # Extract frame number from capture filename
    current_filename = os.path.basename(capture_path)
    match = re.match(r'capture_(\d+)\.jpg', current_filename)
    if not match:
        return False, None
    
    current_num_str = match.group(1)
    current_num = int(current_num_str)
    num_digits = len(current_num_str)
    
    # Need at least 2 seconds of history (2 * fps frames)
    if current_num < (2 * fps):
        return False, None
    
    # Get last 3 thumbnails spaced 1 second apart
    thumb_current_num = current_num
    thumb_prev1_num = current_num - fps        # 1 second ago
    thumb_prev2_num = current_num - (2 * fps)  # 2 seconds ago
    
    thumb_current_filename = f"capture_{thumb_current_num:0{num_digits}d}_thumbnail.jpg"
    thumb_prev1_filename = f"capture_{thumb_prev1_num:0{num_digits}d}_thumbnail.jpg"
    thumb_prev2_filename = f"capture_{thumb_prev2_num:0{num_digits}d}_thumbnail.jpg"
    
    thumb_current_path = os.path.join(thumbnails_dir, thumb_current_filename)
    thumb_prev1_path = os.path.join(thumbnails_dir, thumb_prev1_filename)
    thumb_prev2_path = os.path.join(thumbnails_dir, thumb_prev2_filename)
    
    # Check if all 3 thumbnails exist
    if not os.path.exists(thumb_current_path) or not os.path.exists(thumb_prev1_path) or not os.path.exists(thumb_prev2_path):
        return False, None
    
    # Load thumbnails (already small at 320x180, no need to downscale further!)
    thumb_current = cv2.imread(thumb_current_path, cv2.IMREAD_GRAYSCALE)
    thumb_prev1 = cv2.imread(thumb_prev1_path, cv2.IMREAD_GRAYSCALE)
    thumb_prev2 = cv2.imread(thumb_prev2_path, cv2.IMREAD_GRAYSCALE)
    
    if thumb_current is None or thumb_prev1 is None or thumb_prev2 is None:
        return False, None
    
    # Calculate differences between all 3 thumbnails (1 second apart each)
    diff_1vs2 = cv2.absdiff(thumb_prev2, thumb_prev1)
    diff_1vs3 = cv2.absdiff(thumb_prev2, thumb_current)
    diff_2vs3 = cv2.absdiff(thumb_prev1, thumb_current)
    
    mean_diff_1vs2 = np.mean(diff_1vs2)
    mean_diff_1vs3 = np.mean(diff_1vs3)
    mean_diff_2vs3 = np.mean(diff_2vs3)
    
    # Frozen if ALL comparisons show small differences over 2 seconds
    freeze_threshold = 0.5
    is_frozen = (mean_diff_1vs2 < freeze_threshold and 
                mean_diff_1vs3 < freeze_threshold and 
                mean_diff_2vs3 < freeze_threshold)
    
    freeze_details = {
        'frames_compared': [thumb_prev2_filename, thumb_prev1_filename, thumb_current_filename],
        'frame_differences': [round(mean_diff_1vs2, 2), round(mean_diff_1vs3, 2), round(mean_diff_2vs3, 2)],
        'threshold': freeze_threshold,
        'time_spacing': f'{fps} frames = 1 second'
    }
    
    return is_frozen, freeze_details


def analyze_macroblocks(image_path: str) -> Tuple[bool, float]:
    """
    Conservative macroblock/image quality detection using strict thresholds.
    Detects: green/pink pixels, severe blur, compression artifacts.
    Only flags true macroblocks to avoid false positives.
    
    Args:
        image_path: Path to image file
    
    Returns:
        Tuple of (macroblocks_detected, quality_score)
        quality_score: 0-5 scale (5 = excellent, 0 = terrible)
    """
    try:
        img = cv2.imread(image_path)
        if img is None:
            return False, 5.0  # No image = assume good quality
        
        # Convert to different color spaces for analysis
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        
        # Sample every 10th pixel for performance
        sample_rate = 10
        hsv_sampled = hsv[::sample_rate, ::sample_rate]
        
        # Green artifacts: High saturation in green range
        green_mask = cv2.inRange(hsv_sampled, (40, 100, 50), (80, 255, 255))
        green_pixels = np.sum(green_mask > 0)
        
        # Pink/Magenta artifacts: High saturation in magenta range  
        pink_mask = cv2.inRange(hsv_sampled, (140, 100, 50), (170, 255, 255))
        pink_pixels = np.sum(pink_mask > 0)
        
        total_sampled = hsv_sampled.shape[0] * hsv_sampled.shape[1]
        artifact_percentage = ((green_pixels + pink_pixels) / total_sampled) * 100
        
        # Conservative blur detection using Laplacian variance
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        gray_sampled = gray[::sample_rate, ::sample_rate]
        laplacian_var = cv2.Laplacian(gray_sampled, cv2.CV_64F).var()
        
        # CONSERVATIVE THRESHOLDS - Only flag obvious macroblocks
        has_severe_artifacts = artifact_percentage > 8.0
        is_severely_blurry = laplacian_var < 30
        
        # Both conditions should be somewhat present for true macroblocks
        if has_severe_artifacts and is_severely_blurry:
            macroblocks_detected = True
        elif has_severe_artifacts and artifact_percentage > 15.0:
            macroblocks_detected = True
        elif is_severely_blurry and laplacian_var < 15:
            macroblocks_detected = True
        else:
            macroblocks_detected = False
        
        # Calculate quality score on 0-5 scale (5 = best, 0 = worst)
        if not macroblocks_detected:
            # No issues detected - excellent quality
            quality_score = 5.0
        else:
            # Calculate badness score (higher = worse quality)
            badness_from_artifacts = artifact_percentage  # 0-100 range
            badness_from_blur = max(0, (200 - laplacian_var) / 2)  # 0-100 range
            badness_score = max(badness_from_artifacts, badness_from_blur)
            
            # Convert badness (0-100) to quality score (5-0)
            # Badness 0-10 → Quality 5-4 (excellent-good)
            # Badness 10-25 → Quality 4-3 (good-fair)
            # Badness 25-50 → Quality 3-2 (fair-poor)
            # Badness 50-75 → Quality 2-1 (poor-bad)
            # Badness 75-100+ → Quality 1-0 (bad-terrible)
            if badness_score < 10:
                quality_score = 5.0 - (badness_score / 10)  # 5.0 to 4.0
            elif badness_score < 25:
                quality_score = 4.0 - ((badness_score - 10) / 15)  # 4.0 to 3.0
            elif badness_score < 50:
                quality_score = 3.0 - ((badness_score - 25) / 25)  # 3.0 to 2.0
            elif badness_score < 75:
                quality_score = 2.0 - ((badness_score - 50) / 25)  # 2.0 to 1.0
            else:
                quality_score = max(0.0, 1.0 - ((badness_score - 75) / 25))  # 1.0 to 0.0
        
        return macroblocks_detected, quality_score
        
    except Exception as e:
        print(f"[@image_utils] Error in macroblocks detection: {e}")
        return False, 5.0  # Error = assume good quality


# =============================================================================
# Subtitle/OCR Analysis Functions
# =============================================================================

def analyze_subtitle_region(img: np.ndarray, extract_text: bool = True) -> Dict[str, Any]:
    """
    Analyze subtitle region for text content.
    
    Args:
        img: OpenCV image (BGR format) - any resolution
        extract_text: Whether to extract text using OCR
        
    Returns:
        Dictionary with subtitle analysis results
    """
    try:
        height, width = img.shape[:2]
        
        subtitle_height_start = int(height * 0.62)
        subtitle_width_start = int(width * 0.20)
        subtitle_width_end = int(width * 0.80)
        
        subtitle_region = img[subtitle_height_start:, subtitle_width_start:subtitle_width_end]
        gray_subtitle = cv2.cvtColor(subtitle_region, cv2.COLOR_BGR2GRAY)
        
        adaptive_thresh = cv2.adaptiveThreshold(
            gray_subtitle, 255, 
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C, 
            cv2.THRESH_BINARY, 11, 2
        )
        edges = cv2.Canny(adaptive_thresh, 50, 150)
        subtitle_edges = np.sum(edges > 0)
        
        region_pixels = subtitle_region.shape[0] * subtitle_region.shape[1]
        adaptive_threshold = max(200, region_pixels * 0.002)
        has_subtitles = bool(subtitle_edges > adaptive_threshold)
        
        extracted_text = ""
        detected_language = "unknown"
        
        if extract_text and has_subtitles and OCR_AVAILABLE:
            extracted_text = extract_text_from_region(subtitle_region)
            if extracted_text:
                detected_language = detect_language(extracted_text)
            else:
                has_subtitles = False
        elif extract_text and has_subtitles and not OCR_AVAILABLE:
            has_subtitles = False
        
        confidence = 0.9 if (has_subtitles and extracted_text) else (0.7 if has_subtitles else 0.1)
        
        return {
            'has_subtitles': has_subtitles,
            'subtitle_edges': int(subtitle_edges),
            'subtitle_threshold': float(adaptive_threshold),
            'extracted_text': extracted_text,
            'detected_language': detected_language,
            'confidence': confidence,
            'ocr_available': OCR_AVAILABLE
        }
        
    except Exception as e:
        return {
            'has_subtitles': False,
            'error': str(e),
            'confidence': 0.0
        }


def extract_text_from_region(region_image: np.ndarray) -> str:
    """Extract text from image region using OCR."""
    if not OCR_AVAILABLE:
        raise ImportError("pytesseract is not installed - cannot perform OCR. Install with: pip install pytesseract")
    
    if len(region_image.shape) == 3:
        gray_region = cv2.cvtColor(region_image, cv2.COLOR_BGR2GRAY)
    else:
        gray_region = region_image
    
    enhanced = cv2.convertScaleAbs(gray_region, alpha=2.0, beta=0)
    _, thresh = cv2.threshold(enhanced, 127, 255, cv2.THRESH_BINARY)
    
    text = pytesseract.image_to_string(thresh, config='--psm 6').strip()
    
    if len(text) < 3:
        return ''
    
    cleaned_text = clean_ocr_text(text)
    return cleaned_text if len(cleaned_text) >= 3 else text


def clean_ocr_text(text: str) -> str:
    """Clean OCR text by removing noise."""
    if not text:
        return ''
    
    text = re.sub(r'\s+', ' ', text.replace('\n', ' ')).strip()
    
    words = []
    for word in text.split():
        cleaned_word = re.sub(r'[^\w\s\'-]', '', word).strip()
        if (len(cleaned_word) >= 2 and 
            re.search(r'[a-zA-ZÀ-ÿ]', cleaned_word) and 
            not cleaned_word.isdigit()):
            words.append(cleaned_word)
    
    return ' '.join(words)


def detect_language(text: str) -> str:
    """Detect language from text."""
    if not LANG_DETECT_AVAILABLE or not text:
        return 'unknown'
    
    try:
        cleaned_text = clean_ocr_text(text)
        detection_text = cleaned_text if len(cleaned_text) >= 3 else text
        
        if len(detection_text) < 3:
            return 'unknown'
        
        return detect(detection_text)
        
    except (LangDetectException, Exception):
        return 'unknown'

