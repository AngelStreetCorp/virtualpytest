"""
Translation Utilities - AI-powered text translation using existing AI infrastructure
"""

from typing import Dict, Any, Optional
from shared.src.lib.utils.ai_utils import call_text_ai

# Local translation imports (optional)
try:
    import argostranslate.package
    import argostranslate.translate
    ARGOS_AVAILABLE = True
except ImportError:
    ARGOS_AVAILABLE = False

try:
    from googletrans import Translator
    GOOGLE_TRANSLATE_AVAILABLE = True
except ImportError:
    GOOGLE_TRANSLATE_AVAILABLE = False

def translate_text_local_argos(text: str, source_language: str, target_language: str) -> Dict[str, Any]:
    """
    Fast local translation using Argos Translate (offline, ~0.05-0.1s)
    """
    try:
        if not ARGOS_AVAILABLE:
            return {
                'success': False,
                'error': 'Argos Translate not installed. Run: pip install argostranslate',
                'translated_text': '',
                'source_language': source_language,
                'target_language': target_language
            }
        
        if not text or not text.strip():
            return {
                'success': False,
                'error': 'Empty text provided',
                'translated_text': '',
                'source_language': source_language,
                'target_language': target_language
            }
        
        # Skip if same language
        if source_language == target_language:
            return {
                'success': True,
                'translated_text': text,
                'source_language': source_language,
                'target_language': target_language,
                'skipped': True
            }
        
        # Translate using Argos
        translated_text = argostranslate.translate.translate(text, source_language, target_language)
        
        return {
            'success': True,
            'translated_text': translated_text,
            'source_language': source_language,
            'target_language': target_language,
            'original_text': text,
            'method': 'argos_local'
        }
        
    except Exception as e:
        return {
            'success': False,
            'error': f'Local translation error: {str(e)}',
            'translated_text': '',
            'source_language': source_language,
            'target_language': target_language
        }

async def translate_text_local_google(text: str, source_language: str, target_language: str) -> Dict[str, Any]:
    """
    Fast translation using Google Translate library with async support (~0.05-0.15s)
    """
    try:
        if not GOOGLE_TRANSLATE_AVAILABLE:
            return {
                'success': False,
                'error': 'Google Translate not installed. Run: pip install googletrans==4.0.0rc1',
                'translated_text': '',
                'source_language': source_language,
                'target_language': target_language
            }
        
        if not text or not text.strip():
            return {
                'success': False,
                'error': 'Empty text provided',
                'translated_text': '',
                'source_language': source_language,
                'target_language': target_language
            }
        
        # Skip if same language
        if source_language == target_language:
            return {
                'success': True,
                'translated_text': text,
                'source_language': source_language,
                'target_language': target_language,
                'skipped': True
            }
        
        # Translate using Google Translate with async/await
        translator = Translator()
        # Use auto-detection if source_language is 'auto' or not specified
        if source_language == 'auto' or not source_language:
            result = await translator.translate(text, dest=target_language)
        else:
            result = await translator.translate(text, src=source_language, dest=target_language)
        
        return {
            'success': True,
            'translated_text': result.text,
            'source_language': source_language,
            'target_language': target_language,
            'original_text': text,
            'method': 'google_local_async'
        }
        
    except Exception as e:
        return {
            'success': False,
            'error': f'Google Translate error: {str(e)}',
            'translated_text': '',
            'source_language': source_language,
            'target_language': target_language
        }

