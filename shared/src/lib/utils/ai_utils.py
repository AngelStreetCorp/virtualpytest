"""
AI Utilities - Verification (vision/text) interface.

Thin wrapper over the centralized provider layer in ``shared.src.lib.ai``.
Provider/model/key for the "vision" and "text" tasks are resolved there from
env (AI_VISION_PROVIDER/MODEL, AI_TEXT_PROVIDER/MODEL, AI_PROVIDER) with
per-provider defaults. No provider/model is hardcoded here.

Public API (unchanged for callers): call_text_ai, call_vision_ai,
call_vision_ai_batch, analyze_language_menu_ai, analyze_channel_banner_ai.
"""

import os
import base64
import json
import logging
from datetime import datetime
from time import sleep
from typing import Dict, Any, Optional, Tuple, Union

import cv2

from shared.src.lib.ai.config import resolve_task
from shared.src.lib.ai.provider_client import complete_text, complete_vision

logger = logging.getLogger(__name__)

# Defaults that are not provider/model specific.
AI_DEFAULTS = {
    'max_tokens': 1000,
    'temperature': 0.0,
    'empty_retries': 2,   # retries when the model returns empty content
    'retry_sleep': 3,
}

AI_BATCH_CONFIG = {
    'batch_size': 4,
    'max_batch_size': 4,
    'timeout_seconds': 300,
    'max_tokens': 2000,
    'temperature': 0.0
}

# =============================================================================
# Helper Functions
# =============================================================================

def _format_timestamp(timestamp: float) -> str:
    """Convert Unix timestamp to readable HH:mm:ss format."""
    return datetime.fromtimestamp(timestamp).strftime('%H:%M:%S')

# =============================================================================
# Clean AI Interface Functions
# =============================================================================

def call_text_ai(prompt: str, max_tokens: int = 200, temperature: float = 0.1, model: str = None) -> Dict[str, Any]:
    """Single text completion via the centralized 'text' task provider."""
    return _run_completion('text', prompt, image=None, max_tokens=max_tokens, temperature=temperature, model=model)

def call_vision_ai(prompt: str, image_input: Union[str, bytes], max_tokens: int = 300, temperature: float = 0.0) -> Dict[str, Any]:
    """Single vision completion via the centralized 'vision' task provider."""
    return _run_completion('vision', prompt, image=image_input, max_tokens=max_tokens, temperature=temperature)

def _run_completion(task: str, prompt: str, image: Union[str, bytes, None] = None,
                    max_tokens: int = None, temperature: float = None, model: str = None) -> Dict[str, Any]:
    """
    Resolve the task provider/model/key (from shared.ai.config) and run a text or
    vision completion. Returns the legacy result dict:
    {success, content, error, usage, provider_used}.
    """
    max_tokens = max_tokens or AI_DEFAULTS['max_tokens']
    temperature = temperature if temperature is not None else AI_DEFAULTS['temperature']

    try:
        cfg = resolve_task(task)
    except ValueError as e:
        # No provider/model/key configured for this task (e.g. minimax has no vision model,
        # or the provider's API key is missing). Fail loudly with the real reason.
        print(f"[AI_UTILS] ❌ {task} task not configured: {e}")
        return {'success': False, 'error': str(e), 'content': '', 'provider_used': 'none'}

    provider = cfg['provider']
    resolved_model = model or cfg['model']
    print(f"[AI_UTILS] {task} call → provider={provider}, model={resolved_model}, max_tokens={max_tokens}")

    image_b64 = media_type = None
    if image is not None:
        image_b64, media_type = _image_to_b64(image)
        if not image_b64:
            return {'success': False, 'error': 'Failed to process image', 'content': '', 'provider_used': provider}

    attempts = AI_DEFAULTS['empty_retries'] + 1
    for attempt in range(attempts):
        try:
            if image_b64 is not None:
                resp = complete_vision(
                    provider=provider, api_key=cfg['api_key'], model=resolved_model,
                    prompt=prompt, image_b64=image_b64, media_type=media_type,
                    max_tokens=max_tokens, temperature=temperature,
                )
            else:
                resp = complete_text(
                    provider=provider, api_key=cfg['api_key'], model=resolved_model,
                    prompt=prompt, max_tokens=max_tokens, temperature=temperature,
                )
        except Exception as e:
            error_msg = _format_provider_error(provider, resolved_model, e)
            print(f"[AI_UTILS] ❌ {error_msg}")
            return {'success': False, 'error': f'AI call failed: {error_msg}', 'content': '', 'provider_used': provider}

        content = resp.text()
        if not content or not content.strip():
            if attempt < attempts - 1:
                print(f"[AI_UTILS] Empty content (attempt {attempt + 1}/{attempts}) - retrying")
                sleep(AI_DEFAULTS['retry_sleep'])
                continue
            return {'success': False, 'error': 'AI returned empty content', 'content': '', 'provider_used': provider}

        print(f"[AI_UTILS] ✅ {provider} call successful - content length: {len(content)}")
        return {
            'success': True,
            'content': content,
            'initial_prompt': prompt,
            'provider_used': provider,
            'usage': {
                'prompt_tokens': resp.usage.input_tokens,
                'completion_tokens': resp.usage.output_tokens,
                'total_tokens': resp.usage.input_tokens + resp.usage.output_tokens,
            },
        }

