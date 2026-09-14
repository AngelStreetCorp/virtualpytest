"""
Video Utilities for VirtualPyTest

Generic video operations: merging, compression, extraction
Reused by: hot_cold_archiver, video_compression_utils, audio_transcription_utils
"""

import os
import subprocess
import tempfile
from pathlib import Path
from typing import List, Optional, Dict, Any, Tuple


def merge_video_files(
    input_files: List[str],
    output_path: str,
    output_format: str = 'mp4',
    delete_source: bool = False,
    timeout: int = 30,
    compression_settings: Dict[str, Any] = None,
    skip_faststart: bool = False,
    regen_timestamps: bool = False
) -> Optional[str]:
    """
    Generic video file merger using FFmpeg concat demuxer

    Uses atomic write (via .tmp file) to prevent corruption from partial writes.

    Args:
        input_files: List of video file paths to merge
        output_path: Path for output file
        output_format: Output format ('mp4' or 'ts')
        delete_source: Delete source files after successful merge
        timeout: FFmpeg timeout in seconds
        compression_settings: Optional compression settings (preset, crf, maxrate, etc.)
        skip_faststart: Skip -movflags +faststart (faster on slow disks like SD cards)
        regen_timestamps: Regenerate presentation timestamps on the way out
            (-fflags +genpts on input, -avoid_negative_ts make_zero on output).
            Needed when concatenating losslessly-cut MP4s that carry edit lists /
            non-zero start PTS (e.g. mid-file `-ss … -c copy` slices): without it the
            concat demuxer hands a player non-monotonic timestamps and it freezes /
            skips the first input. Off by default so existing callers are unchanged.

    Returns:
        Output path if successful, None otherwise
    """
    if not input_files:
        return None

    if len(input_files) == 1:
        return input_files[0]

    concat_file = f"{output_path}.concat.txt"
    # Use .tmp file for atomic write (prevents reading incomplete files)
    temp_output = f"{output_path}.tmp"

    try:
        with open(concat_file, 'w') as f:
            for video_file in input_files:
                f.write(f"file '{video_file}'\n")

        cmd = ['ffmpeg', '-y']
        if regen_timestamps:
            cmd += ['-fflags', '+genpts']
        cmd += ['-f', 'concat', '-safe', '0', '-i', concat_file]

        if compression_settings:
            cmd.extend(['-c:v', 'libx264'])
            cmd.extend(['-preset', compression_settings.get('preset', 'medium')])
            cmd.extend(['-crf', str(compression_settings.get('crf', 23))])
            cmd.extend(['-maxrate', compression_settings.get('maxrate', '800k')])
            cmd.extend(['-bufsize', compression_settings.get('bufsize', '1600k')])
            if 'fps' in compression_settings:
                cmd.extend(['-vf', f'fps={compression_settings["fps"]}'])
            cmd.extend(['-c:a', 'aac', '-b:a', '64k'])
        else:
            # Copy all streams (video + audio) without re-encoding
            cmd.extend(['-c:v', 'copy', '-c:a', 'copy'])
        
        if output_format == 'mp4' and not skip_faststart:
            cmd.extend(['-movflags', '+faststart'])

        if regen_timestamps:
            # Shift timestamps so the first output packet is at zero — kills the
            # initial freeze a player otherwise shows when the first input started
            # at a non-zero PTS (mid-file `-ss` copy slice).
            cmd.extend(['-avoid_negative_ts', 'make_zero'])

        # Explicitly specify output format to avoid issues with .tmp or non-standard extensions
        # Map 'ts' to 'mpegts' for FFmpeg compatibility
        ffmpeg_format = 'mpegts' if output_format == 'ts' else output_format
        cmd.extend(['-f', ffmpeg_format])
        cmd.append(temp_output)
        
        result = subprocess.run(cmd, capture_output=True, timeout=timeout)
        
        if result.returncode == 0 and os.path.exists(temp_output):
            # Atomic rename: file only appears complete when fully written
            # Windows-safe atomic overwrite (os.rename fails if destination exists)
            os.replace(temp_output, output_path)
            os.remove(concat_file)
            
            if delete_source:
                for file_path in input_files:
                    try:
                        os.remove(file_path)
                    except:
                        pass
            
            return output_path
        else:
            # Log FFmpeg failure details
            stderr = result.stderr.decode('utf-8', errors='replace') if result.stderr else 'No stderr'
            print(f"[video_utils] FFmpeg merge failed (returncode={result.returncode})")
            print(f"[video_utils] FFmpeg stderr: {stderr[-500:]}")  # Last 500 chars
            return None
        
    except subprocess.TimeoutExpired as e:
        print(f"[video_utils] FFmpeg merge timeout after {timeout}s")
        return None
    except Exception as e:
        print(f"[video_utils] FFmpeg merge exception: {e}")
        return None
    finally:
        # Cleanup temp files
        if os.path.exists(concat_file):
            try:
                os.remove(concat_file)
            except:
                pass
        if os.path.exists(temp_output):
            try:
                os.remove(temp_output)
            except:
                pass