def translate_text(text: str, source_language: str, target_language: str, method: str = 'google') -> Dict[str, Any]:
    # Map language names to codes (support both capitalized and lowercase)
    lang_map = {
        'English':'en', 'english':'en',
        'French':'fr', 'french':'fr', 
        'Spanish':'es', 'spanish':'es',
        'German':'de', 'german':'de',
        'Italian':'it', 'italian':'it',
        'Portuguese':'pt', 'portuguese':'pt',
        'Russian':'ru', 'russian':'ru',
        'Japanese':'ja', 'japanese':'ja',
        'Korean':'ko', 'korean':'ko',
        'Chinese':'zh', 'chinese':'zh',
        'Arabic':'ar', 'arabic':'ar',
        'Hindi':'hi', 'hindi':'hi'
    }
    source_code = lang_map.get(source_language, source_language)
    target_code = lang_map.get(target_language, target_language)
    """
    Translate text using various methods with fallback support.
    
    Args:
        text: Text to translate
        source_language: Source language code (e.g., 'en', 'es', 'fr')
        target_language: Target language code
        method: Translation method ('ai', 'argos', 'google', 'auto')
                'auto' tries local methods first, falls back to AI
        
    Returns:
        Dict with success status, translated text, and metadata
    """
    
    # Auto method: try Google first, fallback to AI
    if method == 'auto':
        # Try Google Translate first (fast, high quality)
        if GOOGLE_TRANSLATE_AVAILABLE:
            import asyncio
            result = asyncio.run(translate_text_local_google(text, source_code, target_code))
            if result['success']:
                return result
        
        # Try Argos second (offline fallback)
        if ARGOS_AVAILABLE:
            result = translate_text_local_argos(text, source_language, target_language)
            if result['success']:
                return result
        
        # Fallback to AI
        method = 'ai'
    
    # Direct method calls
    if method == 'argos':
        return translate_text_local_argos(text, source_language, target_language)
    elif method == 'google':
        import asyncio
        return asyncio.run(translate_text_local_google(text, source_code, target_code))
    elif method == 'ai':
        # Original AI implementation
        pass
    else:
        return {
            'success': False,
            'error': f'Unknown translation method: {method}',
            'translated_text': '',
            'source_language': source_language,
            'target_language': target_language
        }
    try:
        if not text or not text.strip():
            return {
                'success': False,
                'error': 'Empty text provided',
                'translated_text': '',
                'source_language': source_language,
                'target_language': target_language
            }
        
        # Skip translation if source and target are the same
        if source_language == target_language:
            return {
                'success': True,
                'translated_text': text,
                'source_language': source_language,
                'target_language': target_language,
                'skipped': True
            }
        
        # Language name mapping for better AI understanding
        language_names = {
            'en': 'English',
            'es': 'Spanish',
            'fr': 'French',
            'de': 'German',
            'it': 'Italian',
            'pt': 'Portuguese',
            'ru': 'Russian',
            'ja': 'Japanese',
            'ko': 'Korean',
            'zh': 'Chinese',
            'ar': 'Arabic',
            'hi': 'Hindi'
        }
        
        source_name = language_names.get(source_language, source_language)
        target_name = language_names.get(target_language, target_language)
        
        # Create translation prompt
        prompt = f"""Translate the following text from {source_name} to {target_name}.

IMPORTANT INSTRUCTIONS:
1. Provide ONLY the translated text - no explanations, no quotes, no additional text
2. Preserve the original meaning and context
3. Keep the same tone and style (formal/informal)
4. For subtitle text, keep it concise and readable
5. If the text is already in {target_name}, return it unchanged
6. Do not add any formatting or markdown
7. Do NOT include language detection metadata, confidence percentages, or phrases like "Translated to X"
8. Do NOT include technical annotations or metadata prefixes
9. Provide ONLY the clean translated content

Text to translate:
{text}

Translation:"""

        # Call AI for translation
        result = call_text_ai(prompt, max_tokens=300, temperature=0.1)
        
        if result['success']:
            translated_text = result['content'].strip()
            
            # Clean up any unwanted formatting or quotes
            if translated_text.startswith('"') and translated_text.endswith('"'):
                translated_text = translated_text[1:-1]
            if translated_text.startswith("'") and translated_text.endswith("'"):
                translated_text = translated_text[1:-1]
            
            # Remove any confidence metadata that might have been included
            import re
            # Remove patterns like "Translated to Spanish(ENGLISH, 95% confidence):"
            translated_text = re.sub(r'^Translated to \w+\([^)]+\):\s*', '', translated_text)
            # Remove patterns like "(ENGLISH, 95% confidence):"
            translated_text = re.sub(r'\([A-Z]+,\s*\d+%\s*confidence\):\s*', '', translated_text)
            # Remove any remaining confidence metadata patterns
            translated_text = re.sub(r'\(\w+,\s*\d+%\s*confidence\):\s*', '', translated_text)
            # Remove patterns like "Translated to Spanish" at the beginning
            translated_text = re.sub(r'^Translated to \w+:\s*', '', translated_text)
            # Remove any language detection metadata
            translated_text = re.sub(r'\([A-Z]+\):\s*', '', translated_text)
            
            translated_text = translated_text.strip()
            
            return {
                'success': True,
                'translated_text': translated_text,
                'source_language': source_language,
                'target_language': target_language,
                'original_text': text
            }
        else:
            return {
                'success': False,
                'error': f'Translation failed: {result.get("error", "Unknown error")}',
                'translated_text': '',
                'source_language': source_language,
                'target_language': target_language
            }
            
    except Exception as e:
        return {
            'success': False,
            'error': f'Translation error: {str(e)}',
            'translated_text': '',
            'source_language': source_language,
            'target_language': target_language
        }

