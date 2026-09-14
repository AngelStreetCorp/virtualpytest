#!/usr/bin/env python3
"""
Test script for audio detection optimization
Compares ffprobe vs ffmpeg methods for audio stream detection

Usage:
    python3 test_audio.py
"""

import sys
import time
import subprocess
import json
import numpy as np
from pathlib import Path


def test_ffprobe_json(ts_file):
    """FFprobe - JSON output (simple and reliable)"""
    start = time.perf_counter()
    
    try:
        cmd = [
            'ffprobe',
            '-v', 'quiet',              # Suppress noise
            '-print_format', 'json',
            '-show_streams',
            '-select_streams', 'a',     # Audio streams only
            ts_file
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=0.5)
        data = json.loads(result.stdout)
        
        has_audio_stream = len(data.get('streams', [])) > 0
        elapsed = (time.perf_counter() - start) * 1000
        
        return {
            'success': True,
            'has_audio': has_audio_stream,
            'mean_volume_db': 0.0,  # N/A
            'time_ms': elapsed,
            'method': 'ffprobe JSON',
            'streams_found': len(data.get('streams', []))
        }
    except Exception as e:
        elapsed = (time.perf_counter() - start) * 1000
        return {
            'success': False,
            'error': str(e),
            'time_ms': elapsed,
            'method': 'ffprobe JSON'
        }


def test_ffprobe_basic(ts_file):
    """FFprobe - Basic stream detection (current method)"""
    start = time.perf_counter()
    
    try:
        cmd = [
            'ffprobe',
            '-v', 'error',
            '-select_streams', 'a:0',
            '-show_entries', 'stream=codec_type,codec_name',
            '-of', 'default=noprint_wrappers=1:nokey=1',
            ts_file
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=0.5)
        
        has_audio_stream = 'audio' in result.stdout.lower()
        elapsed = (time.perf_counter() - start) * 1000
        
        return {
            'success': True,
            'has_audio': has_audio_stream,
            'mean_volume_db': 0.0,  # N/A
            'time_ms': elapsed,
            'method': 'ffprobe basic',
            'returncode': result.returncode
        }
    except Exception as e:
        elapsed = (time.perf_counter() - start) * 1000
        return {
            'success': False,
            'error': str(e),
            'time_ms': elapsed,
            'method': 'ffprobe basic'
        }


def test_ffprobe_optimized(ts_file):
    """FFprobe - Optimized with probesize limits"""
    start = time.perf_counter()
    
    try:
        cmd = [
            'ffprobe',
            '-probesize', '32768',
            '-analyzeduration', '0',
            '-v', 'error',
            '-select_streams', 'a:0',
            '-show_entries', 'stream=codec_type',
            '-of', 'default=noprint_wrappers=1:nokey=1',
            ts_file
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=0.5)
        
        has_audio_stream = 'audio' in result.stdout.lower()
        elapsed = (time.perf_counter() - start) * 1000
        
        return {
            'success': True,
            'has_audio': has_audio_stream,
            'mean_volume_db': 0.0,  # N/A
            'time_ms': elapsed,
            'method': 'ffprobe optimized',
            'returncode': result.returncode
        }
    except Exception as e:
        elapsed = (time.perf_counter() - start) * 1000
        return {
            'success': False,
            'error': str(e),
            'time_ms': elapsed,
            'method': 'ffprobe optimized'
        }


def test_ffmpeg_volumedetect_01s(ts_file):
    """FFmpeg volumedetect - 0.1s sample"""
    start = time.perf_counter()
    
    try:
        cmd = [
            'ffmpeg', '-hide_banner', '-loglevel', 'info',
            '-i', ts_file, '-t', '0.1', '-vn',
            '-af', 'volumedetect', '-f', 'null', '-'
        ]
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=1)
        
        has_audio = False
        mean_volume = -100.0
        
        for line in result.stderr.split('\n'):
            if 'mean_volume:' in line:
                try:
                    mean_volume = float(line.split('mean_volume:')[1].split('dB')[0].strip())
                    has_audio = mean_volume > -50.0
                except:
                    pass
        
        elapsed = (time.perf_counter() - start) * 1000
        
        return {
            'success': True,
            'has_audio': has_audio,
            'mean_volume_db': mean_volume,
            'time_ms': elapsed,
            'method': 'ffmpeg vol 0.1s'
        }
    except Exception as e:
        elapsed = (time.perf_counter() - start) * 1000
        return {
            'success': False,
            'error': str(e),
            'time_ms': elapsed,
            'method': 'ffmpeg vol 0.1s'
        }


