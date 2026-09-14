"""
Video AI Analysis Helpers

AI-powered analysis functionality for the VideoVerificationController:
1. AI-powered subtitle detection and text extraction
2. Full image analysis with user questions
3. Language/subtitle menu analysis
4. Natural language response parsing
5. OpenRouter API integration

This helper handles all AI-powered analysis operations that require
external AI services for advanced content understanding.
"""

import os
import base64
import requests
import tempfile
import json
import re
import cv2
import numpy as np
from datetime import datetime
from typing import Dict, Any, Optional, Tuple, List

# Optional imports for fallback text extraction
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


class VideoAIHelpers:
    """AI-powered video analysis operations using OpenRouter API."""
    
    def __init__(self, av_controller, device_name: str = "VideoAI"):
        """
        Initialize video AI helpers.
        
        Args:
            av_controller: AV controller for capturing video/images and device context
            device_name: Name for logging purposes
        """
        self.av_controller = av_controller
        self.device_name = device_name
    
    # =============================================================================
    # AI-Powered Subtitle Analysis
    # =============================================================================
    
    def analyze_subtitle_with_ai(self, image) -> Tuple[str, str, float]:
        """
        AI-powered subtitle analysis using centralized AI utilities
        
        Args:
            image: OpenCV image array (numpy.ndarray) - NOT a string path!
            
        Returns:
            Tuple of (extracted_text, detected_language, confidence)
        """
        try:
            # Early validation - fail loudly if no image provided
            if image is None:
                raise ValueError(f"VideoAI[{self.device_name}]: ❌ CRITICAL ERROR - No image provided for AI subtitle analysis!")
            
            # Type enforcement - must be numpy array (cv2 image), not string path
            import numpy as np
            if isinstance(image, str):
                raise TypeError(f"VideoAI[{self.device_name}]: ❌ CRITICAL ERROR - Expected cv2 image array, got string path: {image}. Use cv2.imread() first!")
            
            if not isinstance(image, np.ndarray):
                raise TypeError(f"VideoAI[{self.device_name}]: ❌ CRITICAL ERROR - Expected cv2 image array (numpy.ndarray), got: {type(image)}")
            
            # Use centralized AI utilities
            from shared.src.lib.utils.ai_utils import call_vision_ai
            
            # Log the image being analyzed
            height, width = image.shape[:2]
            print(f"VideoAI[{self.device_name}]: Analyzing cv2 image array: {width}x{height} pixels")
            
            prompt = "Quickly analyze this image for subtitles. Respond with JSON: {\"subtitles_detected\": true/false, \"extracted_text\": \"text or empty\", \"detected_language\": \"language or unknown\", \"confidence\": 0.0-1.0}"
            
            print(f"VideoAI[{self.device_name}]: Calling AI with prompt: {prompt[:100]}...")
            result = call_vision_ai(prompt, image, max_tokens=300, temperature=0.0)
            print(f"VideoAI[{self.device_name}]: AI call result: success={result.get('success')}, error={result.get('error', 'None')}")
            
            if result['success']:
                content = result['content']
                print(f"VideoAI[{self.device_name}]: AI returned content (length: {len(content)}): {repr(content[:200])}")
                
                # Parse JSON response first (primary approach)
                try:
                    # Remove markdown code blocks if present
                    json_content = content
                    if content.startswith('```json') and content.endswith('```'):
                        json_content = content[7:-3].strip()
                    elif content.startswith('```') and content.endswith('```'):
                        json_content = content[3:-3].strip()
                    
                    ai_result = json.loads(json_content)
                    
                    # Check if AI actually detected subtitles - ignore language/confidence if not
                    if not ai_result.get('subtitles_detected', False):
                        print(f"VideoAI[{self.device_name}]: JSON parsing successful - No subtitles detected in image")
                        return '', 'unknown', 0.0
                    
                    extracted_text = ai_result.get('extracted_text', '').strip()
                    detected_language = ai_result.get('detected_language', 'unknown')
                    confidence = float(ai_result.get('confidence', 0.0))
                    
                    if extracted_text:
                        print(f"VideoAI[{self.device_name}]: JSON parsing successful - AI extracted subtitle text: '{extracted_text}' -> Language: {detected_language}, Confidence: {confidence}")
                        return extracted_text, detected_language, confidence
                    else:
                        print(f"VideoAI[{self.device_name}]: Subtitles detected but no text extracted")
                        return '', detected_language, confidence
                        
                except json.JSONDecodeError as e:
                    print(f"VideoAI[{self.device_name}]: JSON parsing failed, trying natural language fallback: {e}")
                    
                    # Fallback to natural language parsing
                    print(f"VideoAI[{self.device_name}]: AI response: {content}")
                    
                    # Check if no subtitles found
                    if 'no subtitles found' in content.lower() or 'no subtitles' in content.lower() or not content.strip():
                        print(f"VideoAI[{self.device_name}]: Natural language fallback - No subtitles detected in image")
                        return '', 'unknown', 0.0
                    
                    # Use natural language parsing to extract subtitle information
                    extracted_text, detected_language, confidence = self.parse_natural_language_response(content)
                
                if extracted_text:
                    print(f"VideoAI[{self.device_name}]: AI extracted subtitle text: '{extracted_text}' -> Language: {detected_language}, Confidence: {confidence}")
                    return extracted_text, detected_language, confidence
                else:
                    print(f"VideoAI[{self.device_name}]: Could not extract subtitle text from response")
                    return '', 'unknown', 0.0
            else:
                # AI call itself failed (e.g. API auth/network error). This is NOT the same
                # as "no subtitles in the image" — raise so the caller records the real reason
                # instead of silently reporting "no subtitles detected".
                error_msg = result.get('error', 'Unknown error')
                print(f"VideoAI[{self.device_name}]: AI subtitle analysis failed: {error_msg}")
                raise RuntimeError(f"AI subtitle analysis call failed: {error_msg}")

        except Exception as e:
            # Propagate so detect_subtitles_ai_batch / _all_frames record the real failure
            # rather than masking an API/decode error as an empty "no subtitles" result.
            print(f"VideoAI[{self.device_name}]: AI subtitle analysis error: {e}")
            raise

    def detect_subtitles_ai_batch(self, image_paths: List[str], extract_text: bool = True) -> Dict[str, Any]:
        """
        AI-powered subtitle detection for multiple images.
        Tests max 3 images with +1s intervals, breaks early if subtitles found.
        
        Args:
            image_paths: List of image paths to analyze
            extract_text: Whether to extract text using AI (always True for AI method)
            
        Returns:
            Dictionary with detailed AI subtitle analysis results
        """
        try:
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
                    
                    height, width = img.shape[:2]
                    
                    # AI-powered subtitle analysis - use full image only for better reliability
                    print(f"VideoAI[{self.device_name}]: Analyzing subtitles with full image")
                    extracted_text, detected_language, ai_confidence = self.analyze_subtitle_with_ai(img)
                    
                    if extracted_text and len(extracted_text.strip()) > 0:
                        print(f"VideoAI[{self.device_name}]: Subtitle analysis successful: '{extracted_text[:50]}{'...' if len(extracted_text) > 50 else ''}'")
                    else:
                        print(f"VideoAI[{self.device_name}]: No subtitles detected in full image analysis")
                    
                    # Determine if subtitles were detected
                    has_subtitles = bool(extracted_text and len(extracted_text.strip()) > 0)
                    
                    # Error detection (same logic as OCR method for consistency)
                    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
                    
                    # Use configurable grid sampling rate
                    grid_rate = 15  # Every 15th pixel in grid for errors
                    sampled_hsv = hsv[::grid_rate, ::grid_rate]
                    
                    # Red color range in HSV - more restrictive for actual error messages
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
                    
                    # Higher threshold for error detection
                    has_errors = bool(red_percentage > 8.0)
                    
                    # Use AI confidence or set default
                    confidence = ai_confidence if has_subtitles else 0.1
                    
                    result = {
                        'image_path': os.path.basename(image_path),
                        'success': True,
                        'has_subtitles': has_subtitles,
                        'has_errors': has_errors,
                        'subtitle_edges': 0,  # Not applicable for AI method
                        'subtitle_threshold': 0.0,  # Not applicable for AI method
                        'red_percentage': round(red_percentage, 2),
                        'error_threshold': 8.0,
                        'extracted_text': extracted_text,
                        'detected_language': detected_language,
                        'image_size': f"{width}x{height}",  # AI analyzes full image
                        'confidence': confidence,
                        'ai_powered': True  # Flag to indicate AI analysis
                    }
                    
                    results.append(result)
                    
                    if has_subtitles and extracted_text:
                        text_preview = extracted_text[:50] + "..." if len(extracted_text) > 50 else extracted_text
                        print(f"VideoAI[{self.device_name}]: AI Subtitle analysis - subtitles=True, errors={has_errors}, text='{text_preview}', confidence={confidence}")
                        # Early break if subtitles found
                        print(f"VideoAI[{self.device_name}]: ✅ Subtitles found in image {i+1}/{max_attempts} - breaking early!")
                        break
                    else:
                        print(f"VideoAI[{self.device_name}]: AI Subtitle analysis - No subtitles detected, errors={has_errors}, confidence={confidence}")
                    
                except Exception as e:
                    results.append({
                        'image_path': image_path,
                        'success': False,
                        'error': f'AI analysis error: {str(e)}'
                    })
            
            # Calculate overall result (same logic as OCR method)
            successful_analyses = [r for r in results if r.get('success')]
            failed_analyses = [r for r in results if not r.get('success')]
            subtitles_detected = any(r.get('has_subtitles', False) for r in successful_analyses)
            errors_detected = any(r.get('has_errors', False) for r in successful_analyses)
            
            # Combine all extracted text and find the most confident language detection
            all_extracted_text = " ".join([r.get('extracted_text', '') for r in successful_analyses if r.get('extracted_text')])
            
            # Get the language and image from analyzed results
            detected_language = 'unknown'
            analyzed_image_path = None
            
            # Always store first analyzed image (for debugging when subtitles not found)
            if successful_analyses:
                analyzed_image_path = successful_analyses[0].get('image_path')
            
            # Find best language detection from results with subtitles
            for result in successful_analyses:
                if result.get('has_subtitles') and result.get('detected_language') != 'unknown':
                    detected_language = result.get('detected_language')
                    break
            
            # Aggregate analysis errors (e.g. AI/API failures) so the caller can tell
            # "AI couldn't run" apart from "AI ran and found no subtitles".
            analysis_error = None
            if not successful_analyses and failed_analyses:
                analysis_error = failed_analyses[0].get('error', 'AI subtitle analysis failed')

            # Add clear detection status message
            if analysis_error:
                detection_message = f"Subtitle analysis could not run: {analysis_error}"
            elif subtitles_detected and all_extracted_text.strip():
                detection_message = f"Subtitles detected with text: '{all_extracted_text.strip()[:100]}{'...' if len(all_extracted_text.strip()) > 100 else ''}'"
            elif subtitles_detected:
                detection_message = "Subtitles detected but no text extracted"
            else:
                detection_message = "No subtitles detected in any analyzed images"
            
            overall_result = {
                'success': len(successful_analyses) > 0,
                'subtitles_detected': subtitles_detected,
                'errors_detected': errors_detected,
                'analyzed_images': len(results),
                'successful_analyses': len(successful_analyses),
                'combined_extracted_text': all_extracted_text.strip(),
                'detected_language': detected_language,
                'image_path': analyzed_image_path,  # Add image path for report thumbnail
                'detection_message': detection_message,
                'results': results,
                'analysis_type': 'ai_subtitle_detection',
                'timestamp': datetime.now().isoformat()
            }
            if analysis_error:
                overall_result['error'] = analysis_error

            return overall_result
            
        except Exception as e:
            print(f"VideoAI[{self.device_name}]: AI subtitle detection error: {e}")
            return {
                'success': False,
                'error': f'AI subtitle detection failed: {str(e)}',
                'analysis_type': 'ai_subtitle_detection'
            }

    def detect_subtitles_ai_all_frames(self, image_paths: List[str], extract_text: bool = True) -> Dict[str, Any]:
        """
        AI-powered subtitle detection for ALL frames (restart video analysis).
        Unlike detect_subtitles_ai_batch, this processes every frame without early termination.
        
        Args:
            image_paths: List of image paths to analyze
            extract_text: Whether to extract text using AI (always True for AI method)
            
        Returns:
            Dictionary with detailed AI subtitle analysis results for all frames
        """
        try:
            results = []
            
            print(f"VideoAI[{self.device_name}]: Analyzing subtitles with AI in ALL {len(image_paths)} frames")
            
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
                    
                    height, width = img.shape[:2]
                    
                    # Use AI to analyze the full image for subtitles
                    print(f"VideoAI[{self.device_name}]: Analyzing frame {i+1}/{len(image_paths)} with full image")
                    extracted_text, detected_language, ai_confidence = self.analyze_subtitle_with_ai(img)
                    
                    has_subtitles = bool(extracted_text and extracted_text.strip())
                    
                    # Quick error detection using red pixel analysis (same as batch method)
                    sampled_img = img[::4, ::4]  # Sample every 4th pixel for speed
                    sampled_hsv = cv2.cvtColor(sampled_img, cv2.COLOR_BGR2HSV)
                    
                    # Red color ranges in HSV
                    lower_red1 = np.array([0, 50, 50])
                    upper_red1 = np.array([10, 255, 255])
                    lower_red2 = np.array([170, 50, 50])
                    upper_red2 = np.array([180, 255, 255])
                    
                    mask1 = cv2.inRange(sampled_hsv, lower_red1, upper_red1)
                    mask2 = cv2.inRange(sampled_hsv, lower_red2, upper_red2)
                    red_mask = mask1 + mask2
                    
                    red_pixels = np.sum(red_mask > 0)
                    total_sampled_pixels = sampled_hsv.shape[0] * sampled_hsv.shape[1]
                    red_percentage = float((red_pixels / total_sampled_pixels) * 100)
                    
                    # Higher threshold for error detection
                    has_errors = bool(red_percentage > 8.0)
                    
                    # Use AI confidence or set default
                    confidence = ai_confidence if has_subtitles else 0.1
                    
                    result = {
                        'image_path': os.path.basename(image_path),
                        'success': True,
                        'has_subtitles': has_subtitles,
                        'has_errors': has_errors,
                        'subtitle_edges': 0,  # Not applicable for AI method
                        'subtitle_threshold': 0.0,  # Not applicable for AI method
                        'red_percentage': round(red_percentage, 2),
                        'error_threshold': 8.0,
                        'extracted_text': extracted_text,
                        'detected_language': detected_language,
                        'image_size': f"{width}x{height}",  # AI analyzes full image
                        'confidence': confidence,
                        'ai_powered': True,  # Flag to indicate AI analysis
                        'frame_index': i
                    }
                    
                    results.append(result)
                    
                    if has_subtitles and extracted_text:
                        text_preview = extracted_text[:50] + "..." if len(extracted_text) > 50 else extracted_text
                        print(f"VideoAI[{self.device_name}]: Frame {i+1}/{len(image_paths)} - subtitles=True, errors={has_errors}, text='{text_preview}', confidence={confidence}")
                    else:
                        print(f"VideoAI[{self.device_name}]: Frame {i+1}/{len(image_paths)} - No subtitles detected, errors={has_errors}, confidence={confidence}")
                    
                    # NO EARLY BREAK - process all frames
                    
                except Exception as e:
                    results.append({
                        'image_path': image_path,
                        'success': False,
                        'error': f'AI analysis error: {str(e)}',
                        'frame_index': i
                    })
            
            # Calculate overall result
            successful_analyses = [r for r in results if r.get('success')]
            failed_analyses = [r for r in results if not r.get('success')]
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
            
            # Surface analysis failures (e.g. AI/API errors) instead of masking them
            # as "no subtitles detected".
            analysis_error = None
            if not successful_analyses and failed_analyses:
                analysis_error = failed_analyses[0].get('error', 'AI subtitle analysis failed')

            overall_result = {
                'success': len(successful_analyses) > 0,
                'subtitles_detected': subtitles_detected,
                'errors_detected': errors_detected,
                'analyzed_images': len(results),
                'successful_analyses': len(successful_analyses),
                'extracted_text': all_extracted_text.strip(),
                'detected_language': detected_language,
                'confidence': max_confidence,
                'results': results,
                'detection_message': (f"Subtitle analysis could not run: {analysis_error}" if analysis_error else None),
                'analysis_type': 'ai_subtitle_detection_all_frames',
                'timestamp': datetime.now().isoformat()
            }
            if analysis_error:
                overall_result['error'] = analysis_error

            print(f"VideoAI[{self.device_name}]: All-frame AI subtitle analysis complete - {len(successful_analyses)}/{len(image_paths)} frames analyzed, subtitles_detected={subtitles_detected}")
            
            return overall_result
            
        except Exception as e:
            print(f"VideoAI[{self.device_name}]: AI all-frames subtitle detection error: {e}")
            return {
                'success': False,
                'error': f'AI all-frames subtitle detection failed: {str(e)}',
                'analysis_type': 'ai_subtitle_detection_all_frames'
            }

    # =============================================================================
    # Full Image Analysis with AI
    # =============================================================================
    
    def analyze_full_image_with_ai(self, image_path: str, user_question: str) -> str:
        """
        Quickly analyze full image with AI using user's question.
        
        Args:
            image_path: Path to image file
            user_question: User's question about the image
            
        Returns:
            AI's text response (max 3 lines) or empty string if failed
        """
        try:
            print(f"VideoAI[{self.device_name}]: AI image analysis - Question: '{user_question}'")
            
            # Check if image exists
            if not os.path.exists(image_path):
                print(f"VideoAI[{self.device_name}]: Image file not found: {image_path}")
                return "Image file not found."
            
            # Get device model context from AV controller
            device_model = "unknown device"
            device_context = "a device screen"
            
            if hasattr(self.av_controller, 'device_model') and self.av_controller.device_model:
                device_model = self.av_controller.device_model
                
                # Provide helpful context based on device model
                model_lower = device_model.lower()
                if "mobile" in model_lower or "phone" in model_lower:
                    device_context = "an Android mobile phone screen"
                elif "fire" in model_lower or "tv" in model_lower:
                    device_context = "a Fire TV/Android TV screen"
                elif "tablet" in model_lower:
                    device_context = "a tablet screen"
                else:
                    device_context = f"a {device_model} device screen"
            
            # Enhanced prompt with device model and context
            prompt = f"""You are analyzing a screenshot from {device_context} (device model: {device_model}).

This image was captured from a controlled device during automated testing/monitoring.

User question: "{user_question}"

Provide a clear, concise answer in maximum 3 lines.
Be specific about what you see on the device interface."""
            
            # Use centralized AI service
            from shared.src.lib.utils.ai_utils import call_vision_ai
            
            result = call_vision_ai(prompt, image_path, max_tokens=200, temperature=0.0)
            
            if result['success']:
                ai_response = result['content'].strip()
                
                # Limit to 3 lines maximum
                lines = ai_response.split('\n')
                if len(lines) > 3:
                    ai_response = '\n'.join(lines[:3])
                
                print(f"VideoAI[{self.device_name}]: AI response: '{ai_response}'")
                return ai_response
            else:
                error_msg = result.get('error', 'Unknown error')
                print(f"VideoAI[{self.device_name}]: AI service error: {error_msg}")
                return "AI service error. Please try again."
                
        except Exception as e:
            print(f"VideoAI[{self.device_name}]: AI image analysis error: {e}")
            return "Analysis error. Please try again."

    def analyze_image_ai_wrapper(self, image_path: str, user_query: str) -> Dict[str, Any]:
        """
        Wrapper method for analyze_full_image_with_ai to match route expectations.
        
        Args:
            image_path: Path to image file
            user_query: User's question about the image
            
        Returns:
            Dictionary with success status and AI response
        """
        try:
            response_text = self.analyze_full_image_with_ai(image_path, user_query)
            clean_response = (response_text or '').strip()
            is_error_text = clean_response.lower() in {
                'image file not found.',
                'ai service error. please try again.',
                'analysis error. please try again.',
            }
            
            return {
                'success': bool(clean_response) and not is_error_text,
                'response': response_text,
                'image_path': os.path.basename(image_path) if image_path else None
            }
        except Exception as e:
            print(f"VideoAI[{self.device_name}]: analyze_image_ai wrapper error: {e}")
            return {
                'success': False,
                'response': "Analysis error. Please try again.",
                'error': str(e)
            }

    def analyze_image_complete(self, image_path: str, extract_text: bool = True, include_description: bool = True) -> Dict[str, Any]:
        """
        Combined AI analysis: subtitles + description in single AI call.
        
        Args:
            image_path: Path to image file
            extract_text: Whether to extract subtitle text
            include_description: Whether to include image description
            
        Returns:
            Dictionary with both subtitle and description analysis
        """
        try:
            print(f"VideoAI[{self.device_name}]: Combined single-call analysis for: {image_path}")
            
            # Use centralized AI utilities for single combined call
            from shared.src.lib.utils.ai_utils import call_vision_ai
            
            # Single combined prompt for both subtitles and description
            prompt = """Quickly analyze this image and provide both subtitle detection and description. Respond with JSON:
{
  "subtitle_analysis": {
    "subtitles_detected": true/false,
    "extracted_text": "subtitle text or empty string",
    "detected_language": "language name or unknown",
    "confidence": 0.0-1.0
  },
  "description_analysis": {
    "success": true,
    "response": "fast and concise description of what you see in this image"
  }
}"""
            
            print(f"VideoAI[{self.device_name}]: Single AI call with combined prompt")
            result = call_vision_ai(prompt, image_path, max_tokens=400, temperature=0.0)
            
            if result['success']:
                try:
                    import json
                    # Parse AI response
                    content = result['content'].strip()
                    
                    # Handle markdown code blocks
                    if content.startswith('```json'):
                        content = content.replace('```json', '').replace('```', '').strip()
                    elif content.startswith('```'):
                        content = content.replace('```', '').strip()
                    
                    # Check if JSON is complete (basic validation)
                    if not content.strip().endswith('}'):
                        print(f"VideoAI[{self.device_name}]: JSON appears truncated, attempting to fix...")
                        # Try to close incomplete JSON
                        open_braces = content.count('{') - content.count('}')
                        if open_braces > 0:
                            content += '}' * open_braces
                    
                    ai_data = json.loads(content)
                    
                    # Extract and validate subtitle analysis
                    subtitle_analysis = ai_data.get('subtitle_analysis', {})
                    subtitle_result = {
                        'subtitles_detected': bool(subtitle_analysis.get('subtitles_detected', False)),
                        'combined_extracted_text': subtitle_analysis.get('extracted_text', ''),
                        'detected_language': subtitle_analysis.get('detected_language', 'unknown'),
                        'confidence': float(subtitle_analysis.get('confidence', 0.1)),
                        'detection_message': f"Subtitles {'found' if subtitle_analysis.get('subtitles_detected') else 'not found'}"
                    }
                    
                    # Extract and validate description analysis
                    description_analysis = ai_data.get('description_analysis', {})
                    description_result = {
                        'success': bool(description_analysis.get('success', True)),
                        'response': description_analysis.get('response', 'No description available')
                    }
                    
                    # Log results
                    if subtitle_result['subtitles_detected']:
                        text_preview = subtitle_result['combined_extracted_text'][:50] + "..." if len(subtitle_result['combined_extracted_text']) > 50 else subtitle_result['combined_extracted_text']
                        print(f"VideoAI[{self.device_name}]: Combined AI extracted subtitle: '{text_preview}' -> Language: {subtitle_result['detected_language']}, Confidence: {subtitle_result['confidence']}")
                    
                    print(f"VideoAI[{self.device_name}]: Combined AI description: '{description_result['response'][:50]}{'...' if len(description_result['response']) > 50 else ''}'")
                    
                    response = {
                        'success': True,
                        'subtitle_analysis': subtitle_result,
                        'description_analysis': description_result
                    }
                    
                    print(f"VideoAI[{self.device_name}]: Combined single-call analysis complete - subtitles: {subtitle_result['subtitles_detected']}")
                    return response
                    
                except (json.JSONDecodeError, KeyError, ValueError) as e:
                    print(f"VideoAI[{self.device_name}]: Failed to parse combined AI response: {e}")
                    print(f"VideoAI[{self.device_name}]: Raw AI content: {result['content']}")
                    
                    # Fallback to empty results
                    return {
                        'success': False,
                        'subtitle_analysis': {
                            'subtitles_detected': False,
                            'combined_extracted_text': '',
                            'detected_language': 'unknown',
                            'confidence': 0.0,
                            'detection_message': 'AI parsing failed'
                        },
                        'description_analysis': {
                            'success': False,
                            'response': 'Description analysis failed'
                        },
                        'error': f'JSON parsing error: {str(e)}'
                    }
            else:
                print(f"VideoAI[{self.device_name}]: Combined AI call failed: {result.get('error', 'Unknown error')}")
                return {
                    'success': False,
                    'subtitle_analysis': {
                        'subtitles_detected': False,
                        'combined_extracted_text': '',
                        'detected_language': 'unknown',
                        'confidence': 0.0,
                        'detection_message': 'AI call failed'
                    },
                    'description_analysis': {
                        'success': False,
                        'response': 'AI call failed'
                    },
                    'error': result.get('error', 'AI call failed')
                }
            
        except Exception as e:
            print(f"VideoAI[{self.device_name}]: Combined analysis error: {e}")
            return {
                'success': False,
                'error': str(e),
                'subtitle_analysis': None,
                'description_analysis': None
            }

    def analyze_image_batch_complete(self, image_paths: list, extract_text: bool = True, include_description: bool = True) -> Dict[str, Any]:
        """
        Batch AI analysis: subtitles + description for multiple images in single call.
        
        Args:
            image_paths: List of paths to image files (max 4)
            extract_text: Whether to extract subtitle text
            include_description: Whether to include image description
            
        Returns:
            Dictionary with batch analysis results
        """
        try:
            print(f"VideoAI[{self.device_name}]: Batch analysis for {len(image_paths)} images")
            
            # Use global batch config
            from shared.src.lib.utils.ai_utils import AI_BATCH_CONFIG
            max_batch_size = AI_BATCH_CONFIG['max_batch_size']
            
            if len(image_paths) > max_batch_size:
                print(f"VideoAI[{self.device_name}]: Too many images in batch ({len(image_paths)}), max is {max_batch_size}")
                return {'success': False, 'error': f'Maximum {max_batch_size} images per batch'}
            
            # Use centralized batch AI utilities
            from shared.src.lib.utils.ai_utils import call_vision_ai_batch
            
            # Batch prompt for multiple images
            prompt = f"""Analyze these {len(image_paths)} images and provide both subtitle detection and description for each. 
Respond with JSON array where each element corresponds to one image:
[
  {{
    "image_index": 1,
    "subtitle_analysis": {{
      "subtitles_detected": true/false,
      "extracted_text": "subtitle text or empty string",
      "detected_language": "language name or unknown",
      "confidence": 0.0-1.0
    }},
    "description_analysis": {{
      "success": true,
      "response": "concise description of what you see in this image"
    }}
  }},
  ... (repeat for each image)
]"""
            
            print(f"VideoAI[{self.device_name}]: Batch AI call for {len(image_paths)} images")
            result = call_vision_ai_batch(prompt, image_paths)
            
            if result['success']:
                try:
                    import json
                    # Parse AI response
                    content = result['content'].strip()
                    
                    # Handle markdown code blocks
                    if content.startswith('```json'):
                        content = content.replace('```json', '').replace('```', '').strip()
                    elif content.startswith('```'):
                        content = content.replace('```', '').strip()
                    
                    ai_data = json.loads(content)
                    
                    # Process each frame result
                    frame_results = []
                    for i, frame_data in enumerate(ai_data):
                        if isinstance(frame_data, dict):
                            # Extract and validate subtitle analysis
                            subtitle_analysis = frame_data.get('subtitle_analysis', {})
                            subtitle_result = {
                                'subtitles_detected': bool(subtitle_analysis.get('subtitles_detected', False)),
                                'combined_extracted_text': subtitle_analysis.get('extracted_text', ''),
                                'detected_language': subtitle_analysis.get('detected_language', 'unknown'),
                                'confidence': float(subtitle_analysis.get('confidence', 0.1)),
                                'detection_message': f"Subtitles {'found' if subtitle_analysis.get('subtitles_detected') else 'not found'}"
                            }
                            
                            # Extract and validate description analysis
                            description_analysis = frame_data.get('description_analysis', {})
                            description_result = {
                                'success': bool(description_analysis.get('success', True)),
                                'response': description_analysis.get('response', 'No description available')
                            }
                            
                            frame_results.append({
                                'success': True,
                                'subtitle_analysis': subtitle_result,
                                'description_analysis': description_result
                            })
                            
                            # Log results for this frame
                            if subtitle_result['subtitles_detected']:
                                text_preview = subtitle_result['combined_extracted_text'][:50] + "..." if len(subtitle_result['combined_extracted_text']) > 50 else subtitle_result['combined_extracted_text']
                                print(f"VideoAI[{self.device_name}]: Frame {i+1} subtitle: '{text_preview}' -> Language: {subtitle_result['detected_language']}")
                            
                            print(f"VideoAI[{self.device_name}]: Frame {i+1} description: '{description_result['response'][:50]}{'...' if len(description_result['response']) > 50 else ''}'")
                        else:
                            # Fallback for malformed frame data
                            frame_results.append({
                                'success': False,
                                'subtitle_analysis': {
                                    'subtitles_detected': False,
                                    'combined_extracted_text': '',
                                    'detected_language': 'unknown',
                                    'confidence': 0.0,
                                    'detection_message': 'Parsing failed'
                                },
                                'description_analysis': {
                                    'success': False,
                                    'response': 'Description analysis failed'
                                }
                            })
                    
                    print(f"VideoAI[{self.device_name}]: Batch analysis complete - processed {len(frame_results)} frames")
                    return {
                        'success': True,
                        'frame_results': frame_results
                    }
                    
                except (json.JSONDecodeError, KeyError, ValueError) as e:
                    print(f"VideoAI[{self.device_name}]: Failed to parse batch AI response: {e}")
                    print(f"VideoAI[{self.device_name}]: Raw AI content: {result['content']}")
                    
                    # Fallback to empty results for all frames
                    frame_results = []
                    for i in range(len(image_paths)):
                        frame_results.append({
                            'success': False,
                            'subtitle_analysis': {
                                'subtitles_detected': False,
                                'combined_extracted_text': '',
                                'detected_language': 'unknown',
                                'confidence': 0.0,
                                'detection_message': 'AI parsing failed'
                            },
                            'description_analysis': {
                                'success': False,
                                'response': 'Description analysis failed'
                            }
                        })
                    
                    return {
                        'success': False,
                        'frame_results': frame_results,
                        'error': f'JSON parsing error: {str(e)}'
                    }
            else:
                print(f"VideoAI[{self.device_name}]: Batch AI call failed: {result.get('error', 'Unknown error')}")
                
                # Fallback to empty results for all frames
                frame_results = []
                for i in range(len(image_paths)):
                    frame_results.append({
                        'success': False,
                        'subtitle_analysis': {
                            'subtitles_detected': False,
                            'combined_extracted_text': '',
                            'detected_language': 'unknown',
                            'confidence': 0.0,
                            'detection_message': 'AI call failed'
                        },
                        'description_analysis': {
                            'success': False,
                            'response': 'AI call failed'
                        }
                    })
                
                return {
                    'success': False,
                    'frame_results': frame_results,
                    'error': result.get('error', 'AI call failed')
                }
            
        except Exception as e:
            print(f"VideoAI[{self.device_name}]: Batch analysis error: {e}")
            return {
                'success': False,
                'error': str(e),
                'frame_results': []
            }

    # =============================================================================
    # Language/Subtitle Menu Analysis
    # =============================================================================
    
    def analyze_language_menu_ai(self, image_path: str) -> Dict[str, Any]:
        """
        AI-powered language/subtitle menu analysis using centralized AI utilities.
        
        Args:
            image_path: Path to image file showing a language/subtitle menu
            
        Returns:
            Dictionary with language and subtitle options analysis
        """
        try:
            print(f"VideoAI[{self.device_name}]: AI language menu analysis")
            
            # Check if image exists
            if not os.path.exists(image_path):
                print(f"VideoAI[{self.device_name}]: Image file not found: {image_path}")
                return {'success': False, 'error': 'Image file not found'}
            
            # Use centralized AI utilities
            from shared.src.lib.utils.ai_utils import analyze_language_menu_ai
            
            result = analyze_language_menu_ai(image_path, context_name=f"VideoAI[{self.device_name}]")
            
            if result['success']:
                # Enhanced logging for debugging
                menu_detected = result.get('menu_detected', False)
                audio_languages = result.get('audio_languages', [])
                subtitle_languages = result.get('subtitle_languages', [])
                selected_audio = result.get('selected_audio', -1)
                selected_subtitle = result.get('selected_subtitle', -1)
                
                print(f"VideoAI[{self.device_name}]: Menu detected: {menu_detected}")
                print(f"VideoAI[{self.device_name}]: Audio languages: {audio_languages}")
                print(f"VideoAI[{self.device_name}]: Subtitle languages: {subtitle_languages}")
                print(f"VideoAI[{self.device_name}]: Selected audio: {selected_audio}")
                print(f"VideoAI[{self.device_name}]: Selected subtitle: {selected_subtitle}")
                
                return {
                    'success': True,
                    'menu_detected': menu_detected,
                    'audio_languages': audio_languages,
                    'subtitle_languages': subtitle_languages,
                    'selected_audio': selected_audio,
                    'selected_subtitle': selected_subtitle,
                    'image_path': os.path.basename(image_path),
                    'analysis_type': 'ai_language_menu_analysis'
                }
            else:
                print(f"VideoAI[{self.device_name}]: Language menu analysis failed: {result.get('error', 'Unknown error')}")
                return {
                    'success': False,
                    'error': result.get('error', 'Language menu analysis failed'),
                    'raw_response': result.get('raw_response', ''),
                    'error_type': result.get('error_type', 'unknown')
                }
                
        except Exception as e:
            print(f"VideoAI[{self.device_name}]: AI language menu analysis error: {e}")
            return {
                'success': False,
                'error': f'Analysis error: {str(e)}'
            }

    # =============================================================================
    # Natural Language Response Parsing
    # =============================================================================
    
    def parse_natural_language_response(self, content: str) -> Tuple[str, str, float]:
        """
        Parse natural language AI response to extract subtitle information.
        
        Args:
            content: Raw AI response content
            
        Returns:
            Tuple of (extracted_text, detected_language, confidence)
        """
        try:
            content_lower = content.lower()
            
            # Check if subtitles were mentioned as present
            subtitle_indicators = ['subtitle', 'text reads', 'says', 'displays', 'shows']
            has_subtitle_mention = any(indicator in content_lower for indicator in subtitle_indicators)
            
            if not has_subtitle_mention:
                return '', 'unknown', 0.0
            
            # Extract text between quotes
            # Look for text in quotes (various quote types)
            quote_patterns = [
                r'"([^"]+)"',           # Double quotes
                r"'([^']+)'",           # Single quotes  
                r'"([^"]+)"',           # Curly quotes
                r'„([^"]+)"',           # German quotes
                r'«([^»]+)»',           # French quotes
            ]
            
            extracted_text = ''
            for pattern in quote_patterns:
                matches = re.findall(pattern, content)
                if matches:
                    # Take the longest match (likely the subtitle text)
                    extracted_text = max(matches, key=len).strip()
                    break
            
            # If no quotes found, try to extract after "reads:" or "says:"
            if not extracted_text:
                read_patterns = [
                    r'text reads:?\s*(.+?)(?:\.|$)',
                    r'says:?\s*(.+?)(?:\.|$)', 
                    r'displays:?\s*(.+?)(?:\.|$)',
                    r'shows:?\s*(.+?)(?:\.|$)'
                ]
                
                for pattern in read_patterns:
                    matches = re.findall(pattern, content, re.IGNORECASE)
                    if matches:
                        extracted_text = matches[0].strip()
                        # Remove quotes if they exist
                        extracted_text = re.sub(r'^["\'"„«]|["\'"„»]$', '', extracted_text)
                        break
            
            # Clean up the extracted text
            if extracted_text:
                # Remove common OCR artifacts and clean the text
                extracted_text = re.sub(r'\s+', ' ', extracted_text).strip()
                
                # Validate the text (should be at least 3 characters)
                if len(extracted_text) < 3:
                    return '', 'unknown', 0.0
            
            # Detect language from the response content
            detected_language = 'unknown'
            language_mentions = {
                'german': 'German',
                'deutsch': 'German', 
                'english': 'English',
                'french': 'French',
                'français': 'French',
                'spanish': 'Spanish',
                'español': 'Spanish',
                'italian': 'Italian',
                'italiano': 'Italian',
                'portuguese': 'Portuguese',
                'português': 'Portuguese',
                'dutch': 'Dutch',
                'nederlands': 'Dutch'
            }
            
            for lang_key, lang_name in language_mentions.items():
                if lang_key in content_lower:
                    detected_language = lang_name
                    break
            
            # If we found text, try to detect language from the text itself using fallback
            if extracted_text and detected_language == 'unknown' and LANG_DETECT_AVAILABLE:
                try:
                    detected_lang = detect(extracted_text)
                    allowed_languages = {
                        'en': 'English', 'fr': 'French', 'de': 'German',
                        'it': 'Italian', 'es': 'Spanish', 'pt': 'Portuguese', 'nl': 'Dutch'
                    }
                    detected_language = allowed_languages.get(detected_lang, 'unknown')
                except:
                    pass  # Keep as unknown
            
            # Set confidence based on what we found
            if extracted_text and detected_language != 'unknown':
                confidence = 0.8  # High confidence when we have both text and language
            elif extracted_text:
                confidence = 0.6  # Medium confidence when we have text but no language
            else:
                confidence = 0.1  # Low confidence
            
            return extracted_text, detected_language, confidence
            
        except Exception as e:
            print(f"VideoAI[{self.device_name}]: Natural language parsing error: {e}")
            return '', 'unknown', 0.0

    # =============================================================================
    # Channel Banner Analysis
    # =============================================================================
    
    def _analyze_banner_with_image(self, img, banner_region: Dict[str, int] = None, analysis_type: str = "image") -> Dict[str, Any]:
        """
        Helper method to analyze banner with a given image (cropped or full).
        
        Args:
            img: OpenCV image (BGR format)
            banner_region: Original banner region for metadata
            analysis_type: Description of analysis type for logging
            
        Returns:
            Dictionary with channel banner analysis results
        """
        try:
            # Save processed image to temporary file for encoding
            with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as tmp_file:
                cv2.imwrite(tmp_file.name, img)
                temp_path = tmp_file.name
            
            try:
                # Create specialized prompt for banner analysis
                prompt = self._create_banner_analysis_prompt()
                
                # Use centralized AI service
                from shared.src.lib.utils.ai_utils import call_vision_ai
                
                result = call_vision_ai(prompt, temp_path, max_tokens=400, temperature=0.0)
                
                print(f"VideoAI[{self.device_name}]: AI call result: success={result['success']}, provider={result.get('provider_used', 'unknown')} ({analysis_type})")
                
                if result['success']:
                    content = result['content'].strip()
                    print(f"VideoAI[{self.device_name}]: Raw content length: {len(content)} ({analysis_type})")
                    print(f"VideoAI[{self.device_name}]: Raw content preview: {repr(content[:200])}")
                    
                    # Parse JSON response
                    try:
                        if not content:
                            print(f"VideoAI[{self.device_name}]: ERROR - Empty content from AI ({analysis_type})")
                            return {
                                'success': False,
                                'error': 'Empty content from AI service',
                                'raw_content': content
                            }
                        
                        # Remove markdown code block markers
                        json_content = content.replace('```json', '').replace('```', '').strip()
                        
                        ai_result = json.loads(json_content)
                        print(f"VideoAI[{self.device_name}]: Successfully parsed AI JSON: {list(ai_result.keys())} ({analysis_type})")
                        
                        # Validate and normalize the result
                        banner_detected = ai_result.get('banner_detected', False)
                        channel_name = ai_result.get('channel_name', '')
                        channel_number = ai_result.get('channel_number', '')
                        program_name = ai_result.get('program_name', '')
                        start_time = ai_result.get('start_time', '')
                        end_time = ai_result.get('end_time', '')
                        confidence = float(ai_result.get('confidence', 0.0))
                        
                        # Enhanced logging for debugging
                        print(f"VideoAI[{self.device_name}]: Banner detected: {banner_detected} ({analysis_type})")
                        print(f"VideoAI[{self.device_name}]: Channel name: {channel_name}")
                        print(f"VideoAI[{self.device_name}]: Channel number: {channel_number}")
                        print(f"VideoAI[{self.device_name}]: Program name: {program_name}")
                        print(f"VideoAI[{self.device_name}]: Start time: {start_time}")
                        print(f"VideoAI[{self.device_name}]: End time: {end_time}")
                        print(f"VideoAI[{self.device_name}]: Confidence: {confidence}")
                        
                        # Return standardized result
                        return {
                            'success': True,
                            'banner_detected': banner_detected,
                            'channel_info': {
                                'channel_name': channel_name,
                                'channel_number': channel_number,
                                'program_name': program_name,
                                'start_time': start_time,
                                'end_time': end_time
                            },
                            'confidence': confidence,
                            'banner_region': banner_region,
                            'analysis_type': f'ai_channel_banner_analysis_{analysis_type.replace(" ", "_")}',
                            'image_path': None  # Will be set by calling method
                        }
                        
                    except json.JSONDecodeError as e:
                        print(f"VideoAI[{self.device_name}]: JSON parsing error: {e} ({analysis_type})")
                        print(f"VideoAI[{self.device_name}]: Raw AI response: {repr(content)}")
                        return {
                            'success': False,
                            'error': 'Invalid AI response format',
                            'raw_response': content,
                            'json_error': str(e)
                        }
                else:
                    error_msg = result.get('error', 'Unknown error')
                    provider_used = result.get('provider_used', 'none')
                    print(f"VideoAI[{self.device_name}]: AI service error with {provider_used}: {error_msg} ({analysis_type})")
                    return {
                        'success': False,
                        'error': f'AI service error: {error_msg}',
                        'provider_used': provider_used
                    }
                    
            finally:
                # Clean up temporary file
                if os.path.exists(temp_path):
                    os.unlink(temp_path)
                    
        except Exception as e:
            print(f"VideoAI[{self.device_name}]: Banner analysis helper error: {e} ({analysis_type})")
            return {
                'success': False,
                'error': f'Analysis error: {str(e)}'
            }

    def analyze_channel_banner_ai(self, image_path: str, banner_region: Dict[str, int] = None) -> Dict[str, Any]:
        """
        AI-powered channel banner analysis using OpenRouter - Full image only.
        
        Args:
            image_path: Path to image file containing the banner
            banner_region: Region where banner appears (kept for compatibility but not used for cropping)
                          Format: {'x': int, 'y': int, 'width': int, 'height': int}
            
        Returns:
            Dictionary with channel banner analysis results
        """
        try:
            print(f"VideoAI[{self.device_name}]: AI channel banner analysis (full image only)")
            print(f"VideoAI[{self.device_name}]: Testing image: {image_path}")
            print(f"VideoAI[{self.device_name}]: Banner region: {banner_region}")
            
            # Check if image exists
            if not os.path.exists(image_path):
                print(f"VideoAI[{self.device_name}]: Image file not found: {image_path}")
                return {'success': False, 'error': 'Image file not found'}
            
            # Load and process the image
            try:
                img = cv2.imread(image_path)
                if img is None:
                    return {'success': False, 'error': 'Could not load image'}
                
                # Use full image analysis only - no cropping to avoid OpenCV errors
                print(f"VideoAI[{self.device_name}]: Analyzing full image for banner detection")
                analysis_result = self._analyze_banner_with_image(img, banner_region, "full image")
                
                # Set image path in the final result
                if analysis_result and analysis_result.get('success', False):
                    analysis_result['image_path'] = os.path.basename(image_path)
                
                return analysis_result
                        
            except Exception as e:
                print(f"VideoAI[{self.device_name}]: Image processing error: {e}")
                return {
                    'success': False,
                    'error': 'Failed to process image'
                }
                
        except Exception as e:
            print(f"VideoAI[{self.device_name}]: AI channel banner analysis error: {e}")
            return {
                'success': False,
                'error': f'Analysis error: {str(e)}'
            }

    def _create_banner_analysis_prompt(self) -> str:
        """
        Create specialized prompt for channel banner analysis optimized for full image analysis.
        
        Returns:
            Formatted prompt string for AI analysis
        """
        return """Analyze this full TV screen image for channel information banner/overlay. Look for channel names, program information, and time details anywhere in the image.

CRITICAL INSTRUCTIONS:
1. You MUST ALWAYS respond with valid JSON - never return empty content
2. If you find a channel banner, extract the information
3. If you find NO banner, you MUST still respond with the "banner_detected": false JSON format below
4. ALWAYS provide a response - never return empty or null content

Required JSON format:
{
  "banner_detected": true,
  "channel_name": "BBC One",
  "channel_number": "1",
  "program_name": "News at Six",
  "start_time": "18:00",
  "end_time": "18:30",
  "confidence": 0.95
}

If no channel banner found:
{
  "banner_detected": false,
  "channel_name": "",
  "channel_number": "",
  "program_name": "",
  "start_time": "",
  "end_time": "",
  "confidence": 0.1
}

FULL IMAGE ANALYSIS RULES:
- Scan the ENTIRE image for channel information
- Look for channel logos, channel names (BBC One, ITV, Channel 4, SRF, etc.)
- Extract channel numbers (1, 2, 3, 101, 201, etc.) from banners or overlays
- IMPORTANT: Channel numbers are typically located to the LEFT of the channel name
- Extract program/show names (News, EastEnders, Music@SRF, etc.)
- Find time information (start time, end time, duration) anywhere on screen
- Look for text overlays, banners, or information bars in ANY location
- Check ALL corners and edges of the image for channel info
- Pay attention to typical TV UI elements (channel number, program guide info)
- Look for semi-transparent overlays that may appear anywhere
- Extract exact times in HH:MM format when visible
- Set confidence based on clarity and completeness of information found
- If only partial information is visible, include what you can extract
- Look for "Now" or "Next" program information
- Check for EPG (Electronic Program Guide) style overlays
- Examine the bottom area of the screen where banners commonly appear
- Also check top areas and side areas for channel branding

IMPORTANT: Even if the image has no channel banner, you MUST respond with the "banner_detected": false JSON format above. Never return empty content.

JSON ONLY - NO OTHER TEXT - ALWAYS RESPOND"""

    def detect_banner_presence(self, image_path: str, banner_region: Dict[str, int] = None) -> bool:
        """
        Quick detection to check if a banner is visually present before calling expensive AI analysis.
        Uses full image analysis only to avoid OpenCV cropping errors.
        
        Args:
            image_path: Path to image file
            banner_region: Region to check for banner presence (kept for compatibility but not used for cropping)
            
        Returns:
            True if banner appears to be present, False otherwise
        """
        try:
            if not os.path.exists(image_path):
                return False
            
            img = cv2.imread(image_path)
            if img is None:
                return False
            
            # Use full image analysis only - no cropping to avoid OpenCV errors
            # Simple heuristic: check for text-like edges and non-uniform color distribution
            gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
            
            # Edge detection for text
            edges = cv2.Canny(gray, 50, 150)
            edge_density = np.sum(edges > 0) / (edges.shape[0] * edges.shape[1])
            
            # Color variance (banners usually have some color variation)
            color_variance = np.var(img)
            
            # Simple thresholds - adjust based on testing
            has_text_edges = edge_density > 0.02  # Some text-like edges
            has_color_variation = color_variance > 100  # Some color variation
            
            banner_likely = has_text_edges and has_color_variation
            
            print(f"VideoAI[{self.device_name}]: Banner presence check (full image) - edges: {edge_density:.4f}, variance: {color_variance:.1f}, likely: {banner_likely}")
            return banner_likely
            
        except Exception as e:
            print(f"VideoAI[{self.device_name}]: Banner presence detection error: {e}")
            return False  # Assume no banner if detection fails