def batch_translate_segments(segments: list, source_language: str, target_language: str) -> Dict[str, Any]:
    """
    Translate multiple text segments efficiently.
    
    Args:
        segments: List of text segments to translate
        source_language: Source language code
        target_language: Target language code
        
    Returns:
        Dict with success status and list of translated segments
    """
    try:
        if not segments:
            return {
                'success': True,
                'translated_segments': [],
                'source_language': source_language,
                'target_language': target_language
            }
        
        # Skip if same language
        if source_language == target_language:
            return {
                'success': True,
                'translated_segments': segments,
                'source_language': source_language,
                'target_language': target_language,
                'skipped': True
            }
        
        # Combine segments for batch translation
        combined_text = "\n---SEGMENT---\n".join(segments)
        
        # Translate combined text using Google Translate (fastest)
        translation_result = translate_text(combined_text, source_language, target_language, method='google')
        
        if translation_result['success']:
            # Split back into segments
            translated_combined = translation_result['translated_text']
            translated_segments = translated_combined.split("\n---SEGMENT---\n")
            
            # Ensure we have the same number of segments
            if len(translated_segments) != len(segments):
                # Fallback to individual translation
                translated_segments = []
                for segment in segments:
                    individual_result = translate_text(segment, source_language, target_language, method='google')
                    if individual_result['success']:
                        translated_segments.append(individual_result['translated_text'])
                    else:
                        translated_segments.append(segment)  # Keep original if translation fails
            
            return {
                'success': True,
                'translated_segments': translated_segments,
                'source_language': source_language,
                'target_language': target_language,
                'original_segments': segments
            }
        else:
            return {
                'success': False,
                'error': translation_result['error'],
                'translated_segments': segments,  # Return originals on failure
                'source_language': source_language,
                'target_language': target_language
            }
            
    except Exception as e:
        return {
            'success': False,
            'error': f'Batch translation error: {str(e)}',
            'translated_segments': segments,  # Return originals on failure
            'source_language': source_language,
            'target_language': target_language
        }