def test_ffmpeg_raw_pcm(ts_file):
    """FFmpeg raw PCM - Extract 0.1s audio and analyze RMS"""
    start = time.perf_counter()
    
    try:
        cmd = [
            'ffmpeg',
            '-i', ts_file,
            '-t', '0.1',        # Duration
            '-f', 'f32le',      # Output raw float32 LE PCM (uncompressed, fast)
            '-ac', '1',         # Mono (faster)
            '-ar', '48000',     # Sample rate
            '-vn',              # No video
            '-'                 # Pipe to stdout
        ]
        
        result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=1)
        
        # Parse raw PCM data
        audio_data = np.frombuffer(result.stdout, dtype=np.float32)
        
        # Calculate RMS (Root Mean Square) for volume level
        if len(audio_data) > 0:
            rms = np.sqrt(np.mean(audio_data**2))
            # Convert RMS to dB (approximate)
            if rms > 0:
                mean_volume_db = 20 * np.log10(rms)
            else:
                mean_volume_db = -100.0
            
            has_audio = mean_volume_db > -50.0
        else:
            has_audio = False
            mean_volume_db = -100.0
        
        elapsed = (time.perf_counter() - start) * 1000
        
        return {
            'success': True,
            'has_audio': has_audio,
            'mean_volume_db': mean_volume_db,
            'time_ms': elapsed,
            'method': 'ffmpeg raw PCM',
            'samples': len(audio_data)
        }
    except Exception as e:
        elapsed = (time.perf_counter() - start) * 1000
        return {
            'success': False,
            'error': str(e),
            'time_ms': elapsed,
            'method': 'ffmpeg raw PCM'
        }


def print_result(filename, results):
    """Print test results"""
    print(f"\n{'='*80}")
    print(f"🔊 {filename}")
    print(f"{'='*80}")
    
    for i, result in enumerate(results, 1):
        method = result.get('method', 'Unknown')
        time_ms = result.get('time_ms', 0)
        
        if result.get('success'):
            has_audio = result.get('has_audio', False)
            status = '✅ AUDIO' if has_audio else '🔇 MUTE'
            mean_volume_db = result.get('mean_volume_db', -100.0)
            
            # Add extra info for some methods
            extra = ''
            if 'samples' in result:
                extra = f" | {result['samples']} samples"
            elif 'streams_found' in result:
                extra = f" | {result['streams_found']} streams"
            elif 'returncode' in result:
                extra = f" | rc={result['returncode']}"
            
            if mean_volume_db > -100:
                print(f"{i}. {method:20} ({time_ms:6.1f}ms) → {status} | {mean_volume_db:6.1f} dB{extra}")
            else:
                print(f"{i}. {method:20} ({time_ms:6.1f}ms) → {status}{extra}")
        else:
            error = result.get('error', 'Unknown error')
            print(f"{i}. {method:20} ({time_ms:6.1f}ms) → ❌ ERROR: {error}")


def main():
    """Test all methods on TS files in audio/ directory"""
    
    script_dir = Path(__file__).parent
    audio_dir = script_dir / 'audio'
    
    if not audio_dir.exists():
        print(f"❌ Error: Audio directory not found: {audio_dir}")
        return 1
    
    # Find all .ts files
    test_files = sorted(audio_dir.glob('*.ts'))
    
    if not test_files:
        print(f"❌ Error: No .ts files found in {audio_dir}")
        return 1
    
    print("\n" + "="*80)
    print("🚀 AUDIO DETECTION PERFORMANCE COMPARISON")
    print("="*80)
    print(f"Testing {len(test_files)} files from {audio_dir.name}/")
    print("\nMethods:")
    print("  1. ffprobe JSON       - JSON output (simple and reliable)")
    print("  2. ffprobe basic      - Current method (stream detection)")
    print("  3. ffprobe optimized  - With probesize/analyzeduration limits")
    print("  4. ffmpeg vol 0.1s    - FFmpeg volumedetect (0.1s sample)")
    print("  5. ffmpeg raw PCM     - FFmpeg raw audio + numpy RMS analysis")
    
    # Test each file
    all_results = {}
    
    for test_file in test_files:
        filename = test_file.name
        
        results = [
            test_ffprobe_json(str(test_file)),
            test_ffprobe_basic(str(test_file)),
            test_ffprobe_optimized(str(test_file)),
            test_ffmpeg_volumedetect_01s(str(test_file)),
            test_ffmpeg_raw_pcm(str(test_file))
        ]
        
        all_results[filename] = results
        print_result(filename, results)
    
    # Summary
    print(f"\n{'='*80}")
    print("📊 PERFORMANCE SUMMARY")
    print(f"{'='*80}")
    
    method_times = {}
    method_success = {}
    
    for filename, results in all_results.items():
        for result in results:
            method = result['method']
            if method not in method_times:
                method_times[method] = []
                method_success[method] = {'success': 0, 'failed': 0}
            
            if result.get('success'):
                method_times[method].append(result['time_ms'])
                method_success[method]['success'] += 1
            else:
                method_success[method]['failed'] += 1
    
    print("\nAverage execution times:")
    for method in ['ffprobe JSON', 'ffprobe basic', 'ffprobe optimized', 'ffmpeg vol 0.1s', 'ffmpeg raw PCM']:
        if method in method_times and method_times[method]:
            times = method_times[method]
            avg_time = sum(times) / len(times)
            min_time = min(times)
            max_time = max(times)
            success = method_success[method]['success']
            failed = method_success[method]['failed']
            
            print(f"  {method:20} {avg_time:6.1f}ms avg ({min_time:5.1f}-{max_time:5.1f}ms) | ✅ {success} ❌ {failed}")
    
    print(f"\n✅ Test complete!")
    return 0


if __name__ == '__main__':
    sys.exit(main())

