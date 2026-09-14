"""
Audio Utilities - Shared TTS and audio generation helpers

This module provides a single, unified interface for audio operations
to avoid code duplication across the codebase.
"""

import os
import subprocess
import tempfile
from typing import Optional


# Centralized voice mapping (used by all dubbing features)
EDGE_TTS_VOICE_MAP = {
    'fr': 'fr-FR-DeniseNeural',
    'en': 'en-US-JennyNeural',
    'es': 'es-ES-ElviraNeural',
    'de': 'de-DE-KatjaNeural',
    'it': 'it-IT-ElsaNeural',
    'pt': 'pt-BR-FranciscaNeural'
}


def generate_edge_tts_audio(
    text: str,
    language_code: str,
    output_path: str,
    voice_name: Optional[str] = None
) -> bool:
    """
    Generate audio from text using Edge-TTS (Microsoft Azure Text-to-Speech)
    
    This is the SINGLE source of truth for Edge-TTS generation.
    Used by:
    - Transcript dubbing (1-minute and 10-minute chunks)
    - Restart video dubbing
    - Any other TTS feature
    
    Args:
        text: Text to convert to speech
        language_code: Language code (fr, en, es, de, it, pt)
        output_path: Output MP3 file path
        voice_name: Optional voice name override (uses EDGE_TTS_VOICE_MAP if not provided)
    
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        import edge_tts
        import asyncio
        
        # Use provided voice or look up from centralized map
        voice = voice_name or EDGE_TTS_VOICE_MAP.get(language_code, 'en-US-JennyNeural')
        
        async def generate_audio():
            communicate = edge_tts.Communicate(text, voice)
            await communicate.save(output_path)
        
        # Run async function
        asyncio.run(generate_audio())
        
        # Verify file was created
        return os.path.exists(output_path) and os.path.getsize(output_path) > 0
        
    except Exception as e:
        print(f"Error generating Edge-TTS audio: {e}")
        return False


def extract_audio_from_video(video_path: str, audio_output_path: str, format: str = 'mp3') -> bool:
    """
    Extract audio from video file using FFmpeg
    
    Args:
        video_path: Input video file path
        audio_output_path: Output audio file path
        format: Audio format (mp3, wav, etc.)
    
    Returns:
        bool: True if successful, False otherwise
    """
    try:
        subprocess.run(
            ['ffmpeg', '-i', video_path, '-vn', '-acodec', 'libmp3lame' if format == 'mp3' else 'pcm_s16le',
             '-q:a', '4', audio_output_path, '-y'],
            capture_output=True,
            check=True,
            timeout=30
        )
        return os.path.exists(audio_output_path) and os.path.getsize(audio_output_path) > 0
    except Exception as e:
        print(f"Error extracting audio: {e}")
        return False