def _format_provider_error(provider: str, model: str, exc: Exception) -> str:
    """Build a clear, single-line error string from a provider exception."""
    try:
        import requests as _requests
        if isinstance(exc, _requests.HTTPError) and exc.response is not None:
            body = (exc.response.text or '')[:300]
            return f"{provider} API error (HTTP {exc.response.status_code}) for model '{model}': {body}"
    except Exception:
        pass
    return f"{provider} call failed for model '{model}': {exc}"

def call_vision_ai_batch(prompt: str, image_paths: list, max_tokens: int = None, temperature: float = None) -> Dict[str, Any]:
    """Simple batch vision AI call."""
    print(f"[AI_UTILS] Batch processing {len(image_paths)} images")
    
    # Process first image with batch context (can be enhanced for true batch processing later)
    if image_paths:
        batch_prompt = f"{prompt}\n\nNote: This is part of a batch analysis of {len(image_paths)} images."
        result = call_vision_ai(
            batch_prompt,
            image_paths[0],
            max_tokens=max_tokens or AI_BATCH_CONFIG['max_tokens'],
            temperature=temperature if temperature is not None else AI_BATCH_CONFIG['temperature'],
        )
        print(f"[AI_UTILS] Batch result: success={result['success']}, provider={result.get('provider_used', 'unknown')}")
        return result
    else:
        return {'success': False, 'error': 'No images provided', 'content': ''}

# =============================================================================
# Helper Functions
# =============================================================================

def _image_to_b64(image_input: Union[str, bytes]) -> Tuple[Optional[str], Optional[str]]:
    """Convert an image (path, data URI, raw bytes, base64 str, or cv2 ndarray) to
    (base64_string, media_type). Returns (None, None) on failure.

    media_type matters: providers like Anthropic validate it against the bytes.
    """
    try:
        if isinstance(image_input, str):
            if image_input.startswith('data:image'):
                header, b64 = image_input.split(',', 1)
                media_type = header[5:].split(';')[0] or 'image/jpeg'
                return b64, media_type
            elif os.path.exists(image_input):
                media_type = 'image/png' if image_input.lower().endswith('.png') else 'image/jpeg'
                with open(image_input, 'rb') as f:
                    return base64.b64encode(f.read()).decode(), media_type
            else:
                # Assume an already-base64 JPEG string.
                return image_input, 'image/jpeg'
        elif isinstance(image_input, bytes):
            return base64.b64encode(image_input).decode(), 'image/jpeg'
        elif hasattr(image_input, 'shape'):  # OpenCV image (numpy ndarray)
            ok, buffer = cv2.imencode('.jpg', image_input)
            if not ok:
                return None, None
            return base64.b64encode(buffer.tobytes()).decode(), 'image/jpeg'
        return None, None
    except Exception as e:
        print(f"AI: Error processing image: {e}")
        return None, None


def _process_image_input(image_input: Union[str, bytes]) -> Optional[str]:
    """Backwards-compatible base64-only image conversion (media type discarded)."""
    b64, _ = _image_to_b64(image_input)
    return b64

# =============================================================================
# Specialized AI Functions
# =============================================================================

