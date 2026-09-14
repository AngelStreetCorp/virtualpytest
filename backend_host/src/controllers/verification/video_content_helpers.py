"""
Video Content Detection Helpers

Specialized content detection functionality for the VideoVerificationController:
1. Blackscreen detection
2. Freeze detection  
3. Subtitle detection with OCR
4. Text extraction and language detection
5. Error content detection

This helper handles content-specific analysis that requires domain knowledge
about video artifacts, subtitles, and visual content patterns.
"""

import os
import time
import subprocess
import cv2
import numpy as np
import re
from datetime import datetime
from backend_host.src.lib.utils.system_info_utils import get_files_by_pattern
from typing import Dict, Any, Optional, Tuple, List
from shared.src.lib.utils.image_utils import (
    analyze_subtitle_region as shared_analyze_subtitle_region,
    extract_text_from_region,
    clean_ocr_text,
    detect_language
)

# Simplified sampling patterns for performance optimization
SAMPLING_PATTERNS = {
    "freeze_sample_rate": 10,     # Every 10th pixel for freeze detection
    "blackscreen_samples": 1000,  # 1000 random pixels for blackscreen
    "error_grid_rate": 15,        # Every 15th pixel in grid for errors
    "subtitle_edge_threshold": 200  # Edge detection threshold
}