def batch_translate_restart_content(content_blocks: Dict[str, Any], target_language: str) -> Dict[str, Any]:
    """
    Translate all restart video content in a single AI request.
    
    Args:
        content_blocks: Dict containing all content to translate
        target_language: Target language code
        
    Returns:
        Dict with all translated content organized by type
    """
    try:
        # Build structured prompt for single AI call
        sections = []
        section_map = {}
        
        # Video Summary Section
        if content_blocks.get('video_summary', {}).get('text'):
            sections.append(f"[VIDEO_SUMMARY]\n{content_blocks['video_summary']['text']}")
            section_map['video_summary'] = len(sections) - 1
        
        # Audio Transcript Section  
        if content_blocks.get('audio_transcript', {}).get('text'):
            sections.append(f"[AUDIO_TRANSCRIPT]\n{content_blocks['audio_transcript']['text']}")
            section_map['audio_transcript'] = len(sections) - 1
        
        # Frame Descriptions Section
        if content_blocks.get('frame_descriptions', {}).get('texts'):
            frame_texts = content_blocks['frame_descriptions']['texts']
            descriptions_text = "\n".join([f"FRAME_{i+1}: {text}" for i, text in enumerate(frame_texts)])
            sections.append(f"[FRAME_DESCRIPTIONS]\n{descriptions_text}")
            section_map['frame_descriptions'] = len(sections) - 1
            print(f"[TRANSLATION] 📝 FRAME_DESCRIPTIONS: {len(frame_texts)} frames to translate")
        
        # Frame Subtitles Section
        if content_blocks.get('frame_subtitles', {}).get('texts'):
            subtitle_texts = content_blocks['frame_subtitles']['texts']
            subtitles_text = "\n".join([f"SUBTITLE_{i+1}: {text}" for i, text in enumerate(subtitle_texts)])
            sections.append(f"[FRAME_SUBTITLES]\n{subtitles_text}")
            section_map['frame_subtitles'] = len(sections) - 1
            print(f"[TRANSLATION] 📝 FRAME_SUBTITLES: {len(subtitle_texts)} subtitles to translate")
        
        if not sections:
            return {'success': True, 'translations': {}, 'skipped': True}
        
        # Create single comprehensive prompt
        language_names = {
            'en': 'English', 'es': 'Spanish', 'fr': 'French', 'de': 'German',
            'it': 'Italian', 'pt': 'Portuguese', 'ru': 'Russian', 'ja': 'Japanese',
            'ko': 'Korean', 'zh': 'Chinese', 'ar': 'Arabic', 'hi': 'Hindi'
        }
        target_name = language_names.get(target_language, target_language)
        
        combined_content = "\n\n".join(sections)
        
        prompt = f"""Translate ALL sections below to {target_name}. Maintain the EXACT same structure and section headers.

CRITICAL INSTRUCTIONS:
1. Keep ALL section headers EXACTLY as shown: [VIDEO_SUMMARY], [AUDIO_TRANSCRIPT], [FRAME_DESCRIPTIONS], [FRAME_SUBTITLES]
2. For FRAME_DESCRIPTIONS: Keep "FRAME_1:", "FRAME_2:" etc. prefixes
3. For FRAME_SUBTITLES: Keep "SUBTITLE_1:", "SUBTITLE_2:" etc. prefixes  
4. Translate ONLY the content after the colons, NOT the prefixes
5. Preserve all line breaks and structure
6. If text is already in {target_name}, keep it unchanged
7. Do not add explanations or additional text
8. Do NOT include language detection metadata, confidence percentages, or phrases like "Translated to X"
9. Provide ONLY the translated content without any prefixes or metadata

Content to translate:

{combined_content}

Translated content:"""

        # Use Google Translate for fast batch translation
        print(f"[TRANSLATION] 🚀 Starting Google Translate batch translation to {target_language}")
        print(f"[TRANSLATION] Sections to translate: {list(section_map.keys())}")
        print(f"[TRANSLATION] Total content length: {len(combined_content)} characters")
        
        # Use Google Translate instead of AI for speed (with async support)
        if GOOGLE_TRANSLATE_AVAILABLE:
            try:
                import asyncio
                
                async def async_google_translate():
                    translator = Translator()
                    # Auto-detect source language instead of assuming English (support both capitalized and lowercase)
                    lang_map = {
                        'English':'en', 'english':'en',
                        'French':'fr', 'french':'fr', 
                        'Spanish':'es', 'spanish':'es',
                        'German':'de', 'german':'de',
                        'Italian':'it', 'italian':'it',
                        'Portuguese':'pt', 'portuguese':'pt',
                        'Russian':'ru', 'russian':'ru',
                        'Japanese':'ja', 'japanese':'ja',
                        'Korean':'ko', 'korean':'ko',
                        'Chinese':'zh', 'chinese':'zh',
                        'Arabic':'ar', 'arabic':'ar',
                        'Hindi':'hi', 'hindi':'hi'
                    }
                    target_code = lang_map.get(target_language, target_language)
                    translate_result = await translator.translate(combined_content, dest=target_code)
                    return translate_result
                
                # Run async translation
                translate_result = asyncio.run(async_google_translate())
                translated_content = translate_result.text
                detected_source = translate_result.src or 'auto'
                print(f"[TRANSLATION] ⚡ Detected source language: {detected_source} → {target_language}")
                result = {'success': True, 'content': translated_content}
                print(f"[TRANSLATION] ⚡ Google Translate completed successfully")
            except Exception as e:
                print(f"[TRANSLATION] ❌ Google Translate failed: {e}, falling back to AI")
                result = call_text_ai(prompt, max_tokens=2000, temperature=0.1)
        else:
            print(f"[TRANSLATION] ⚠️ Google Translate not available, using AI")
            result = call_text_ai(prompt, max_tokens=2000, temperature=0.1)
        
        print(f"[TRANSLATION] AI call result: success={result['success']}")
        if not result['success']:
            print(f"[TRANSLATION] AI error: {result.get('error', 'Unknown error')}")
            if 'response_body' in result:
                print(f"[TRANSLATION] OpenRouter response body: {result['response_body']}")
        
        if result['success']:
            return _parse_batch_translation_response(result['content'], section_map, content_blocks)
        else:
            return {
                'success': False,
                'error': f'Batch translation failed: {result.get("error", "Unknown error")}',
                'translations': {},
                'openrouter_response': result.get('response_body', 'No response body available')
            }
            
    except Exception as e:
        return {
            'success': False,
            'error': f'Batch translation error: {str(e)}',
            'translations': {}
        }