def get_compression_settings(level: str) -> Dict[str, Any]:
    """Get FFmpeg compression settings for different quality levels"""
    settings = {
        'fast': {
            'preset': 'veryfast',
            'crf': 28,
            'maxrate': '1000k',
            'bufsize': '2000k'
        },
        'medium': {
            'preset': 'medium',
            'crf': 23,
            'maxrate': '800k',
            'bufsize': '1600k'
        },
        'high': {
            'preset': 'slow',
            'crf': 20,
            'maxrate': '600k',
            'bufsize': '1200k'
        },
        'low': {
            'preset': 'ultrafast',
            'crf': 30,
            'maxrate': '500k',
            'bufsize': '1000k'
        },
        'pi_optimized': {
            'preset': 'ultrafast',
            'crf': 30,
            'maxrate': '500k',
            'bufsize': '1000k',
            'fps': 15
        }
    }
    return settings.get(level, settings['medium'])


def compress_video_segments(
    segment_files: List[Tuple[str, str]],
    output_path: str,
    compression_level: str = "medium"
) -> Dict[str, Any]:
    """
    Compress video segments to single MP4 with optional quality settings
    
    Args:
        segment_files: List of (segment_name, segment_path) tuples
        output_path: Output MP4 path
        compression_level: "fast", "medium", "high", "low", "pi_optimized"
        
    Returns:
        Dict with success status, output path, and compression stats
    """
    try:
        if not segment_files:
            return {'success': False, 'error': 'No segments provided'}
        
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        
        original_size = sum(
            os.path.getsize(segment_path) 
            for _, segment_path in segment_files 
            if os.path.exists(segment_path)
        )
        
        file_paths = [segment_path for _, segment_path in segment_files]
        compression_settings = get_compression_settings(compression_level)
        
        result_path = merge_video_files(
            file_paths,
            output_path,
            'mp4',
            False,
            300,
            compression_settings
        )
        
        if result_path and os.path.exists(result_path):
            compressed_size = os.path.getsize(result_path)
            compression_ratio = (original_size - compressed_size) / original_size * 100
            
            return {
                'success': True,
                'output_path': output_path,
                'original_size': original_size,
                'compressed_size': compressed_size,
                'compression_ratio': compression_ratio,
                'segments_count': len(segment_files)
            }
        else:
            return {'success': False, 'error': 'Output file not created'}
            
    except subprocess.TimeoutExpired:
        return {'success': False, 'error': 'Compression timeout (>5 minutes)'}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def merge_progressive_batch(
    source_dir: str,
    source_pattern: str,
    output_path: str,
    count: int,
    delete_source: bool = True,
    timeout: int = 30,
    skip_faststart: bool = False,
) -> Optional[str]:
    """
    Find video files matching pattern, merge N oldest into single file

    Generic progressive merge: finds files, sorts by time, merges batch
    Used for progressive grouping: 6s→1min→10min→1h

    Args:
        source_dir: Directory to search for files
        source_pattern: Glob pattern (e.g., 'segment_*.ts', '6s_*.mp4')
        output_path: Output file path
        count: Number of files to merge
        delete_source: Delete source files after merge
        timeout: FFmpeg timeout in seconds
        skip_faststart: Skip ffmpeg's `+faststart` second-pass moov-relocation. Set
                        True for intermediate hot-storage merges where the resulting
                        MP4 isn't streamed standalone — the second pass doubles I/O
                        on the Pi's storage and is the dominant cost there.

    Returns:
        Output path if successful, None otherwise
    """
    if not os.path.isdir(source_dir):
        return None

    files = sorted(
        [str(f) for f in Path(source_dir).glob(source_pattern) if f.is_file()],
        key=os.path.getmtime
    )

    if len(files) < count:
        return None

    return merge_video_files(files[:count], output_path, 'mp4', delete_source, timeout, skip_faststart=skip_faststart)