def analyze_language_menu_ai(image_path: str, context_name: str = "AI") -> Dict[str, Any]:
    """
    AI-powered language/subtitle menu analysis using centralized AI utilities.
    
    Args:
        image_path: Path to image file showing a language/subtitle menu
        context_name: Context name for logging
        
    Returns:
        Dictionary with language and subtitle options analysis
    """
    try:
        print(f"{context_name}: AI language menu analysis")
        
        # Check if image exists
        if not os.path.exists(image_path):
            print(f"{context_name}: Image file not found: {image_path}")
            return {'success': False, 'error': 'Image file not found'}
        
        # Enhanced prompt for language/subtitle menu detection with exact format extraction
        prompt = """Analyze this image for language/subtitle/audio menu options. This could be a TV settings menu, streaming app menu, or media player interface.

LOOK FOR THESE UI PATTERNS:
- Settings menus with AUDIO, SUBTITLES, or LANGUAGE sections
- Dropdown menus or lists showing language options
- Media player controls with language/subtitle buttons
- TV/STB interface menus for audio/subtitle settings
- Streaming app (Netflix, Prime, etc.) audio/subtitle menus
- Any interface showing language choices like "English", "French", "Spanish", etc.
- Audio tracks, subtitle tracks, or closed caption options

CRITICAL INSTRUCTIONS:
1. You MUST ALWAYS respond with valid JSON - never return empty content
2. If you find ANY language/audio/subtitle menu or options, extract them
3. If you find NO menu, you MUST still respond with the "menu_detected": false JSON format below
4. ALWAYS provide a response - never return empty or null content
5. Be liberal in detecting menus - if there are any language-related options, consider it a menu

Required JSON format when menu found:
{
  "menu_detected": true,
  "audio_languages": ["English - AD - Stereo", "English - Stereo", "French - Stereo"],
  "subtitle_languages": ["English", "French", "Spanish", "Off"],
  "selected_audio": 0,
  "selected_subtitle": 3
}

If no language/subtitle menu found:
{
  "menu_detected": false,
  "audio_languages": [],
  "subtitle_languages": [],
  "selected_audio": -1,
  "selected_subtitle": -1
}

LANGUAGE FORMAT EXTRACTION RULES:
- Extract the COMPLETE text as shown for each language option
- Include ALL descriptors like "AD" (Audio Description), "Stereo", "Dolby", etc.
- Preserve exact formatting with dashes, spaces, and separators as displayed
- Examples of complete formats to capture:
  * "English - AD - Stereo"
  * "English - Stereo"
  * "English - Dolby"
  * "French - Stereo"
  * "French - AD - Stereo"
- DO NOT simplify to just "English" - capture the full descriptive text
- If only "English" is shown without descriptors, then use just "English"

CATEGORIZATION RULES:
- AUDIO section: Main audio languages with their full descriptors
- SUBTITLE section: Subtitle options (usually simpler, like "English", "French", "Off")
- AUDIO DESCRIPTION: These belong in audio_languages, not subtitle_languages
- Look for section headers like "AUDIO", "SUBTITLES", "AUDIO DESCRIPTION", "LANGUAGE", "CC"
- List languages in the order they appear within each section (index 0, 1, 2, etc.)
- Use "Off" for disabled subtitles
- Set selected_audio/selected_subtitle to the index of the currently selected option (-1 if none)
- Check for visual indicators like checkmarks (✓), highlighting, arrows, or bold text

SPECIAL AUDIO HANDLING:
- "Audio description" or "Audio Description" should be treated as an audio language option
- If you see "Audio description" in an AUDIO section, include it as "Audio Description" in audio_languages
- Even standalone audio accessibility options count as audio language choices
- Look for any audio-related options like "Descriptive Audio", "AD", "Audio Description", etc.

IMPORTANT: Even if the image has no language/subtitle menu, you MUST respond with the "menu_detected": false JSON format above. Never return empty content.

RESPOND WITH JSON ONLY - NO MARKDOWN - NO OTHER TEXT"""
        
        # Call AI with image
        result = call_vision_ai(prompt, image_path, max_tokens=400, temperature=0.0)
        
        if not result['success']:
            return {
                'success': False,
                'error': f"AI call failed: {result.get('error', 'Unknown error')}",
                'analysis_type': 'ai_language_menu_analysis'
            }
        
        content = result['content']
        
        # Parse JSON response
        try:
            # Remove markdown code block markers
            json_content = content.replace('```json', '').replace('```', '').strip()
            
            ai_result = json.loads(json_content)
            
            # Validate and normalize the result
            menu_detected = ai_result.get('menu_detected', False)
            audio_languages = ai_result.get('audio_languages', [])
            subtitle_languages = ai_result.get('subtitle_languages', [])
            selected_audio = ai_result.get('selected_audio', -1)
            selected_subtitle = ai_result.get('selected_subtitle', -1)
            
            # Return standardized result
            return {
                'success': True,
                'menu_detected': menu_detected,
                'audio_languages': audio_languages,
                'subtitle_languages': subtitle_languages,
                'selected_audio': selected_audio,
                'selected_subtitle': selected_subtitle,
                'analysis_type': 'ai_language_menu_analysis'
            }
            
        except json.JSONDecodeError as e:
            print(f"{context_name}: JSON parsing error: {e}")
            print(f"{context_name}: Raw AI response: {repr(content)}")
            return {
                'success': False,
                'error': 'Invalid AI response format',
                'raw_response': content,
                'json_error': str(e)
            }
            
    except Exception as e:
        print(f"{context_name}: AI language menu analysis error: {e}")
        return {
            'success': False,
            'error': f'Analysis error: {str(e)}'
        }