def _clean_translated_text(text: str) -> str:
    """Clean translated text from AI metadata and formatting."""
    import re
    
    # Remove patterns like "Translated to Spanish(ENGLISH, 95% confidence):"
    text = re.sub(r'^Translated to \w+\([^)]+\):\s*', '', text)
    # Remove patterns like "(ENGLISH, 95% confidence):"
    text = re.sub(r'\([A-Z]+,\s*\d+%\s*confidence\):\s*', '', text)
    # Remove any remaining confidence metadata patterns
    text = re.sub(r'\(\w+,\s*\d+%\s*confidence\):\s*', '', text)
    # Remove patterns like "Translated to Spanish" at the beginning
    text = re.sub(r'^Translated to \w+:\s*', '', text)
    # Remove any language detection metadata
    text = re.sub(r'\([A-Z]+\):\s*', '', text)
    
    return text.strip()

def _parse_batch_translation_response(response: str, section_map: Dict, original_content: Dict) -> Dict[str, Any]:
    """Parse the structured AI response back into organized translations."""
    from datetime import datetime
    
    try:
        translations = {}
        parsing_timestamp = datetime.now().strftime('%H:%M:%S')
        
        print(f"[TRANSLATION] 🔍 [{parsing_timestamp}] Parsing batch translation response...")
        
        # Split response by section headers
        sections = response.split('[')
        
        for section in sections[1:]:  # Skip first empty split
            if not section.strip():
                continue
                
            # Extract section name and content
            lines = section.strip().split('\n', 1)
            if len(lines) < 2:
                continue
                
            section_name = lines[0].replace(']', '').strip().lower()
            section_content = lines[1].strip()
            
            # Parse based on section type
            if section_name == 'video_summary':
                translations['video_summary'] = _clean_translated_text(section_content)
                print(f"[TRANSLATION] ✅ [{parsing_timestamp}] VIDEO_SUMMARY translated ({len(section_content)} chars)")
                
            elif section_name == 'audio_transcript':
                translations['audio_transcript'] = _clean_translated_text(section_content)
                print(f"[TRANSLATION] ✅ [{parsing_timestamp}] AUDIO_TRANSCRIPT translated ({len(section_content)} chars)")
                
            elif section_name == 'frame_descriptions':
                # Parse FRAME_1:, FRAME_2: format
                frame_lines = section_content.split('\n')
                frame_descriptions = []
                successful_frames = 0
                for i, line in enumerate(frame_lines):
                    if ':' in line and line.strip():
                        # Extract content after "FRAME_X: "
                        content = line.split(':', 1)[1].strip()
                        frame_descriptions.append(_clean_translated_text(content))
                        successful_frames += 1
                    elif line.strip():  # Non-empty line without colon
                        print(f"[TRANSLATION] ⚠️ [{parsing_timestamp}] FRAME_DESCRIPTIONS line {i+1} malformed: '{line[:50]}...'")
                
                translations['frame_descriptions'] = frame_descriptions
                original_count = len(original_content.get('frame_descriptions', {}).get('texts', []))
                print(f"[TRANSLATION] ✅ [{parsing_timestamp}] FRAME_DESCRIPTIONS: {successful_frames}/{original_count} frames translated")
                
            elif section_name == 'frame_subtitles':
                # Parse SUBTITLE_1:, SUBTITLE_2: format  
                subtitle_lines = section_content.split('\n')
                frame_subtitles = []
                successful_subtitles = 0
                for i, line in enumerate(subtitle_lines):
                    if ':' in line and line.strip():
                        # Extract content after "SUBTITLE_X: "
                        content = line.split(':', 1)[1].strip()
                        frame_subtitles.append(_clean_translated_text(content))
                        successful_subtitles += 1
                    elif line.strip():  # Non-empty line without colon
                        print(f"[TRANSLATION] ⚠️ [{parsing_timestamp}] FRAME_SUBTITLES line {i+1} malformed: '{line[:50]}...'")
                
                translations['frame_subtitles'] = frame_subtitles
                original_count = len(original_content.get('frame_subtitles', {}).get('texts', []))
                print(f"[TRANSLATION] ✅ [{parsing_timestamp}] FRAME_SUBTITLES: {successful_subtitles}/{original_count} subtitles translated")
        
        # Summary of what was translated
        translated_sections = list(translations.keys())
        expected_sections = list(section_map.keys())
        missing_sections = [s for s in expected_sections if s not in translated_sections]
        
        if missing_sections:
            print(f"[TRANSLATION] ⚠️ [{parsing_timestamp}] Missing sections: {missing_sections}")
        
        print(f"[TRANSLATION] 📊 [{parsing_timestamp}] Translation summary: {len(translated_sections)}/{len(expected_sections)} sections completed")
        
        return {
            'success': True,
            'translations': translations,
            'original_content': original_content
        }
        
    except Exception as e:
        return {
            'success': False,
            'error': f'Response parsing error: {str(e)}',
            'translations': {}
        }