# Size policy for report/test videos uploaded to R2 via the nginx proxy.
# - Below COMPRESS_THRESHOLD_MB the video is uploaded as-is.
# - Above the threshold we re-encode (CRF 30, 854px wide cap, AAC 64k mono).
# - HARD_LIMIT_MB is the proxy ceiling; anything still above this after compression
#   is skipped to avoid the certain-413 from nginx.
# Threshold is 5MB (was 20): report videos are stream-copied 720p and averaged
# well under 20MB, so they were stored raw and never compressed — the main driver
# of script-reports/ storage growth. 5MB re-encodes the fatter (longer-test)
# videos where the bytes concentrate while skipping sub-5MB clips so hosts don't
# spend CPU re-encoding tiny files for little gain. Set lower to compress more
# aggressively (higher host CPU per report), higher to compress less.
VIDEO_COMPRESS_THRESHOLD_MB = 5
VIDEO_HARD_LIMIT_MB = 100


def compress_video_for_upload(
    input_path: str,
    threshold_mb: int = VIDEO_COMPRESS_THRESHOLD_MB,
    hard_limit_mb: int = VIDEO_HARD_LIMIT_MB,
    timeout: int = 300,
) -> Dict[str, Any]:
    """
    Conditionally compress a video so it stays under the upload size cap.

    Returns a dict with:
      - 'success' (bool): True if a usable file is ready to upload
      - 'path' (str): file to upload (original or compressed temp file)
      - 'compressed' (bool): whether re-encoding ran
      - 'original_size_mb' / 'final_size_mb' (float)
      - 'error' (str): set when success=False (e.g. file missing, ffmpeg failed,
                      still over hard_limit_mb after compression)

    Caller is responsible for deleting `path` when `compressed` is True.
    """
    result: Dict[str, Any] = {
        'success': False,
        'path': input_path,
        'compressed': False,
        'original_size_mb': 0.0,
        'final_size_mb': 0.0,
        'error': '',
    }

    if not input_path or not os.path.exists(input_path):
        result['error'] = f'Video not found: {input_path}'
        return result

    original_size = os.path.getsize(input_path)
    original_mb = original_size / (1024 * 1024)
    result['original_size_mb'] = round(original_mb, 2)
    result['final_size_mb'] = result['original_size_mb']

    if original_mb <= threshold_mb:
        result['success'] = True
        return result

    base, _ = os.path.splitext(input_path)
    compressed_path = f"{base}.compressed.mp4"

    try:
        proc = subprocess.run(
            [
                'ffmpeg', '-y',
                '-i', input_path,
                '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '30',
                '-vf', "scale='min(iw,854)':-2",
                '-c:a', 'aac', '-b:a', '64k', '-ac', '1',
                '-movflags', '+faststart',
                compressed_path,
            ],
            capture_output=True, timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        if os.path.exists(compressed_path):
            try: os.remove(compressed_path)
            except OSError: pass
        result['error'] = f'ffmpeg compression timed out after {timeout}s'
        return result
    except FileNotFoundError:
        result['error'] = 'ffmpeg binary not found on PATH'
        return result

    if proc.returncode != 0 or not os.path.exists(compressed_path):
        if os.path.exists(compressed_path):
            try: os.remove(compressed_path)
            except OSError: pass
        stderr_tail = (proc.stderr or b'').decode(errors='replace')[-300:]
        result['error'] = f'ffmpeg compression failed (rc={proc.returncode}): {stderr_tail}'
        return result

    compressed_mb = os.path.getsize(compressed_path) / (1024 * 1024)
    result['compressed'] = True
    result['path'] = compressed_path
    result['final_size_mb'] = round(compressed_mb, 2)

    if compressed_mb > hard_limit_mb:
        try: os.remove(compressed_path)
        except OSError: pass
        result['error'] = (
            f'Video still {compressed_mb:.1f}MB after compression '
            f'(original {original_mb:.1f}MB, hard limit {hard_limit_mb}MB) — not uploaded'
        )
        return result

    result['success'] = True
    return result