def analyze_channel_banner_ai(image_path: str, context_name: str = "AI") -> Dict[str, Any]:
    """
    AI-powered channel banner detection using centralized AI utilities.
    
    Detects TV channel information including channel name, number, program name,
    and timing from channel banners/overlays that appear during channel changes.
    
    Analyzes FULL TV screen image - AI scans entire image for channel information.
    
    Args:
        image_path: Path to image file to analyze (full TV screen)
        context_name: Context name for logging
    
    Returns:
        Dictionary with detection results:
        {
            'success': True/False,
            'banner_detected': True/False,
            'channel_info': {
                'channel_name': 'BBC One',
                'channel_number': '1',
                'program_name': 'News at Six',
                'start_time': '18:00',
                'end_time': '18:30',
                'confidence': 0.95
            },
            'confidence': 0.95,
            'error': 'error message' (if failed)
        }
    """
    try:
        logger.info(f"[{context_name}] AI channel banner analysis")
        logger.info(f"[{context_name}] 📸 FULL IMAGE PATH: {image_path}")
        logger.info(f"[{context_name}] 📂 Image exists: {os.path.exists(image_path)}")
        if os.path.exists(image_path):
            file_size = os.path.getsize(image_path)
            logger.info(f"[{context_name}] 📏 Image size: {file_size} bytes ({file_size/1024:.1f} KB)")
        
        # Check if image exists
        if not os.path.exists(image_path):
            logger.warning(f"[{context_name}] ❌ Image file not found: {image_path}")
            return {'success': False, 'error': 'Image file not found'}
        
        # Create specialized prompt for banner analysis
        prompt = _create_banner_analysis_prompt()
        
        # Call AI with image (increased max_tokens from 400 to 600 to avoid truncation)
        result = call_vision_ai(prompt, image_path, max_tokens=600, temperature=0.0)
        
        logger.info(f"[{context_name}] AI call complete - success={result['success']}, provider={result.get('provider_used', 'unknown')}")
        
        if not result['success']:
            error_msg = result.get('error', 'Unknown error')
            provider_used = result.get('provider_used', 'none')
            logger.error(f"[{context_name}] ❌ AI call failed - error: {error_msg}")
            return {
                'success': False,
                'error': f'AI service error: {error_msg}',
                'provider_used': provider_used
            }
        
        # Parse AI response (JSON)
        content = result['content'].strip()
        
        # 🔍 LOG RAW AI RESPONSE (escape newlines to avoid truncation)
        content_display = content.replace('\n', '\\n').replace('\r', '\\r')
        logger.info(f"[{context_name}] 🤖 RAW AI RESPONSE (length={len(content)}): {content_display}")
        logger.info(f"[{context_name}] {'='*80}")
        
        if not content:
            logger.error(f"[{context_name}] ❌ Empty content from AI service!")
            return {
                'success': False,
                'error': 'Empty content from AI service',
                'raw_content': content
            }
        
        # Check if content looks incomplete (just opening brace or very short)
        if len(content) < 50:
            logger.warning(f"[{context_name}] ⚠️  Suspiciously short AI response: {repr(content)}")
        
        # Check if response looks like incomplete JSON
        if content.strip() == '{' or content.strip() == '[':
            logger.error(f"[{context_name}] ❌ AI returned incomplete JSON (only opening brace)")
            return {
                'success': False,
                'error': 'Incomplete JSON response from AI',
                'raw_content': content
            }
        
        # Remove markdown code block markers if present
        json_content = content.replace('```json', '').replace('```', '').strip()
        
        try:
            ai_result = json.loads(json_content)
        except json.JSONDecodeError as e:
            logger.error(f"[{context_name}] JSON parsing error: {e}")
            logger.error(f"[{context_name}] Raw AI response: {repr(content)}")
            
            # ✅ FALLBACK: Extract fields from incomplete/truncated JSON
            # If we can find channel_name, program_name, etc., consider it a success
            logger.info(f"[{context_name}] 🔧 Attempting fallback extraction from raw response...")
            
            import re
            fallback_data = {}
            
            # Extract fields using regex (handle both complete and incomplete JSON)
            patterns = {
                'banner_detected': r'"banner_detected"\s*:\s*(true|false)',
                'channel_name': r'"channel_name"\s*:\s*"([^"]*)"',
                'channel_number': r'"channel_number"\s*:\s*"([^"]*)"',
                'program_name': r'"program_name"\s*:\s*"([^"]*)"',
                'episode_information': r'"episode_information"\s*:\s*"([^"]*)"',
                'start_time': r'"start_time"\s*:\s*"([^"]*)"',
                'end_time': r'"end_time"\s*:\s*"([^"]*)"',
                'confidence': r'"confidence"\s*:\s*([0-9.]+)'
            }
            
            for field, pattern in patterns.items():
                match = re.search(pattern, content)
                if match:
                    value = match.group(1)
                    if field == 'banner_detected':
                        fallback_data[field] = value == 'true'
                    elif field == 'confidence':
                        fallback_data[field] = float(value)
                    else:
                        fallback_data[field] = value
            
            # Check if we have ANY useful channel/program info
            has_channel_info = any([
                fallback_data.get('channel_name', '').strip(),
                fallback_data.get('channel_number', '').strip(),
                fallback_data.get('program_name', '').strip(),
                fallback_data.get('episode_information', '').strip()
            ])
            
            if has_channel_info:
                logger.info(f"[{context_name}] ✅ Fallback extraction successful - found channel info!")
                logger.info(f"[{context_name}] Extracted: {fallback_data}")
                # Override banner_detected to true since we found channel info
                fallback_data['banner_detected'] = True
                ai_result = fallback_data
            else:
                logger.error(f"[{context_name}] ❌ Fallback extraction failed - no channel info found")
                return {
                    'success': False,
                    'error': 'Invalid AI response format',
                    'raw_response': content,
                    'json_error': str(e)
                }
        
        # Validate and normalize the result
        banner_detected = ai_result.get('banner_detected', False)
        channel_name = ai_result.get('channel_name', '')
        channel_number = ai_result.get('channel_number', '')
        program_name = ai_result.get('program_name', '')
        start_time = ai_result.get('start_time', '')
        end_time = ai_result.get('end_time', '')
        confidence = float(ai_result.get('confidence', 0.0))
        
        # ✅ SMART DETECTION: Override AI's banner_detected if we have useful info
        # Even if AI says "banner_detected: false", if we extracted meaningful channel/program info, count it as success
        has_useful_info = any([
            channel_name and len(channel_name.strip()) > 2,
            program_name and len(program_name.strip()) > 2,
            start_time and len(start_time.strip()) > 2,
            end_time and len(end_time.strip()) > 2
        ])
        
        if has_useful_info and not banner_detected:
            logger.info(f"[{context_name}] 🔧 OVERRIDE: AI said banner_detected=false, but found useful info - setting to true")
            banner_detected = True
        
        # ✅ CALCULATE CONFIDENCE based on extracted fields
        if banner_detected:
            confidence_score = 0.0
            # Channel name/logo: +0.4
            if channel_name and len(channel_name.strip()) > 2:
                confidence_score += 0.4
            # Program name: +0.3
            if program_name and len(program_name.strip()) > 2:
                confidence_score += 0.3
            # Time information: +0.2
            if (start_time and len(start_time.strip()) > 2) or (end_time and len(end_time.strip()) > 2):
                confidence_score += 0.2
            # Channel number (bonus): +0.1
            if channel_number and len(channel_number.strip()) > 0:
                confidence_score += 0.1
            
            confidence = min(1.0, confidence_score)  # Cap at 1.0
            logger.info(f"[{context_name}] 📊 Calculated confidence: {confidence:.2f} (channel={bool(channel_name)}, program={bool(program_name)}, time={bool(start_time or end_time)})")
        else:
            confidence = 0.1  # No banner detected
        
        logger.info(f"[{context_name}] {'='*80}")
        logger.info(f"[{context_name}] 🎯 AI ANALYSIS RESULT:")
        logger.info(f"[{context_name}]    📸 Image analyzed: {image_path}")
        logger.info(f"[{context_name}]    🔍 Banner detected: {banner_detected} (AI said: {ai_result.get('banner_detected', False)})")
        if banner_detected:
            logger.info(f"[{context_name}]    📺 Channel: {channel_name} ({channel_number})")
            logger.info(f"[{context_name}]    📋 Program: {program_name}")
            logger.info(f"[{context_name}]    ⏰ Time: {start_time} - {end_time}")
            logger.info(f"[{context_name}]    ✅ Confidence: {confidence:.2f}")
        else:
            logger.info(f"[{context_name}]    ❌ No banner found in image")
            logger.info(f"[{context_name}]    📉 Confidence: {confidence:.2f}")
        logger.info(f"[{context_name}] {'='*80}")
        
        # Return standardized result
        return {
            'success': True,
            'banner_detected': banner_detected,
            'channel_info': {
                'channel_name': channel_name,
                'channel_number': channel_number,
                'program_name': program_name,
                'start_time': start_time,
                'end_time': end_time,
                'confidence': confidence
            },
            'confidence': confidence,
            'image_path': os.path.basename(image_path)
        }
        
    except Exception as e:
        logger.error(f"[{context_name}] AI channel banner analysis error: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return {
            'success': False,
            'error': f'Analysis error: {str(e)}'
        }