class VideoContentHelpers:
    """Content detection and analysis for video verification."""
    
    def __init__(self, av_controller, device_name: str = "VideoContent"):
        """
        Initialize video content helpers.
        
        Args:
            av_controller: AV controller for capturing video/images
            device_name: Name for logging purposes
        """
        self.av_controller = av_controller
        self.device_name = device_name
        
        # Initialize AI helpers for channel analysis
        from .video_ai_helpers import VideoAIHelpers
        self.ai_helpers = VideoAIHelpers(av_controller, device_name)
    
    # =============================================================================
    # Optimized Edge-Based Detection Workflow
    # =============================================================================
    
    def detect_zap_with_edge_analysis(self, image_path: str, threshold: int = 10) -> Dict[str, Any]:
        """
        Optimized zap detection using edge-based analysis.
        
        Workflow:
        1. Edge detection (core - reused)
        2. Blackscreen check (5-70% region, skip header & banner)
        3. Bottom content check (only if blackscreen - for zap confirmation)
        
        Returns zap=True only if: blackscreen + bottom_content
        
        Args:
            image_path: Path to image file
            threshold: Pixel intensity threshold for blackscreen (default: 10)
            
        Returns:
            Dictionary with zap analysis results
        """
        try:
            img = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
            if img is None:
                return {'success': False, 'error': 'Failed to load image'}
            
            img_height, img_width = img.shape
            timings = {}
            total_start = time.perf_counter()
            
            # === STEP 1: Edge Detection (CORE - runs always) ===
            start = time.perf_counter()
            edges = cv2.Canny(img, 50, 150)
            timings['edge_detection'] = (time.perf_counter() - start) * 1000
            
            # Define regions
            header_y = int(img_height * 0.05)  # Skip top 5% (TV time/header)
            split_y = int(img_height * 0.7)     # Blackscreen region: 5-70%
            
            # === STEP 2: Blackscreen Detection (fast sampling) ===
            start = time.perf_counter()
            # Analyze 5% to 70% (skip header, skip bottom banner)
            top_region = img[header_y:split_y, :]
            
            # Sample every 3rd pixel (11% sample)
            sample = top_region[::3, ::3]
            sample_dark = np.sum(sample <= threshold)
            sample_total = sample.shape[0] * sample.shape[1]
            dark_percentage = (sample_dark / sample_total) * 100
            
            # Full scan only if edge case (70-90%)
            if 70 <= dark_percentage <= 90:
                total_pixels = top_region.shape[0] * top_region.shape[1]
                dark_pixels = np.sum(top_region <= threshold)
                dark_percentage = (dark_pixels / total_pixels) * 100
            
            blackscreen = dark_percentage > 85
            timings['blackscreen'] = (time.perf_counter() - start) * 1000
            
            # === STEP 3: Bottom Content Check (ONLY if blackscreen) ===
            start = time.perf_counter()
            if blackscreen:
                # Check bottom 30% for banner/channel info (zap confirmation)
                edges_bottom = edges[split_y:img_height, :]
                bottom_edge_density = np.sum(edges_bottom > 0) / edges_bottom.size * 100
                has_bottom_content = 3 < bottom_edge_density < 20
                timings['bottom_content'] = (time.perf_counter() - start) * 1000
            else:
                # No blackscreen = no need to check for zapping
                has_bottom_content = False
                bottom_edge_density = 0.0
                timings['bottom_content'] = 0.0  # Skipped
            
            # Zap decision: blackscreen + bottom content
            zap = blackscreen and has_bottom_content
            
            timings['total'] = (time.perf_counter() - total_start) * 1000
            
            return {
                'success': True,
                'zap': zap,
                'blackscreen': blackscreen,
                'blackscreen_percentage': round(dark_percentage, 1),
                'blackscreen_threshold': threshold,
                'blackscreen_region': '5-70%',
                'has_bottom_content': has_bottom_content,
                'bottom_edge_density': round(bottom_edge_density, 1),
                'edges': edges,  # For reuse in subtitle detection
                'timings': {k: round(v, 2) for k, v in timings.items()}
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': f'Zap detection error: {str(e)}'
            }
    
    def detect_subtitle_box_with_edges(self, image_path: str, edges: np.ndarray = None, skip_if_zap: bool = False) -> Dict[str, Any]:
        """
        Detect subtitle box location using edge analysis.
        
        Optimizations:
        - Reuses edge detection from zap analysis
        - Skips if zap detected (mutually exclusive)
        - Returns box coordinates for OCR
        
        Args:
            image_path: Path to image file
            edges: Pre-computed edge detection (optional - reuse from zap)
            skip_if_zap: Skip subtitle detection if zap detected
            
        Returns:
            Dictionary with subtitle box detection results
        """
        try:
            if skip_if_zap:
                return {
                    'success': True,
                    'has_subtitle_area': False,
                    'subtitle_edge_density': 0.0,
                    'box': None,
                    'skipped': True,
                    'skip_reason': 'zap',
                    'timing_ms': 0.0
                }
            
            start = time.perf_counter()
            
            # Load image if edges not provided
            if edges is None:
                img = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
                if img is None:
                    return {'success': False, 'error': 'Failed to load image'}
                edges = cv2.Canny(img, 50, 150)
            else:
                img = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
                if img is None:
                    return {'success': False, 'error': 'Failed to load image'}
            
            img_height, img_width = img.shape
            
            # Check subtitle area (bottom 15%)
            subtitle_y = int(img_height * 0.85)
            edges_subtitle = edges[subtitle_y:img_height, :]
            
            subtitle_edge_density = np.sum(edges_subtitle > 0) / edges_subtitle.size * 100
            has_subtitle_area = 2 < subtitle_edge_density < 25
            
            subtitle_box = None
            if has_subtitle_area:
                # Find specific subtitle box (bottom 40% of image)
                search_y_start = int(img_height * 0.6)
                edges_search_region = edges[search_y_start:img_height, :]
                
                # Find contours (connected edge regions)
                contours, _ = cv2.findContours(edges_search_region, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
                
                # Filter for subtitle-like boxes
                subtitle_boxes = []
                for contour in contours:
                    x, y, w, h = cv2.boundingRect(contour)
                    
                    # Filter criteria for subtitle boxes:
                    # - Width > 30% of image width (subtitles span screen)
                    # - Height between 20-150 pixels (text size range)
                    # - Aspect ratio > 3 (horizontal rectangle)
                    if w > img_width * 0.3 and 20 < h < 150 and w / h > 3:
                        # Adjust y coordinate to full image space
                        subtitle_boxes.append({
                            'x': x,
                            'y': search_y_start + y,
                            'width': w,
                            'height': h
                        })
                
                if subtitle_boxes:
                    # Take ONLY the lowest box (highest Y coordinate = bottom-most)
                    subtitle_boxes.sort(key=lambda box: box['y'], reverse=True)
                    subtitle_box = subtitle_boxes[0]
            
            timing_ms = (time.perf_counter() - start) * 1000
            
            return {
                'success': True,
                'has_subtitle_area': has_subtitle_area,
                'subtitle_edge_density': round(subtitle_edge_density, 1),
                'box': subtitle_box,
                'skipped': False,
                'skip_reason': None,
                'timing_ms': round(timing_ms, 2)
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': f'Subtitle box detection error: {str(e)}'
            }
    
    def extract_text_from_subtitle_box(self, image_path: str, box: Dict[str, int]) -> Dict[str, Any]:
        """
        Extract text from subtitle box using optimized OCR.
        
        Optimizations:
        - Downscales to 80px height for speed
        - Uses --psm 6 (multi-line text)
        - Detects language and confidence
        
        Args:
            image_path: Path to image file
            box: Subtitle box coordinates {x, y, width, height}
            
        Returns:
            Dictionary with OCR results
        """
        try:
            start = time.perf_counter()
            
            img = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
            if img is None:
                return {'success': False, 'error': 'Failed to load image'}
            
            img_height, img_width = img.shape
            
            # Extract subtitle box with padding
            padding = 5
            x1 = max(0, box['x'] - padding)
            y1 = max(0, box['y'] - padding)
            x2 = min(img_width, box['x'] + box['width'] + padding)
            y2 = min(img_height, box['y'] + box['height'] + padding)
            
            subtitle_box_region = img[y1:y2, x1:x2]
            
            # OPTIMIZATION 1: Downscale to target height for faster OCR
            # Target height: 80 pixels (good for OCR, faster processing)
            box_h, box_w = subtitle_box_region.shape
            if box_h > 80:
                scale = 80 / box_h
                new_w = int(box_w * scale)
                subtitle_box_region = cv2.resize(subtitle_box_region, (new_w, 80), interpolation=cv2.INTER_AREA)
            
            # OPTIMIZATION 2: Fast OCR - multi-line mode
            # Use --psm 6 (uniform block of text) for subtitles
            try:
                import pytesseract
                # Enhance contrast for better OCR
                enhanced = cv2.convertScaleAbs(subtitle_box_region, alpha=2.0, beta=0)
                _, thresh = cv2.threshold(enhanced, 127, 255, cv2.THRESH_BINARY)
                
                # Multi-line OCR (--psm 6 = uniform block of text)
                subtitle_text = pytesseract.image_to_string(thresh, config='--psm 6 --oem 3').strip()
            except:
                # Fallback to standard method
                subtitle_text = extract_text_from_region(subtitle_box_region)
            
            timing_ms = (time.perf_counter() - start) * 1000
            
            # Detect language if text found
            detected_language = None
            confidence = 0.0
            
            if subtitle_text and len(subtitle_text.strip()) > 0:
                try:
                    detected_language = detect_language(subtitle_text)
                    
                    # If language detected successfully, trust the OCR (confidence = 1.0)
                    if detected_language and detected_language != 'unknown':
                        confidence = 1.0
                    else:
                        # Language unknown but text extracted - medium confidence
                        confidence = 0.75
                except:
                    detected_language = 'unknown'
                    confidence = 0.75
            
            return {
                'success': True,
                'extracted_text': subtitle_text if subtitle_text else '',
                'detected_language': detected_language,
                'confidence': confidence,
                'ocr_method': 'edge_based_box_detection',
                'downscaled_to_height': 80 if box_h > 80 else box_h,
                'psm_mode': 6,
                'timing_ms': round(timing_ms, 2)
            }
            
        except Exception as e:
            return {
                'success': False,
                'error': f'OCR extraction error: {str(e)}'
            }
    
    # =============================================================================
    # Blackscreen Detection
    # =============================================================================
    
    def detect_blackscreen_in_image(self, image_path: str, threshold: int = 10) -> Dict[str, Any]:
        """
        Detect if image is mostly black (blackscreen) - Simple and reliable.
        
        Args:
            image_path: Path to image file
            threshold: Pixel intensity threshold (0-255)
            
        Returns:
            Dictionary with blackscreen analysis results
        """
        try:
            if not os.path.exists(image_path):
                return {
                    'success': False,
                    'error': 'Image file not found',
                    'image_path': image_path
                }
            
            img = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
            if img is None:
                return {
                    'success': False,
                    'error': 'Could not load image',
                    'image_path': image_path
                }
            
            # Simple approach: count how many pixels are very dark (0-threshold)
            very_dark_pixels = np.sum(img <= threshold)
            total_pixels = img.shape[0] * img.shape[1]
            dark_percentage = (very_dark_pixels / total_pixels) * 100
            
            # If more than 80% of pixels are very dark, it's a blackscreen
            is_blackscreen = bool(dark_percentage > 80)
            
            result = {
                'success': True,
                'is_blackscreen': is_blackscreen,
                'dark_percentage': round(float(dark_percentage), 2),
                'threshold': threshold,
                'very_dark_pixels': int(very_dark_pixels),
                'total_pixels': int(total_pixels),
                'image_size': f"{img.shape[1]}x{img.shape[0]}",
                'confidence': 0.9 if is_blackscreen else 0.1,
                'image_path': os.path.basename(image_path)
            }
            
            print(f"VideoContent[{self.device_name}]: Blackscreen analysis - {dark_percentage:.1f}% dark pixels, blackscreen={is_blackscreen}")
            return result
            
        except Exception as e:
            print(f"VideoContent[{self.device_name}]: Blackscreen detection error: {e}")
            return {
                'success': False,
                'error': f'Analysis error: {str(e)}',
                'image_path': image_path
            }

    def detect_blackscreen_batch(self, image_paths: List[str], threshold: int = 10) -> Dict[str, Any]:
        """
        Detect blackscreen in multiple images.
        
        Args:
            image_paths: List of image paths to analyze
            threshold: Pixel intensity threshold (0-255)
            
        Returns:
            Dictionary with overall blackscreen analysis results
        """
        results = []
        
        for image_path in image_paths:
            result = self.detect_blackscreen_in_image(image_path, threshold)
            results.append(result)
        
        # Calculate overall result
        successful_analyses = [r for r in results if r.get('success')]
        blackscreen_detected = any(r.get('is_blackscreen', False) for r in successful_analyses)
        
        overall_result = {
            'success': len(successful_analyses) > 0,
            'blackscreen_detected': blackscreen_detected,
            'analyzed_images': len(results),
            'successful_analyses': len(successful_analyses),
            'results': results,
            'analysis_type': 'blackscreen_detection',
            'timestamp': datetime.now().isoformat()
        }
        
        return overall_result

    # =============================================================================
    # Freeze Detection
    # =============================================================================
    
    def detect_freeze_in_images(self, image_paths: List[str], freeze_threshold: float = 0.2) -> Dict[str, Any]:
        """
        Detect if images are frozen (identical frames) with early stopping for zapping detection.
        
        Args:
            image_paths: List of image paths to analyze
            freeze_threshold: Threshold for frame difference detection (0.2 = nearly identical frames)
            
        Returns:
            Dictionary with freeze analysis results
        """
        try:
            if len(image_paths) < 2:
                return {
                    'success': False,
                    'error': 'Need at least 2 images for freeze detection',
                    'freeze_detected': False
                }
            
            # Enhanced freeze detection with early stopping (similar to blackscreen detection)
            comparisons = []
            freeze_detected = False
            freeze_ended = False
            MAX_ANALYSIS_IMAGES = min(50, len(image_paths))  # Dynamic safety cap based on available images
            
            # Process images with early stopping logic
            for i in range(len(image_paths) - 1):
                # Safety cap on analysis
                if i >= MAX_ANALYSIS_IMAGES - 1:
                    print(f"VideoContent[{self.device_name}]: Reached {MAX_ANALYSIS_IMAGES}-image analysis cap - stopping")
                    break
                
                # Load current and next image
                img1_path = image_paths[i]
                img2_path = image_paths[i + 1]
                
                if not os.path.exists(img1_path) or not os.path.exists(img2_path):
                    return {
                        'success': False,
                        'error': f'Image file not found: {img1_path} or {img2_path}',
                        'freeze_detected': False
                    }
                
                img1 = cv2.imread(img1_path, cv2.IMREAD_GRAYSCALE)
                img2 = cv2.imread(img2_path, cv2.IMREAD_GRAYSCALE)
                
                if img1 is None or img2 is None:
                    return {
                        'success': False,
                        'error': f'Could not load images: {img1_path}, {img2_path}',
                        'freeze_detected': False
                    }
                
                # Check if images have same dimensions
                if img1.shape != img2.shape:
                    return {
                        'success': False,
                        'error': f'Image dimensions don\'t match: {img1.shape} vs {img2.shape}',
                        'freeze_detected': False
                    }
                
                # Optimized sampling for pixel difference (every 10th pixel for performance)
                sample_rate = SAMPLING_PATTERNS["freeze_sample_rate"]
                img1_sampled = img1[::sample_rate, ::sample_rate]
                img2_sampled = img2[::sample_rate, ::sample_rate]
                
                # Calculate difference
                diff = cv2.absdiff(img1_sampled, img2_sampled)
                mean_diff = np.mean(diff)
                is_frozen = bool(mean_diff < freeze_threshold)
                
                comparison = {
                    'frame1': os.path.basename(img1_path),
                    'frame2': os.path.basename(img2_path),
                    'mean_difference': round(float(mean_diff), 2),
                    'is_frozen': is_frozen,
                    'threshold': freeze_threshold
                }
                
                comparisons.append(comparison)
                
                # Early stopping logic (similar to blackscreen detection)
                if is_frozen and not freeze_detected:
                    freeze_detected = True
                    print(f"VideoContent[{self.device_name}]: ⚡ Freeze START at comparison {i+1} ({comparison['frame1']} vs {comparison['frame2']}: diff={mean_diff:.2f}) - continuing to find END...")
                
                elif freeze_detected and not is_frozen:
                    freeze_ended = True
                    print(f"VideoContent[{self.device_name}]: ✅ Freeze END at comparison {i+1} ({comparison['frame1']} vs {comparison['frame2']}: diff={mean_diff:.2f}) - STOPPING EARLY!")
                    break  # Early stopping - complete freeze sequence found!
                else:
                    # Only log non-transition frames in compact format
                    print(f"VideoContent[{self.device_name}]: {comparison['frame1']} vs {comparison['frame2']}: diff={mean_diff:.2f}, frozen={is_frozen}")
            
            # Calculate freeze statistics
            frozen_count = sum(1 for comp in comparisons if comp['is_frozen'])
            
            # Find freeze sequences - look for consecutive frozen frames
            max_consecutive_frozen = 0
            current_consecutive = 0
            
            for comp in comparisons:
                if comp['is_frozen']:
                    current_consecutive += 1
                    max_consecutive_frozen = max(max_consecutive_frozen, current_consecutive)
                else:
                    current_consecutive = 0
            
            # Detect freeze if we have at least 1 frozen frame comparison (2 identical images = freeze)
            freeze_sequence_detected = max_consecutive_frozen >= 1
            freeze_detected_final = freeze_sequence_detected
            
            print(f"VideoContent[{self.device_name}]: Freeze analysis - {frozen_count}/{len(comparisons)} frozen comparisons, max consecutive: {max_consecutive_frozen}, sequence detected: {freeze_sequence_detected}, early_stopped={freeze_ended}")
            
            overall_result = {
                'success': True,
                'freeze_detected': freeze_detected_final,
                'freeze_sequence_detected': freeze_sequence_detected,
                'max_consecutive_frozen': max_consecutive_frozen,
                'analyzed_images': len(comparisons) + 1,  # +1 because comparisons = images - 1
                'frame_comparisons': len(comparisons),
                'frozen_comparisons': frozen_count,
                'freeze_threshold': freeze_threshold,
                'comparisons': comparisons,
                'confidence': 0.9 if freeze_detected_final else 0.1,
                'analysis_type': 'freeze_detection',
                'timestamp': datetime.now().isoformat(),
                'early_stopped': freeze_ended
            }
            
            return overall_result
            
        except Exception as e:
            print(f"VideoContent[{self.device_name}]: Freeze detection error: {e}")
            return {
                'success': False,
                'error': f'Freeze detection failed: {str(e)}',
                'analysis_type': 'freeze_detection',
                'freeze_detected': False
            }

    # =============================================================================
    # Subtitle Detection with OCR
    # =============================================================================
    
    def analyze_subtitle_region(self, img, extract_text: bool = True) -> Dict[str, Any]:
        """Analyze subtitle region - uses shared utility with error detection."""
        result = shared_analyze_subtitle_region(img, extract_text)
        
        try:
            height, width = img.shape[:2]
            hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
            
            grid_rate = SAMPLING_PATTERNS["error_grid_rate"]
            sampled_hsv = hsv[::grid_rate, ::grid_rate]
            
            lower_red1 = np.array([0, 100, 100])
            upper_red1 = np.array([10, 255, 255])
            lower_red2 = np.array([170, 100, 100])
            upper_red2 = np.array([180, 255, 255])
            
            mask1 = cv2.inRange(sampled_hsv, lower_red1, upper_red1)
            mask2 = cv2.inRange(sampled_hsv, lower_red2, upper_red2)
            red_mask = mask1 + mask2
            
            red_pixels = np.sum(red_mask > 0)
            total_sampled_pixels = sampled_hsv.shape[0] * sampled_hsv.shape[1]
            red_percentage = float((red_pixels / total_sampled_pixels) * 100)
            
            result['has_errors'] = bool(red_percentage > 8.0)
            result['red_percentage'] = round(red_percentage, 2)
            result['error_threshold'] = 8.0
            result['image_size'] = f"{width}x{height}"
            
        except Exception as e:
            result['has_errors'] = False
            result['error'] = str(e)
        
        return result

    def detect_subtitles_batch(self, image_paths: List[str], extract_text: bool = True) -> Dict[str, Any]:
        """
        Detect subtitles and error messages in multiple images.
        Tests max 3 images with +1s intervals, breaks early if subtitles found.
        
        Args:
            image_paths: List of image paths to analyze
            extract_text: Whether to extract text using OCR
            
        Returns:
            Dictionary with subtitle analysis results
        """
        results = []
        max_attempts = min(3, len(image_paths))  # Test max 3 images
        
        for i, image_path in enumerate(image_paths[:max_attempts]):
            if not os.path.exists(image_path):
                results.append({
                    'image_path': image_path,
                    'success': False,
                    'error': 'Image file not found'
                })
                continue
            
            try:
                img = cv2.imread(image_path)
                if img is None:
                    results.append({
                        'image_path': image_path,
                        'success': False,
                        'error': 'Could not load image'
                    })
                    continue
                
                # Analyze subtitle region
                analysis = self.analyze_subtitle_region(img, extract_text)
                analysis['image_path'] = os.path.basename(image_path)
                analysis['success'] = True
                
                results.append(analysis)
                
                text_preview = analysis.get('extracted_text', '')[:50]
                if len(analysis.get('extracted_text', '')) > 50:
                    text_preview += "..."
                print(f"VideoContent[{self.device_name}]: Subtitle analysis - edges={analysis.get('subtitle_edges', 0)}, subtitles={analysis.get('has_subtitles', False)}, errors={analysis.get('has_errors', False)}, text='{text_preview}', confidence={analysis.get('confidence', 0)}")
                
                # Early break if subtitles found
                if analysis.get('has_subtitles', False) and analysis.get('extracted_text', '').strip():
                    print(f"VideoContent[{self.device_name}]: ✅ Subtitles found in image {i+1}/{max_attempts} - breaking early!")
                    break
                
            except Exception as e:
                results.append({
                    'image_path': image_path,
                    'success': False,
                    'error': f'Analysis error: {str(e)}'
                })
        
        # Calculate overall result
        successful_analyses = [r for r in results if r.get('success')]
        subtitles_detected = any(r.get('has_subtitles', False) for r in successful_analyses)
        errors_detected = any(r.get('has_errors', False) for r in successful_analyses)
        
        # Combine all extracted text and find the most confident language detection
        all_extracted_text = " ".join([r.get('extracted_text', '') for r in successful_analyses if r.get('extracted_text')])
        
        # Get the language from the result with highest confidence and subtitles detected
        detected_language = 'unknown'
        for result in successful_analyses:
            if result.get('has_subtitles') and result.get('detected_language') != 'unknown':
                detected_language = result.get('detected_language')
                break
        
        overall_result = {
            'success': len(successful_analyses) > 0,
            'subtitles_detected': subtitles_detected,
            'errors_detected': errors_detected,
            'analyzed_images': len(results),
            'successful_analyses': len(successful_analyses),
            'combined_extracted_text': all_extracted_text.strip(),
            'detected_language': detected_language,
            'results': results,
            'analysis_type': 'subtitle_detection',
            'timestamp': datetime.now().isoformat()
        }
        
        return overall_result

    def detect_subtitles_all_frames(self, image_paths: List[str], extract_text: bool = True) -> Dict[str, Any]:
        """
        Detect subtitles in ALL frames for restart video analysis.
        Unlike detect_subtitles_batch, this processes every frame without early termination.
        
        Args:
            image_paths: List of image paths to analyze
            extract_text: Whether to extract text using OCR
            
        Returns:
            Dictionary with subtitle analysis results for all frames
        """
        results = []
        
        print(f"VideoContent[{self.device_name}]: Analyzing subtitles in ALL {len(image_paths)} frames")
        
        for i, image_path in enumerate(image_paths):
            if not os.path.exists(image_path):
                results.append({
                    'image_path': image_path,
                    'success': False,
                    'error': 'Image file not found',
                    'frame_index': i
                })
                continue
            
            try:
                img = cv2.imread(image_path)
                if img is None:
                    results.append({
                        'image_path': image_path,
                        'success': False,
                        'error': 'Could not load image',
                        'frame_index': i
                    })
                    continue
                
                # Analyze subtitle region
                analysis = self.analyze_subtitle_region(img, extract_text)
                analysis['image_path'] = os.path.basename(image_path)
                analysis['success'] = True
                analysis['frame_index'] = i
                
                results.append(analysis)
                
                text_preview = analysis.get('extracted_text', '')[:50]
                if len(analysis.get('extracted_text', '')) > 50:
                    text_preview += "..."
                print(f"VideoContent[{self.device_name}]: Frame {i+1}/{len(image_paths)} - edges={analysis.get('subtitle_edges', 0)}, subtitles={analysis.get('has_subtitles', False)}, errors={analysis.get('has_errors', False)}, text='{text_preview}', confidence={analysis.get('confidence', 0)}")
                
                # NO EARLY BREAK - process all frames
                
            except Exception as e:
                results.append({
                    'image_path': image_path,
                    'success': False,
                    'error': f'Analysis error: {str(e)}',
                    'frame_index': i
                })
        
        # Calculate overall result
        successful_analyses = [r for r in results if r.get('success')]
        subtitles_detected = any(r.get('has_subtitles', False) for r in successful_analyses)
        errors_detected = any(r.get('has_errors', False) for r in successful_analyses)
        
        # Combine all extracted text and find the most confident language detection
        all_extracted_text = " ".join([r.get('extracted_text', '') for r in successful_analyses if r.get('extracted_text')])
        
        # Get the language from the result with highest confidence and subtitles detected
        detected_language = 'unknown'
        max_confidence = 0.0
        for result in successful_analyses:
            if result.get('has_subtitles') and result.get('confidence', 0) > max_confidence:
                detected_language = result.get('detected_language', 'unknown')
                max_confidence = result.get('confidence', 0)
        
        overall_result = {
            'success': len(successful_analyses) > 0,
            'subtitles_detected': subtitles_detected,
            'errors_detected': errors_detected,
            'analyzed_images': len(results),
            'successful_analyses': len(successful_analyses),
            'combined_extracted_text': all_extracted_text.strip(),
            'detected_language': detected_language,
            'confidence': max_confidence,
            'results': results,
            'analysis_type': 'subtitle_detection_all_frames',
            'timestamp': datetime.now().isoformat()
        }
        
        print(f"VideoContent[{self.device_name}]: All-frame subtitle analysis complete - {len(successful_analyses)}/{len(image_paths)} frames analyzed, subtitles_detected={subtitles_detected}")
        
        return overall_result

    # =============================================================================
    # Text Extraction and Language Detection - Using Shared Utilities
    # =============================================================================
    
    def extract_text_from_region(self, region_image) -> str:
        """Extract text - uses shared utility"""
        return extract_text_from_region(region_image)

    def clean_ocr_text(self, text: str) -> str:
        """Clean OCR text - uses shared utility"""
        return clean_ocr_text(text)

    def detect_language(self, text: str) -> str:
        """Detect language - uses shared utility with allowed languages mapping"""
        detected_lang = detect_language(text)
        
        allowed_languages = {
            'en': 'English',
            'fr': 'French', 
            'de': 'German',
            'it': 'Italian',
            'es': 'Spanish',
            'pt': 'Portuguese',
            'nl': 'Dutch'
        }
        
        return allowed_languages.get(detected_lang, 'unknown')

    # =============================================================================
    # Motion Analysis from JSON Files
    # =============================================================================
    
    def detect_motion_from_json_analysis(self, capture_path: str, json_count: int = 5, strict_mode: bool = True) -> Dict[str, Any]:
        """
        Helper method to detect motion/activity from JSON analysis files.
        Uses shared analysis utility to avoid code duplication.
        
        Args:
            capture_path: Direct path to the capture folder containing analysis files
            json_count: Number of recent JSON files to analyze (default: 5)
            strict_mode: If True, ALL files must show no errors. If False, majority must show no errors (default: True)
            
        Returns:
            Dict with detailed analysis similar to controller methods
        """
        try:
            # Import shared analysis utility
            from  backend_host.src.lib.utils.analysis_utils import load_recent_analysis_data_from_path, analyze_motion_from_loaded_data
            
            # Load recent analysis data using direct capture path (5 minutes timeframe)
            data_result = load_recent_analysis_data_from_path(capture_path, timeframe_minutes=5, max_count=json_count)
            
            if not data_result['success']:
                # Enhanced error logging for data loading failures
                error_detail = data_result.get('error', 'Failed to load analysis data')
                print(f"🔍 [VideoContent] Motion analysis data loading failed: {error_detail}")
                print(f"🔍 [VideoContent] Capture path: {capture_path}")
                return {
                    'success': False,
                    'video_ok': False,
                    'audio_ok': False,
                    'blackscreen_count': 0,
                    'freeze_count': 0,
                    'audio_loss_count': 0,
                    'total_analyzed': 0,
                    'details': [],
                    'strict_mode': strict_mode,
                    'message': error_detail
                }
            
            # Analyze motion from loaded data using shared utility
            result = analyze_motion_from_loaded_data(data_result['analysis_data'], json_count, strict_mode)
            
            print(f"VideoContent[{self.device_name}]: Motion detection result: {result.get('message', 'Unknown')}")
            return result
            
        except Exception as e:
            error_msg = f"Motion detection from JSON error: {e}"
            print(f"VideoContent[{self.device_name}]: {error_msg}")
            return {
                'success': False,
                'video_ok': False,
                'audio_ok': False,
                'blackscreen_count': 0,
                'freeze_count': 0,
                'audio_loss_count': 0,
                'total_analyzed': 0,
                'details': [],
                'strict_mode': strict_mode,
                'message': error_msg
            }

    # =============================================================================
    # Macroblock Detection
    # =============================================================================
    
    def detect_macroblocks_batch(self, image_paths: List[str]) -> Dict[str, Any]:
        """
        Detect macroblocks/image quality issues in multiple images.
        Similar pattern to detect_blackscreen_batch.
        """
        results = []
        
        for image_path in image_paths:
            if not os.path.exists(image_path):
                results.append({
                    'image_path': image_path,
                    'success': False,
                    'error': 'Image file not found'
                })
                continue
            
            try:
                # Use same algorithm as analyze_audio_video.py
                macroblocks_detected, quality_score = self._analyze_macroblocks_simple(image_path)
                
                results.append({
                    'image_path': os.path.basename(image_path),
                    'success': True,
                    'macroblocks_detected': macroblocks_detected,
                    'quality_score': quality_score
                })
                
                print(f"VideoContent[{self.device_name}]: Macroblock analysis - macroblocks={macroblocks_detected}, quality={quality_score:.1f}")
                
            except Exception as e:
                results.append({
                    'image_path': image_path,
                    'success': False,
                    'error': f'Analysis error: {str(e)}'
                })
        
        # Calculate overall result
        successful_analyses = [r for r in results if r.get('success')]
        macroblocks_detected = any(r.get('macroblocks_detected', False) for r in successful_analyses)
        
        # Calculate average quality score
        quality_scores = [r.get('quality_score', 0.0) for r in successful_analyses if r.get('quality_score') is not None]
        average_quality_score = sum(quality_scores) / len(quality_scores) if quality_scores else 0.0
        
        overall_result = {
            'success': len(successful_analyses) > 0,
            'macroblocks_detected': macroblocks_detected,
            'quality_score': round(average_quality_score, 1),
            'analyzed_images': len(results),
            'successful_analyses': len(successful_analyses),
            'results': results,
            'analysis_type': 'macroblock_detection',
            'timestamp': datetime.now().isoformat()
        }
        
        return overall_result

    def _analyze_macroblocks_simple(self, image_path: str) -> Tuple[bool, float]:
        """Conservative macroblock detection - same algorithm as analyze_audio_video.py"""
        try:
            img = cv2.imread(image_path)
            if img is None:
                return False, 0.0
            
            # Convert to different color spaces for analysis
            hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
            img_height, img_width = img.shape[:2]
            
            # 1. Detect abnormal color pixels (green/pink artifacts)
            # Sample every 10th pixel for performance (reuse existing pattern)
            sample_rate = 10  # Same as freeze detection
            hsv_sampled = hsv[::sample_rate, ::sample_rate]
            
            # Green artifacts: High saturation in green range
            green_mask = cv2.inRange(hsv_sampled, (40, 100, 50), (80, 255, 255))
            green_pixels = np.sum(green_mask > 0)
            
            # Pink/Magenta artifacts: High saturation in magenta range  
            pink_mask = cv2.inRange(hsv_sampled, (140, 100, 50), (170, 255, 255))
            pink_pixels = np.sum(pink_mask > 0)
            
            total_sampled = hsv_sampled.shape[0] * hsv_sampled.shape[1]
            artifact_percentage = ((green_pixels + pink_pixels) / total_sampled) * 100
            
            # 2. Conservative blur detection using Laplacian variance
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            gray_sampled = gray[::sample_rate, ::sample_rate]
            laplacian_var = cv2.Laplacian(gray_sampled, cv2.CV_64F).var()
            
            # CONSERVATIVE THRESHOLDS - Only flag obvious macroblocks
            has_severe_artifacts = artifact_percentage > 8.0  # Raised from 2% to 8% - must be obvious
            is_severely_blurry = laplacian_var < 30  # Lowered from 100 to 30 - must be very blurry
            
            # Additional validation: both conditions should be somewhat present for true macroblocks
            # If only one condition is met, require it to be very severe
            if has_severe_artifacts and is_severely_blurry:
                # Both conditions met - likely macroblocks
                macroblocks_detected = True
                confidence = "high"
            elif has_severe_artifacts and artifact_percentage > 15.0:
                # Very high artifact percentage alone
                macroblocks_detected = True
                confidence = "medium_artifacts"
            elif is_severely_blurry and laplacian_var < 15:
                # Extremely blurry alone
                macroblocks_detected = True
                confidence = "medium_blur"
            else:
                # Neither condition severe enough
                macroblocks_detected = False
                confidence = "none"
            
            quality_score = max(artifact_percentage, (200 - laplacian_var) / 2) if macroblocks_detected else 0.0
            
            # Detailed logging (same format as blackscreen detection)
            print(f"VideoContent[{self.device_name}]: Macroblock check: {img_width}x{img_height} | artifacts={artifact_percentage:.1f}% (threshold: 8.0%), blur_var={laplacian_var:.1f} (threshold: 30), detected={macroblocks_detected} ({confidence})")
            
            return macroblocks_detected, quality_score
            
        except Exception as e:
            print(f"VideoContent[{self.device_name}]: Macroblock analysis error: {e}")
            return False, 0.0

    # =============================================================================
    # Freeze-based Zapping Detection
    # =============================================================================
    
    def detect_freeze_zapping_sequence(self, folder_path: str, key_release_timestamp: float, 
                                      analysis_rectangle: Dict[str, int] = None, max_images: int = 15, 
                                      banner_region: Dict[str, int] = None) -> Dict[str, Any]:
        """
        Detect freeze-based zapping sequence (similar to blackscreen zapping but for freeze frames).
        
        Args:
            folder_path: Path to folder containing captured images
            key_release_timestamp: Timestamp when zapping key was released (Unix timestamp)
            analysis_rectangle: Rectangle to analyze for freeze detection
            max_images: Maximum number of images to analyze (default: 10)
            banner_region: Region where banner appears for AI analysis (optional)
            
        Returns:
            Dictionary with freeze zapping analysis results
        """
        try:
            print(f"VideoContent[{self.device_name}]: Starting freeze-based zapping detection in {folder_path}")
            
            capture_format_timestamp = self._convert_unix_to_capture_format(key_release_timestamp)
            print(f"VideoContent[{self.device_name}]: Key release timestamp: {capture_format_timestamp} (Unix: {key_release_timestamp})")
            
            # Use thumbnails for performance - auto-correction will fit rectangle to thumbnail size
            image_data = self._get_images_after_timestamp(folder_path, key_release_timestamp, max_images, use_thumbnails=True)
            
            if not image_data:
                return {
                    'success': False,
                    'error': 'No images found after key release timestamp',
                    'freeze_zapping_detected': False,
                    'freeze_duration': 0.0,
                    'debug_images': [],
                    'analysis_type': 'freeze_zapping_detection'
                }
            
            print(f"VideoContent[{self.device_name}]: Found {len(image_data)} images to analyze for freeze zapping")
            
            image_paths = [img['path'] for img in image_data]
            freeze_results = self.detect_freeze_in_images(image_paths, freeze_threshold=0.2)
            
            if not freeze_results.get('success', False):
                return {
                    'success': False,
                    'error': f"Freeze analysis failed: {freeze_results.get('error', 'Unknown error')}",
                    'freeze_zapping_detected': False,
                    'freeze_duration': 0.0,
                    'analysis_type': 'freeze_zapping_detection'
                }
            
            freeze_sequence = self._find_freeze_sequence(freeze_results.get('comparisons', []))
            
            freeze_duration = 0.0
            zapping_duration = 0.0
            
            if freeze_sequence['freeze_zapping_detected']:
                max_consecutive = freeze_results.get('max_consecutive_frozen', 0)
                freeze_duration = max_consecutive * 0.2
                
                first_image_time = image_data[0]['timestamp']
                if freeze_sequence.get('freeze_end_index') is not None:
                    freeze_end_time = image_data[freeze_sequence['freeze_end_index']]['timestamp']
                    zapping_duration = freeze_end_time - first_image_time
                else:
                    last_image_time = image_data[-1]['timestamp']
                    zapping_duration = last_image_time - first_image_time
            channel_info = {
                'channel_name': '',
                'channel_number': '',
                'program_name': '',
                'start_time': '',
                'end_time': '',
                'confidence': 0.0
            }
            
            if freeze_sequence['freeze_zapping_detected'] and freeze_sequence.get('freeze_end_index') is not None:
                if freeze_sequence['freeze_end_index'] < len(image_data) - 1:
                    channel_info = self._extract_channel_info_from_images(
                        image_data, freeze_sequence['freeze_end_index'], banner_region
                    )
            
            overall_result = {
                'success': True,
                'freeze_zapping_detected': freeze_sequence['freeze_zapping_detected'],
                'freeze_duration': round(freeze_duration, 2),
                'zapping_duration': round(zapping_duration, 2),
                'first_image': image_data[0]['filename'] if image_data else None,
                'blackscreen_start_image': self._get_freeze_start_image(image_data, freeze_sequence),
                'blackscreen_end_image': self._get_freeze_end_image(image_data, freeze_sequence),
                'first_content_after_blackscreen': self._get_first_content_after_freeze(image_data, freeze_sequence),
                'last_image': image_data[-1]['filename'] if image_data else None,
                'debug_images': [img['filename'] for img in image_data],
                'channel_info': channel_info,
                'analyzed_images': len(image_data),
                'max_consecutive_frozen': freeze_results.get('max_consecutive_frozen', 0),
                'frozen_comparisons': freeze_results.get('frozen_comparisons', 0),
                'frame_comparisons': freeze_results.get('frame_comparisons', 0),
                'details': {
                    'freeze_results': freeze_results,
                    'freeze_sequence': freeze_sequence,
                    'timestamps': {
                        'first_image': image_data[0]['timestamp'] if image_data else None,
                        'last_image': image_data[-1]['timestamp'] if image_data else None
                    }
                },
                'analysis_type': 'freeze_zapping_detection',
                'timestamp': datetime.now().isoformat()
            }
            
            print(f"VideoContent[{self.device_name}]: Freeze zapping detection complete - detected={freeze_sequence['freeze_zapping_detected']}, duration={freeze_duration}s")
            return overall_result
            
        except Exception as e:
            print(f"VideoContent[{self.device_name}]: Freeze zapping detection error: {e}")
            return {
                'success': False,
                'error': f'Freeze zapping detection failed: {str(e)}',
                'freeze_zapping_detected': False,
                'freeze_duration': 0.0,
                'analysis_type': 'freeze_zapping_detection'
            }

    def _find_freeze_sequence(self, comparisons: List[Dict]) -> Dict[str, Any]:
        """
        Find freeze start and end in the sequence of comparisons (similar to blackscreen sequence).
        
        Args:
            comparisons: List of frame comparison results
            
        Returns:
            Dictionary with freeze sequence information
        """
        freeze_start_index = None
        freeze_end_index = None
        freeze_images = []
        
        # Find all frozen comparisons
        for i, comparison in enumerate(comparisons):
            if comparison.get('is_frozen', False):
                freeze_images.append(i)
        
        if not freeze_images:
            return {
                'freeze_start_index': None,
                'freeze_end_index': None,
                'freeze_zapping_detected': False
            }
        
        # Find sequence boundaries
        freeze_start_index = freeze_images[0]
        print(f"VideoContent[{self.device_name}]: Freeze started at comparison {freeze_start_index}")
        
        # Look for freeze end (first non-frozen after start)
        for i in range(freeze_start_index + 1, len(comparisons)):
            comparison = comparisons[i]
            if not comparison.get('is_frozen', False):
                freeze_end_index = i
                print(f"VideoContent[{self.device_name}]: Freeze ended at comparison {freeze_end_index}")
                break
        
        # Only consider zapping detected if we have both freeze start AND freeze end
        # A freeze that never ends indicates a stuck/frozen screen, not successful zapping
        freeze_zapping_detected = freeze_start_index is not None and freeze_end_index is not None
        
        if freeze_start_index is not None and freeze_end_index is None:
            print(f"VideoContent[{self.device_name}]: Freeze detected but never ended - screen appears stuck/frozen, not successful zapping")
        
        return {
            'freeze_start_index': freeze_start_index,
            'freeze_end_index': freeze_end_index,
            'freeze_zapping_detected': freeze_zapping_detected
        }

    def _get_freeze_start_image(self, image_data: List[Dict], freeze_sequence: Dict[str, Any]) -> Optional[str]:
        """Get the first freeze image filename. Adjust comparison index to image index."""
        start_index = freeze_sequence.get('freeze_start_index')
        if start_index is not None:
            # Comparison index maps to second image in comparison (index + 1)
            image_index = start_index + 1
            if image_index < len(image_data):
                return image_data[image_index]['filename']
        return None

    def _get_freeze_end_image(self, image_data: List[Dict], freeze_sequence: Dict[str, Any]) -> Optional[str]:
        """Get the last freeze image filename. Adjust comparison index to image index."""
        end_index = freeze_sequence.get('freeze_end_index')
        if end_index is not None:
            # For freeze end, we want the last frozen image (end_index maps to first non-frozen)
            # So last frozen is at comparison end_index - 1, which maps to image end_index
            image_index = end_index
            if image_index < len(image_data):
                return image_data[image_index]['filename']
        return None

    def _get_first_content_after_freeze(self, image_data: List[Dict], freeze_sequence: Dict[str, Any]) -> Optional[str]:
        """Get the first content image after freeze. Adjust comparison index to image index."""
        end_index = freeze_sequence.get('freeze_end_index')
        if end_index is not None:
            # Comparison end_index is first non-frozen comparison, maps to image end_index + 1
            image_index = end_index + 1
            if image_index < len(image_data):
                return image_data[image_index]['filename']
        return None

    # =============================================================================
    # Zapping Detection
    # =============================================================================
    
    def detect_zapping_sequence(self, folder_path: str, key_release_timestamp: float, 
                               analysis_rectangle: Dict[str, int] = None, max_images: int = 10, 
                               banner_region: Dict[str, int] = None, device_model: str = None) -> Dict[str, Any]:
        """
        Simple zapping detection using existing components and direct file access.
        
        Args:
            folder_path: Path to folder containing captured images
            key_release_timestamp: Timestamp when zapping key was released (Unix timestamp)
            analysis_rectangle: Rectangle to analyze for blackscreen (exclude banner area)
            max_images: Maximum number of images to analyze (default: 10)
            
        Returns:
            Dictionary with zapping analysis results
        """
        try:
            print(f"VideoContent[{self.device_name}]: Starting simple zapping detection in {folder_path}")
            
            capture_format_timestamp = self._convert_unix_to_capture_format(key_release_timestamp)
            print(f"VideoContent[{self.device_name}]: Key release timestamp: {capture_format_timestamp} (Unix: {key_release_timestamp})")
            
            # Use thumbnails for performance - percentage-based analysis works at any resolution
            image_data = self._get_images_after_timestamp(folder_path, key_release_timestamp, max_images, use_thumbnails=True)
            
            if not image_data:
                return {
                    'success': False,
                    'error': 'No images found after key release timestamp',
                    'zapping_detected': False,
                    'blackscreen_duration': 0.0,
                    'debug_images': [],  # No images to debug
                    'analysis_type': 'simple_zapping_detection'
                }
            
            print(f"VideoContent[{self.device_name}]: Found {len(image_data)} images to analyze")
            
            # Log analysis configuration
            img_type = "thumbnails" if image_data and '_thumbnail' in image_data[0]['path'] else "full-resolution"
            print(f"VideoContent[{self.device_name}]: Using {img_type} images for blackscreen detection")
            
            # Step 2: Batch blackscreen detection using proven algorithm with device-specific threshold
            blackscreen_results = self._detect_blackscreen_batch(image_data, analysis_rectangle, device_model)
            
            # Step 3: Find blackscreen sequence
            sequence = self._find_blackscreen_sequence(blackscreen_results)
            
            # Step 4: Calculate durations (both blackscreen and zapping)
            blackscreen_duration = 0.0
            zapping_duration = 0.0
            
            if sequence['zapping_detected']:
                # Zapping duration: from first image (action completion) to blackscreen disappearance
                first_image_time = image_data[0]['timestamp']
                
                if sequence.get('single_image_case', False):
                    # Single blackscreen image case (fast zapping under 2s)
                    # Assume 1-second blackscreen duration as specified
                    blackscreen_duration = 1.0
                    blackscreen_start_time = image_data[sequence['blackscreen_start_index']]['timestamp']
                    
                    # If blackscreen appears before our action timestamp, start zapping 1s before blackscreen
                    if blackscreen_start_time < key_release_timestamp:
                        adjusted_zapping_start = blackscreen_start_time - 1.0
                        zapping_duration = (blackscreen_start_time + blackscreen_duration) - adjusted_zapping_start
                    else:
                        time_to_blackscreen = blackscreen_start_time - first_image_time
                        zapping_duration = time_to_blackscreen + blackscreen_duration
                    print(f"VideoContent[{self.device_name}]: Single image case - assumed 1s blackscreen, total zapping: {zapping_duration:.1f}s")
                    
                elif sequence['blackscreen_end_index'] is not None:
                    # Normal case: blackscreen ended - zapping duration is from start to blackscreen end
                    blackscreen_end_time = image_data[sequence['blackscreen_end_index']]['timestamp']
                    
                    # If blackscreen appears before our action timestamp, adjust zapping start time
                    if sequence['blackscreen_start_index'] is not None:
                        blackscreen_start_time = image_data[sequence['blackscreen_start_index']]['timestamp']
                        if blackscreen_start_time < key_release_timestamp:
                            # Blackscreen detected before action timestamp - start zapping 1s before blackscreen
                            adjusted_zapping_start = blackscreen_start_time - 1.0
                            zapping_duration = blackscreen_end_time - adjusted_zapping_start
                        else:
                            zapping_duration = blackscreen_end_time - first_image_time
                        
                        # Blackscreen duration: from blackscreen start to blackscreen end
                        blackscreen_duration = blackscreen_end_time - blackscreen_start_time
                    else:
                        zapping_duration = blackscreen_end_time - first_image_time
                else:
                    # Blackscreen didn't end in our window - use last image
                    last_image_time = image_data[-1]['timestamp']
                    zapping_duration = last_image_time - first_image_time
                    
                    if sequence['blackscreen_start_index'] is not None:
                        blackscreen_start_time = image_data[sequence['blackscreen_start_index']]['timestamp']
                        blackscreen_duration = last_image_time - blackscreen_start_time
            
            # Step 5: Extract channel information using AI (if blackscreen ended)
            channel_info = {
                'channel_name': '',
                'channel_number': '',
                'program_name': '',
                'start_time': '',
                'end_time': '',
                'confidence': 0.0
            }
            
            # Try AI analysis if we have blackscreen end OR single image case
            if sequence['zapping_detected']:
                if sequence.get('single_image_case', False):
                    # For single image case, try to extract channel info from images after the blackscreen image
                    blackscreen_index = sequence['blackscreen_start_index']
                    if blackscreen_index < len(image_data) - 1:
                        print(f"VideoContent[{self.device_name}]: Single image case - analyzing images after blackscreen for channel info")
                        channel_info = self._extract_channel_info_from_images(
                            image_data, blackscreen_index + 1, banner_region
                        )
                elif (sequence['blackscreen_end_index'] is not None and 
                      sequence['blackscreen_end_index'] < len(image_data) - 1):
                    # Normal case: analyze images after blackscreen ends
                    channel_info = self._extract_channel_info_from_images(
                        image_data, sequence['blackscreen_end_index'], banner_region
                    )
            
            # Compile complete results with all information
            overall_result = {
                # Core zapping detection results
                'success': True,
                'zapping_detected': sequence['zapping_detected'],
                
                # Duration information
                'zapping_duration': round(zapping_duration, 2),          # Total time from action to blackscreen end
                'blackscreen_duration': round(blackscreen_duration, 2), # Time blackscreen was visible
                
                # Channel information
                'channel_name': channel_info.get('channel_name', ''),
                'channel_number': channel_info.get('channel_number', ''),
                'program_name': channel_info.get('program_name', ''),
                'program_start_time': channel_info.get('start_time', ''),
                'program_end_time': channel_info.get('end_time', ''),
                'channel_confidence': channel_info.get('confidence', 0.0),
                
                # Image sequence information
                'first_image': image_data[0]['filename'] if image_data else None,
                'blackscreen_start_image': image_data[sequence['blackscreen_start_index']]['filename'] if sequence.get('blackscreen_start_index') is not None else None,
                'blackscreen_end_image': self._get_blackscreen_end_image(image_data, sequence),
                'first_content_after_blackscreen': self._get_first_content_after_blackscreen(image_data, sequence),
                'last_image': image_data[-1]['filename'] if image_data else None,
                
                # Debug images for analysis (all analyzed images for debugging)
                'debug_images': [result['filename'] for result in blackscreen_results],
                
                # Analysis metadata
                'analyzed_images': len(blackscreen_results),
                'total_images_available': len(image_data),
                'key_release_timestamp': key_release_timestamp,
                'analysis_rectangle': analysis_rectangle,
                
                # Detailed results for debugging
                'details': {
                    'images_analyzed': [result['filename'] for result in blackscreen_results],
                    'blackscreen_percentages': [result.get('blackscreen_percentage', 0) for result in blackscreen_results],
                    'blackscreen_sequence': {
                        'start_index': sequence['blackscreen_start_index'],
                        'end_index': sequence['blackscreen_end_index']
                    },
                    'timestamps': {
                        'first_image': image_data[0]['timestamp'] if image_data else None,
                        'blackscreen_start': image_data[sequence['blackscreen_start_index']]['timestamp'] if sequence.get('blackscreen_start_index') is not None else None,
                        'blackscreen_end': image_data[sequence['blackscreen_end_index']]['timestamp'] if sequence.get('blackscreen_end_index') is not None else None,
                        'last_image': image_data[-1]['timestamp'] if image_data else None
                    },
                    'channel_analysis': channel_info,
                    'blackscreen_results': blackscreen_results
                },
                'analysis_type': 'simple_zapping_detection',
                'timestamp': datetime.now().isoformat()
            }
            
            print(f"VideoContent[{self.device_name}]: Simple zapping detection complete - detected={sequence['zapping_detected']}, duration={blackscreen_duration}s")
            return overall_result
            
        except Exception as e:
            print(f"VideoContent[{self.device_name}]: Simple zapping detection error: {e}")
            
            # Try to get debug images even if analysis failed
            debug_images = []
            try:
                if 'image_data' in locals() and image_data:
                    debug_images = [img['filename'] for img in image_data]
                elif 'blackscreen_results' in locals() and blackscreen_results:
                    debug_images = [result['filename'] for result in blackscreen_results]
            except:
                pass  # If we can't get debug images, just use empty list
            
            return {
                'success': False,
                'error': f'Simple zapping detection failed: {str(e)}',
                'analysis_type': 'simple_zapping_detection',
                'zapping_detected': False,
                'blackscreen_duration': 0.0,
                'debug_images': debug_images
            }

    def _get_images_after_timestamp(self, folder_path: str, start_timestamp: float, max_count: int = 10, use_thumbnails: bool = False) -> List[Dict]:
        """Get images after timestamp for detection analysis - searches both HOT and COLD storage."""
        try:
            from shared.src.lib.utils.storage_path_utils import get_capture_storage_path, get_cold_storage_path, is_ram_mode
            
            # Check if device is in RAM mode - if so, search BOTH hot and cold folders
            # (images may have been archived from hot to cold during zap execution)
            search_folders = []
            
            if is_ram_mode(folder_path):
                # RAM mode: search both hot (active) and cold (recently archived)
                if use_thumbnails:
                    search_folders.append(get_capture_storage_path(folder_path, 'thumbnails'))  # Hot thumbnails
                    search_folders.append(get_cold_storage_path(folder_path, 'thumbnails'))    # Cold thumbnails (if archived)
                else:
                    search_folders.append(get_capture_storage_path(folder_path, 'captures'))   # Hot captures
                    search_folders.append(get_cold_storage_path(folder_path, 'captures'))      # Cold captures (archived)
            else:
                # SD mode: only one location
                if use_thumbnails:
                    search_folders.append(get_capture_storage_path(folder_path, 'thumbnails'))
                else:
                    search_folders.append(get_capture_storage_path(folder_path, 'captures'))
            
            image_pattern = 'capture_*_thumbnail.jpg' if use_thumbnails else 'capture_*.jpg'
            MAX_TOTAL_IMAGES = max_count if max_count > 0 else 40
            
            import re
            capture_files = []
            
            # Search all folders (hot + cold in RAM mode, single folder in SD mode)
            for images_folder in search_folders:
                if not os.path.exists(images_folder):
                    continue
                
                try:
                    if use_thumbnails:
                        result = subprocess.run([
                            'find', images_folder, '-name', image_pattern, '-type', 'f'
                        ], capture_output=True, text=True, timeout=30)
                    else:
                        result = subprocess.run([
                            'find', images_folder, '-name', 'capture_*.jpg', '!', '-name', '*_thumbnail.jpg', '-type', 'f'
                        ], capture_output=True, text=True, timeout=30)
                    
                    if result.returncode != 0:
                        continue
                    
                    for file_path in result.stdout.strip().split('\n'):
                        if not file_path:
                            continue
                        
                        filename = os.path.basename(file_path)
                        pattern = r'capture_(\d+)_thumbnail\.jpg' if use_thumbnails else r'capture_(\d+)\.jpg'
                        match = re.match(pattern, filename)
                        
                        if match:
                            try:
                                file_mtime = os.path.getmtime(file_path)
                                if file_mtime >= start_timestamp:
                                    capture_number = int(match.group(1))
                                    # Avoid duplicates (same file in hot and cold) - keep newest
                                    existing = next((f for f in capture_files if f[0] == capture_number), None)
                                    if existing:
                                        if file_mtime > os.path.getmtime(existing[1]):
                                            capture_files.remove(existing)
                                            capture_files.append((capture_number, file_path))
                                    else:
                                        capture_files.append((capture_number, file_path))
                            except OSError:
                                continue
                    
                except (subprocess.TimeoutExpired, Exception):
                    continue
            
            # Sort by capture number and limit results
            capture_files.sort(key=lambda x: x[0])
            valid_files = [f[1] for f in capture_files][:max_count] if max_count > 0 else [f[1] for f in capture_files]
            
            images = []
            for file_path in valid_files[:MAX_TOTAL_IMAGES]:
                images.append({
                    'path': file_path,
                    'timestamp': os.path.getmtime(file_path),
                    'filename': os.path.basename(file_path),
                    'sequential_format': True
                })
            
            return sorted(images, key=lambda x: x['timestamp'])
            
        except Exception as e:
            print(f"VideoContent[{self.device_name}]: Error getting images after timestamp: {e}")
            return []

    def _convert_unix_to_capture_format(self, unix_timestamp: float) -> str:
        """Convert Unix timestamp to capture format (no-op for sequential naming)."""
        return ""

    def _detect_blackscreen_batch(self, image_data: List[Dict], analysis_rectangle: Dict[str, int] = None, device_model: str = None) -> List[Dict]:
        """Batch blackscreen detection with early stopping."""
        results = []
        blackscreen_detected = False
        MAX_ANALYSIS_IMAGES = min(50, len(image_data))
        
        for i, img_data in enumerate(image_data):
            if i >= MAX_ANALYSIS_IMAGES:
                break
                
            image_path = img_data['path']
            
            try:
                is_blackscreen, blackscreen_percentage = self._analyze_blackscreen_simple(image_path, analysis_rectangle, 5, device_model)
                
                result = {
                    'path': image_path,
                    'filename': img_data['filename'],
                    'timestamp': img_data['timestamp'],
                    'is_blackscreen': is_blackscreen,
                    'blackscreen_percentage': blackscreen_percentage,
                    'success': True,
                    'second_group': img_data.get('second_group', 0),
                    'files_in_second': img_data.get('files_in_second', 1)
                }
                results.append(result)
                
                # Log each analysis result
                status_emoji = "⬛" if is_blackscreen else "📺"
                print(f"VideoContent[{self.device_name}]: {status_emoji} {img_data['filename']}: {blackscreen_percentage:.1f}% dark (blackscreen={is_blackscreen})")
                
                if is_blackscreen and not blackscreen_detected:
                    blackscreen_detected = True
                    print(f"VideoContent[{self.device_name}]: ⚡ Blackscreen START at {img_data['filename']} - continuing to find END...")
                
                elif blackscreen_detected and not is_blackscreen:
                    print(f"VideoContent[{self.device_name}]: ✅ Blackscreen END at {img_data['filename']} - STOPPING EARLY!")
                    break
                
            except Exception as e:
                results.append({
                    'path': image_path,
                    'filename': img_data['filename'],
                    'timestamp': img_data['timestamp'],
                    'is_blackscreen': False,
                    'blackscreen_percentage': 0.0,
                    'success': False,
                    'error': str(e)
                })
                print(f"VideoContent[{self.device_name}]: ❌ {img_data['filename']}: Analysis error - {e}")
        
        print(f"VideoContent[{self.device_name}]: Blackscreen analysis complete - {len(results)} images analyzed, early_stopped={blackscreen_detected}")
        return results

    def _analyze_blackscreen_simple(self, image_path: str, analysis_rectangle: Dict[str, int] = None, threshold: int = 5, device_model: str = None) -> Tuple[bool, float]:
        """
        Smart blackscreen detection that works at any image resolution.
        Analysis rectangle is ignored for thumbnails - we analyze the top portion to exclude banner.
        
        Args:
            image_path: Path to image file (full-res or thumbnail)
            analysis_rectangle: Optional rectangle (only used for full-resolution images)
            threshold: Pixel intensity threshold (0-255, default: 5 for real blackscreen detection)
            
        Returns:
            Tuple of (is_blackscreen, blackscreen_percentage)
        """
        try:
            img = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
            if img is None:
                return False, 0.0
            
            img_height, img_width = img.shape
            
            # Smart detection: Is this a thumbnail or full-resolution image?
            is_thumbnail = '_thumbnail' in image_path or img_width < 1000
            
            if is_thumbnail:
                # Thumbnail: Analyze top 70% (exclude banner at bottom ~30%)
                # Blackscreen happens in the center during zapping, not in banner area
                x = 0
                y = 0
                width = img_width
                height = int(img_height * 0.7)  # Top 70%
            else:
                # Full-resolution: Use provided rectangle or default
                if analysis_rectangle:
                    x = analysis_rectangle.get('x', 0)
                    y = analysis_rectangle.get('y', 0)
                    width = analysis_rectangle.get('width', img_width)
                    height = analysis_rectangle.get('height', img_height)
                    
                    # Clamp to image bounds (same as old auto-correction logic)
                    x = max(0, x)
                    y = max(0, y)
                    if x + width > img_width:
                        width = img_width - x
                    if y + height > img_height:
                        height = img_height - y
                else:
                    # Default: top 70% of image
                    x = 0
                    y = 0
                    width = img_width
                    height = int(img_height * 0.7)
            
            # Crop to analysis region
            img = img[y:y+height, x:x+width]
            
            # FAST PATH: Sample-based detection for performance
            # For true blackscreen (0,0,0), we don't need to check every pixel
            total_pixels = img.shape[0] * img.shape[1]
            
            # Sample 10% of pixels in a grid pattern (much faster)
            sample_step = 3  # Check every 3rd pixel in both directions = ~11% sample
            sample = img[::sample_step, ::sample_step]
            sample_dark_pixels = np.sum(sample <= threshold)
            sample_total = sample.shape[0] * sample.shape[1]
            dark_percentage = (sample_dark_pixels / sample_total) * 100
            
            # If sample shows definitive result (>90% or <70%), trust it
            # Otherwise fall back to full analysis for edge cases
            if dark_percentage < 70 or dark_percentage > 90:
                # Confident result from sample - no need for full analysis
                pass
            else:
                # Edge case: 70-90% range, do full analysis to be sure
                very_dark_pixels = np.sum(img <= threshold)
                dark_percentage = (very_dark_pixels / total_pixels) * 100
            
            # Device-specific blackscreen thresholds to account for UI overlays
            if device_model and 'mobile' in device_model.lower():
                blackscreen_threshold = 70  # Mobile: 70% threshold (accounts for UI overlays)
            else:
                blackscreen_threshold = 85  # Desktop/STB: 85% threshold (minimal UI overlay)
            
            is_blackscreen = dark_percentage > blackscreen_threshold
            
            return is_blackscreen, dark_percentage
            
        except Exception as e:
            print(f"VideoContent[{self.device_name}]: Blackscreen analysis error: {e}")
            return False, 0.0

    def _find_blackscreen_sequence(self, blackscreen_results: List[Dict]) -> Dict[str, Any]:
        """
        Find blackscreen start and end in the sequence of results.
        Handles both full sequences and single blackscreen images (fast zapping).
        
        Args:
            blackscreen_results: List of blackscreen analysis results
            
        Returns:
            Dictionary with sequence information
        """
        blackscreen_start_index = None
        blackscreen_end_index = None
        blackscreen_images = []
        
        # First pass: identify all blackscreen images
        for i, result in enumerate(blackscreen_results):
            if result.get('success', False) and result.get('is_blackscreen', False):
                blackscreen_images.append(i)
        
        if not blackscreen_images:
            # No blackscreen detected
            return {
                'blackscreen_start_index': None,
                'blackscreen_end_index': None,
                'zapping_detected': False,
                'single_image_case': False
            }
        
        # Find sequence boundaries
        blackscreen_start_index = blackscreen_images[0]
        print(f"VideoContent[{self.device_name}]: Blackscreen started at {blackscreen_results[blackscreen_start_index]['filename']}")
        
        # Look for blackscreen end (first non-blackscreen after start)
        for i in range(blackscreen_start_index + 1, len(blackscreen_results)):
            result = blackscreen_results[i]
            if result.get('success', False) and not result.get('is_blackscreen', False):
                blackscreen_end_index = i
                print(f"VideoContent[{self.device_name}]: Blackscreen ended at {result['filename']}")
                break
        
        # Handle single blackscreen image case (fast zapping under 2s)
        single_image_case = len(blackscreen_images) == 1 and blackscreen_end_index is None
        if single_image_case:
            print(f"VideoContent[{self.device_name}]: Single blackscreen image detected - assuming fast zapping (1s duration)")
        
        zapping_detected = blackscreen_start_index is not None
        
        return {
            'blackscreen_start_index': blackscreen_start_index,
            'blackscreen_end_index': blackscreen_end_index,
            'zapping_detected': zapping_detected,
            'single_image_case': single_image_case
        }

    def _get_blackscreen_end_image(self, image_data: List[Dict], sequence: Dict[str, Any]) -> Optional[str]:
        """Get the last blackscreen image filename (the actual last black frame)."""
        if sequence.get('single_image_case', False):
            # For single blackscreen image, end image is the same as start image
            start_index = sequence.get('blackscreen_start_index')
            if start_index is not None and start_index < len(image_data):
                return image_data[start_index]['filename']
        else:
            # Normal case: blackscreen_end_index points to first content, so last black is end_index - 1
            end_index = sequence.get('blackscreen_end_index')
            if end_index is not None and end_index > 0:
                return image_data[end_index - 1]['filename']
        return None

    def _get_first_content_after_blackscreen(self, image_data: List[Dict], sequence: Dict[str, Any]) -> Optional[str]:
        """Get the first content image after blackscreen, handling single image case."""
        if sequence.get('single_image_case', False):
            # For single blackscreen image, first content is the next image after the blackscreen
            start_index = sequence.get('blackscreen_start_index')
            if start_index is not None and start_index + 1 < len(image_data):
                return image_data[start_index + 1]['filename']
        else:
            # Normal case: blackscreen_end_index already points to the first content image
            end_index = sequence.get('blackscreen_end_index')
            if end_index is not None and end_index < len(image_data):
                return image_data[end_index]['filename']
        return None

    def _extract_channel_info_from_images(self, image_data: List[Dict], blackscreen_end_index: int, 
                                         banner_region: Dict[str, int] = None) -> Dict[str, Any]:
        """
        Extract channel information from images after blackscreen ends using AI analysis.
        
        Args:
            image_data: List of image data dictionaries
            blackscreen_end_index: Index where blackscreen ended
            banner_region: Hardcoded banner region passed from zap_controller
            
        Returns:
            Dictionary with channel information
        """
        try:
            # Use the passed banner region from zap_controller (now properly hardcoded per device type)
            if not banner_region:
                print(f"VideoContent[{self.device_name}]: No banner region provided, skipping channel analysis")
                return {
                    'channel_name': '',
                    'channel_number': '',
                    'program_name': '',
                    'start_time': '',
                    'end_time': '',
                    'confidence': 0.0
                }
            
            print(f"VideoContent[{self.device_name}]: Using banner region: {banner_region}")
            
            # Try to extract channel info from images BEFORE blackscreen ends
            # Start from blackscreen_end_index - 1 to get the last transition image
            start_index = max(0, blackscreen_end_index - 1)  # Ensure we don't go below 0
            max_attempts = min(3, len(image_data) - start_index)
            
            for i in range(max_attempts):
                image_index = start_index + i
                if image_index >= len(image_data):
                    break
                
                image_path = image_data[image_index]['path']
                filename = image_data[image_index]['filename']
                
                print(f"VideoContent[{self.device_name}]: AI analysis on {filename} (image {i+1} from last transition) | banner_region: {banner_region}")
                
                # Use AI helper for channel banner analysis with cropped region first
                channel_result = self.ai_helpers.analyze_channel_banner_ai(image_path, banner_region)
                
                # Check if banner region analysis has useful info (even if banner_detected is false)
                has_useful_banner_info = False
                if channel_result.get('success', False):
                    banner_info = channel_result.get('channel_info', {})
                    has_useful_banner_info = any([
                        banner_info.get('channel_name'),
                        banner_info.get('channel_number'),
                        banner_info.get('program_name'),
                        banner_info.get('start_time'),
                        banner_info.get('end_time')
                    ])
                
                # If banner region analysis fails OR has no useful info, try with full image as fallback
                if not (channel_result.get('success', False) and (channel_result.get('banner_detected', False) or has_useful_banner_info)):
                    fallback_reason = "partial info but no banner detected" if has_useful_banner_info else "analysis failed"
                    print(f"VideoContent[{self.device_name}]: Banner region {fallback_reason}, trying full image analysis on {filename}")
                    
                    full_image_result = self.ai_helpers.analyze_channel_banner_ai(image_path, None)
                    
                    # Use full image result if it has useful information (regardless of banner_detected flag)
                    if full_image_result.get('success', False):
                        full_info = full_image_result.get('channel_info', {})
                        full_has_useful_info = any([
                            full_info.get('channel_name'),
                            full_info.get('channel_number'),
                            full_info.get('program_name'),
                            full_info.get('start_time'),
                            full_info.get('end_time')
                        ])
                        
                        # Use full image result if it has more/better info than banner region
                        if full_has_useful_info and (not has_useful_banner_info or full_image_result.get('confidence', 0) > channel_result.get('confidence', 0)):
                            channel_result = full_image_result
                            print(f"VideoContent[{self.device_name}]: Using full image analysis result for {filename}")
                        elif has_useful_banner_info:
                            print(f"VideoContent[{self.device_name}]: Keeping banner region result with partial info for {filename}")
                
                # Check if we have any useful channel information (regardless of banner_detected flag)
                if channel_result.get('success', False):
                    channel_info = channel_result.get('channel_info', {})
                    has_useful_info = any([
                        channel_info.get('channel_name'),
                        channel_info.get('channel_number'),
                        channel_info.get('program_name'),
                        channel_info.get('start_time'),
                        channel_info.get('end_time')
                    ])
                    
                    if has_useful_info:
                        banner_status = "detected" if channel_result.get('banner_detected', False) else "partial info found"
                        print(f"VideoContent[{self.device_name}]: Channel info {banner_status} from {filename}: {channel_info}")
                    
                    return {
                        'channel_name': channel_info.get('channel_name', ''),
                        'channel_number': channel_info.get('channel_number', ''),
                        'program_name': channel_info.get('program_name', ''),
                        'start_time': channel_info.get('start_time', ''),
                        'end_time': channel_info.get('end_time', ''),
                        'confidence': channel_result.get('confidence', 0.0),
                        'analyzed_image': filename,
                        'banner_region': banner_region
                    }
            
            print(f"VideoContent[{self.device_name}]: No channel information found in {max_attempts} images from last transition")
            return {
                'channel_name': '',
                'channel_number': '',
                'program_name': '',
                'start_time': '',
                'end_time': '',
                'confidence': 0.0,
                'analyzed_image': '',
                'banner_region': banner_region
            }
            
        except Exception as e:
            print(f"VideoContent[{self.device_name}]: Channel info extraction error: {e}")
            return {
                'channel_name': '',
                'channel_number': '',
                'program_name': '',
                'start_time': '',
                'end_time': '',
                'confidence': 0.0,
                'error': str(e)
            }



