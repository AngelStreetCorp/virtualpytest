#!/usr/bin/env python3

"""
Video Compression Utilities for VirtualPyTest

Wrapper for shared video_utils - provides backward compatibility
"""

import os
import time
import logging
from typing import Optional, Dict, List, Tuple
from shared.src.lib.utils.video_utils import compress_video_segments

logger = logging.getLogger(__name__)

class VideoCompressionUtils:
    """Utilities for compressing video files before upload."""
    
    @staticmethod
    def compress_hls_to_mp4(
        m3u8_path: str,
        segment_files: List[Tuple[str, str]],
        output_path: str = None,
        compression_level: str = "medium"
    ) -> Dict[str, any]:
        """
        Convert HLS segments to a single compressed MP4.
        Uses shared video_utils for actual compression.
        
        Args:
            m3u8_path: Path to M3U8 playlist file (not used, kept for compatibility)
            segment_files: List of (segment_name, segment_path) tuples
            output_path: Output MP4 path (auto-generated if None)
            compression_level: "fast", "medium", "high", "low", "pi_optimized"
            
        Returns:
            Dict with success status, output path, and compression stats
        """
        if output_path is None:
            timestamp = int(time.time())
            output_path = f"/tmp/compressed_video_{timestamp}.mp4"
        
        logger.info(f"Compressing {len(segment_files)} HLS segments to MP4...")
        
        result = compress_video_segments(segment_files, output_path, compression_level)
        
        if result.get('success'):
            logger.info(f"Compression complete:")
            logger.info(f"  Original: {result['original_size'] / 1024 / 1024:.1f} MB ({result['segments_count']} segments)")
            logger.info(f"  Compressed: {result['compressed_size'] / 1024 / 1024:.1f} MB (1 file)")
            logger.info(f"  Savings: {result['compression_ratio']:.1f}%")
        else:
            logger.error(f"Compression failed: {result.get('error')}")
        
        return result
    
    @staticmethod
    def estimate_compression_time(segment_count: int, duration_seconds: float) -> float:
        """
        Estimate compression time based on segment count and duration.
        
        Args:
            segment_count: Number of HLS segments
            duration_seconds: Total video duration
            
        Returns:
            Estimated compression time in seconds
        """
        # Rough estimate: ~0.1x realtime for medium compression
        # (3 minutes of video = ~18 seconds compression time)
        base_time = duration_seconds * 0.1
        
        # Add overhead for segment processing
        segment_overhead = segment_count * 0.05  # 50ms per segment
        
        return base_time + segment_overhead
    
    @staticmethod
    def cleanup_segments_after_compression(segment_files: List[Tuple[str, str]]) -> int:
        """
        DEPRECATED: Do not clean up HLS segments - they're needed for live streaming.
        This function is kept for compatibility but does nothing.
        
        Args:
            segment_files: List of (segment_name, segment_path) tuples
            
        Returns:
            Always returns 0 (no files deleted)
        """
        logger.info("Segment cleanup skipped - HLS segments preserved for live streaming")
        return 0

def compress_video_for_upload(
    m3u8_path: str,
    segment_files: List[Tuple[str, str]],
    compression_level: str = "medium"
) -> Optional[str]:
    """
    Convenience function to compress HLS video for upload.
    
    Args:
        m3u8_path: Path to M3U8 playlist
        segment_files: List of segment files
        compression_level: Compression quality level
        
    Returns:
        Path to compressed MP4 file, or None if failed
    """
    compressor = VideoCompressionUtils()
    result = compressor.compress_hls_to_mp4(
        m3u8_path=m3u8_path,
        segment_files=segment_files,
        compression_level=compression_level
    )
    
    if result['success']:
        logger.info(f"Video compressed successfully: {result['compression_ratio']:.1f}% savings")
        return result['output_path']
    else:
        logger.error(f"Video compression failed: {result['error']}")
        return None