def _create_banner_analysis_prompt() -> str:
    """
    Create specialized prompt for channel banner analysis.
    
    This prompt is optimized for full image analysis to detect channel
    information, logos, program names, episode details, and timing information.
    
    Returns:
        Formatted prompt string for AI analysis
    """
    return """Analyze this TV screen image to extract channel and program information.

WHAT YOU'RE LOOKING FOR:
You need to identify ANY visible channel information display, including:
- Channel logos or names (e.g., "BBC One", "U&DRAMA", "ITV", "Channel 4")
- Program/show titles (e.g., "New Tricks", "EastEnders", "News")
- Episode information (e.g., "S 2, Ep 7 - Fluke of Luck")
- Time information (e.g., "00:15 - 01:35", "18:00 - 19:00")

IMPORTANT: Set "banner_detected": true if you can see ANY of the following:
✓ Channel logo or name visible anywhere in the image
✓ Program title displayed with time information
✓ Episode information with channel branding
✓ TV player UI showing channel and program details
✓ Any on-screen display (OSD) with channel/program info

This includes:
- Player overlays showing program information
- Channel banners that appear during channel changes
- Program guide information bars
- Corner logos with program details
- ANY text showing what channel/program is playing

Required JSON format (if channel info found):
{
  "banner_detected": true,
  "channel_name": "U&DRAMA",
  "channel_number": "",
  "program_name": "New Tricks",
  "episode_information": "S 2, Ep 7 - Fluke of Luck",
  "start_time": "00:15",
  "end_time": "01:35",
  "confidence": 0.85
}

If NO channel or program information visible:
{
  "banner_detected": false,
  "channel_name": "",
  "channel_number": "",
  "program_name": "",
  "episode_information": "",
  "start_time": "",
  "end_time": "",
  "confidence": 0.1
}

EXTRACTION RULES:
- Channel name: Look in ALL corners, especially top-left and top-right for logos/text
- Channel number: Usually appears before/near the channel name (e.g., "101 BBC One")
- Program name: Main title text (e.g., "New Tricks"), do NOT include episode info here
- Episode information: Season/episode details (e.g., "S 2, Ep 7 - Fluke of Luck") - extract separately!
- Start/end times: Format as HH:MM (e.g., "18:00", "01:35")
- If you see a channel logo without explicit channel number, leave channel_number empty
- Leave confidence as 0.5 (we calculate actual confidence based on extracted fields)

CRITICAL: You MUST respond with valid JSON. Never return empty content.

RESPOND ONLY WITH THE JSON OBJECT - NO MARKDOWN BLOCKS - NO EXPLANATION."""