def detect_language_from_text(text: str) -> Dict[str, Any]:
    """
    Detect language of text using AI.
    
    Args:
        text: Text to analyze
        
    Returns:
        Dict with detected language code and confidence
    """
    try:
        if not text or not text.strip():
            return {
                'success': False,
                'error': 'Empty text provided',
                'language': 'unknown',
                'confidence': 0.0
            }
        
        prompt = f"""Detect the language of the following text and respond with ONLY the two-letter language code (e.g., en, es, fr, de, it, pt, ru, ja, ko, zh, ar, hi).

Text: {text}

Language code:"""

        result = call_text_ai(prompt, max_tokens=10, temperature=0.0)
        
        if result['success']:
            detected_code = result['content'].strip().lower()
            
            # Validate the code
            valid_codes = ['en', 'es', 'fr', 'de', 'it', 'pt', 'ru', 'ja', 'ko', 'zh', 'ar', 'hi']
            if detected_code in valid_codes:
                return {
                    'success': True,
                    'language': detected_code,
                    'confidence': 0.9  # High confidence for AI detection
                }
            else:
                return {
                    'success': False,
                    'error': f'Invalid language code detected: {detected_code}',
                    'language': 'unknown',
                    'confidence': 0.0
                }
        else:
            return {
                'success': False,
                'error': f'Language detection failed: {result.get("error", "Unknown error")}',
                'language': 'unknown',
                'confidence': 0.0
            }
            
    except Exception as e:
        return {
            'success': False,
            'error': f'Language detection error: {str(e)}',
            'language': 'unknown',
            'confidence': 0.0
        }
