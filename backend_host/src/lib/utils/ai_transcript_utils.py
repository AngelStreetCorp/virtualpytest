"""AI-powered transcript enhancement and translation"""

import json
import time
from typing import Dict, Any, List
from shared.src.lib.utils.ai_utils import call_text_ai

def translate_segments(
    segments: List[Dict[str, Any]],
    source_language: str,
    target_language: str
) -> Dict[str, Any]:
    start_time = time.time()
    
    try:
        lang_names = {
            'fr': 'French', 'en': 'English', 'es': 'Spanish',
            'de': 'German', 'it': 'Italian', 'pt': 'Portuguese'
        }
        target_lang_name = lang_names.get(target_language, target_language)
        
        texts = [f"{i+1}. {seg['text']}" for i, seg in enumerate(segments)]
        prompt = f"""Translate these numbered texts from {source_language} to {target_lang_name}.
Keep the same order. Provide ONLY valid JSON.

{chr(10).join(texts)}

Respond with ONLY this JSON (no markdown, no extra text):
{{"translations": ["translated text 1", "translated text 2", ...]}}"""
        
        estimated_tokens = max(3000, len('\n'.join(texts)) * 2)
        result = call_text_ai(prompt, max_tokens=estimated_tokens, temperature=0.0)
        
        if not result['success']:
            return {'success': False, 'error': result.get('error', 'AI call failed'), 'processing_time': time.time() - start_time}
        
        content = result['content'].strip().replace('```json', '').replace('```', '').strip()
        
        try:
            data = json.loads(content)
        except json.JSONDecodeError as e:
            import re
            print(f"[AI_TRANSCRIPT] ⚠️ JSON parse error: {e}")
            print(f"[AI_TRANSCRIPT] Content length: {len(content)} chars")
            print(f"[AI_TRANSCRIPT] Content preview: {content[:200]}...")
            print(f"[AI_TRANSCRIPT] Cleaning control characters and retrying...")
            content = re.sub(r'[\x00-\x08\x0b-\x0c\x0e-\x1f\x7f-\x9f]', '', content)
            try:
                data = json.loads(content)
                print(f"[AI_TRANSCRIPT] ✅ Successfully parsed after cleaning")
            except json.JSONDecodeError as e2:
                print(f"[AI_TRANSCRIPT] ❌ Still failed after cleaning: {e2}")
                print(f"[AI_TRANSCRIPT] Problem area: {content[max(0, e2.pos-50):e2.pos+50]}")
                return {'success': False, 'error': f'Invalid control character at: {e2}', 'processing_time': time.time() - start_time}
        
        translations = data.get('translations', [])
        
        if len(translations) != len(segments):
            print(f"[AI_TRANSCRIPT] ❌ Translation count mismatch: got {len(translations)}, expected {len(segments)}")
            return {'success': False, 'error': f'Translation count mismatch: {len(translations)} != {len(segments)}', 'processing_time': time.time() - start_time}
        
        translated_segments = []
        for i, seg in enumerate(segments):
            new_seg = seg.copy()
            translated_text = translations[i]
            
            if not translated_text or not isinstance(translated_text, str):
                print(f"[AI_TRANSCRIPT] ⚠️ Invalid translation at index {i}: {translated_text}")
                translated_text = seg['text']
            
            new_seg['text'] = translated_text
            translated_segments.append(new_seg)
        
        processing_time = time.time() - start_time
        print(f"[AI_TRANSCRIPT] ✅ Translated {len(translated_segments)} segments to {target_lang_name} in {processing_time:.1f}s")
        
        return {
            'success': True,
            'segments': translated_segments,
            'processing_time': processing_time
        }
    except Exception as e:
        print(f"[AI_TRANSCRIPT] ❌ Translation exception: {e}")
        import traceback
        traceback.print_exc()
        return {'success': False, 'error': str(e), 'processing_time': time.time() - start_time}

def enhance_and_translate_transcript(
    text: str,
    source_language: str,
    target_languages: List[str]
) -> Dict[str, Any]:
    """
    Single AI call to enhance transcript and translate to all languages.
    
    Args:
        text: Original transcript text
        source_language: Detected language (e.g., 'german', 'french')
        target_languages: List of language codes ['fr', 'en', 'es', 'de', 'it']
    
    Returns:
        {
            'success': bool,
            'enhanced_original': str,
            'translations': {'fr': '...', 'en': '...', ...},
            'processing_time': float
        }
    """
    try:
        start_time = time.time()
        
        lang_names = {
            'fr': 'French',
            'en': 'English',
            'es': 'Spanish',
            'de': 'German',
            'it': 'Italian',
            'pt': 'Portuguese'
        }
        
        target_names = [lang_names.get(code, code) for code in target_languages]
        
        # Calculate needed tokens:
        # - Enhanced original: ~len(text) 
        # - 5 translations: 5 * len(text)
        # - JSON overhead + AI verbosity: 1.3x
        # Formula: (text_chars * 6.5) / 3.5 chars_per_token
        # Simplified: text_chars * 2, minimum 5000
        estimated_tokens = max(5000, len(text) * 2)
        
        prompt = f"""Translate this {source_language} text to EXACTLY these {len(target_languages)} languages: {', '.join(target_languages)}.

IMPORTANT: Only include these language codes in your response, no others.

Text:
{text}

Respond with JSON only (no markdown):
{{
    "enhanced_original": "corrected text",
    "translations": {{
        "fr": "French translation",
        "en": "English translation",
        "es": "Spanish translation",
        "de": "German translation",
        "it": "Italian translation"
    }}
}}"""

        result = call_text_ai(prompt, max_tokens=estimated_tokens, temperature=0.0)
        
        if not result['success']:
            return {
                'success': False,
                'error': result.get('error', 'AI call failed'),
                'enhanced_original': text,
                'translations': {},
                'processing_time': time.time() - start_time
            }
        
        content = result['content'].strip()
        content = content.replace('```json', '').replace('```', '').strip()
        
        # Try parsing, if it fails try cleaning control characters
        try:
            data = json.loads(content)
        except json.JSONDecodeError:
            import re
            # Remove control characters (except newlines in context)
            content = re.sub(r'[\x00-\x08\x0b-\x0c\x0e-\x1f\x7f-\x9f]', '', content)
            data = json.loads(content)
        
        return {
            'success': True,
            'enhanced_original': data.get('enhanced_original', text),
            'translations': data.get('translations', {}),
            'processing_time': time.time() - start_time
        }
        
    except json.JSONDecodeError as e:
        return {
            'success': False,
            'error': f'JSON parse error: {e}',
            'enhanced_original': text,
            'translations': {},
            'processing_time': time.time() - start_time
        }
    except Exception as e:
        return {
            'success': False,
            'error': str(e),
            'enhanced_original': text,
            'translations': {},
            'processing_time': time.time() - start_time
        }

