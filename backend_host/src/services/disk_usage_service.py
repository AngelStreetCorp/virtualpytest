"""
Disk Usage Analysis Service

Centralized service for analyzing disk usage across capture directories.
Provides clean, reusable business logic separated from HTTP routing.
"""

import os
import time
import subprocess
from typing import Dict, Any, List, Optional
from backend_host.src.lib.utils.system_info_utils import get_files_by_pattern
from shared.src.lib.utils.storage_path_utils import get_capture_base_directories, get_stream_base_path


class DiskUsageService:
    """Service for disk usage analysis and diagnostics"""
    
    @staticmethod
    def get_system_disk_info(path: str = None) -> Dict[str, Any]:
        """Get overall system disk usage for a path"""
        if path is None:
            path = get_stream_base_path()
        try:
            df_result = subprocess.run(
                ['df', '-h', path],
                capture_output=True, text=True, timeout=5
            )
            df_lines = df_result.stdout.strip().split('\n')
            if len(df_lines) >= 2:
                parts = df_lines[1].split()
                return {
                    'filesystem': parts[0],
                    'size': parts[1],
                    'used': parts[2],
                    'available': parts[3],
                    'use_percent': parts[4],
                    'mounted_on': parts[5] if len(parts) > 5 else path
                }
            return {'error': 'Failed to parse df output'}
        except Exception as e:
            return {'error': str(e)}
    
    @staticmethod
    def calculate_directory_size(directory: str) -> Dict[str, Any]:
        """
        Calculate total size of directory by summing all files.
        More accurate than du and consistent with file-by-file analysis.
        """
        if not os.path.exists(directory):
            return {'error': 'Directory does not exist'}
        
        try:
            total_bytes = 0
            file_count = 0
            
            for entry in os.scandir(directory):
                try:
                    if entry.is_file(follow_symlinks=False):
                        total_bytes += entry.stat().st_size
                        file_count += 1
                    elif entry.is_dir(follow_symlinks=False):
                        # Recursively scan subdirectories
                        subdir_result = DiskUsageService.calculate_directory_size(entry.path)
                        if 'total_bytes' in subdir_result:
                            total_bytes += subdir_result['total_bytes']
                            file_count += subdir_result['file_count']
                except (OSError, PermissionError):
                    continue
            
            return {
                'total_bytes': total_bytes,
                'file_count': file_count,
                'size_gb': round(total_bytes / (1024**3), 2),
                'size_mb': round(total_bytes / (1024**2), 1)
            }
        except Exception as e:
            return {'error': str(e)}
    
    @staticmethod
    def analyze_file_type(directory: str, pattern: str, exclude_pattern: Optional[str] = None) -> Dict[str, Any]:
        """Analyze files of a specific type in a directory"""
        try:
            files = get_files_by_pattern(directory, pattern, exclude_pattern=exclude_pattern)
            if files:
                sizes = [os.path.getsize(f) for f in files]
                total_bytes = sum(sizes)
                return {
                    'count': len(sizes),
                    'size_gb': round(total_bytes / (1024**3), 2),
                    'size_mb': round(total_bytes / (1024**2), 1),
                    'size_bytes': total_bytes,
                    'avg_size_kb': round(total_bytes / len(sizes) / 1024, 1) if sizes else 0
                }
            return {'count': 0, 'size_gb': 0, 'size_mb': 0}
        except Exception as e:
            return {'error': str(e)}
    
    @staticmethod
    def analyze_cleanup_health(capture_dir: str, captures_subdir: str, max_age_hours: int = 24) -> Dict[str, Any]:
        """Check for files older than specified age (cleanup failure indicator)"""
        try:
            cutoff_time = time.time() - (max_age_hours * 3600)
            
            # Segments older than cutoff
            old_segment_files = get_files_by_pattern(capture_dir, r'^segment_.*\.ts$', max_mtime=cutoff_time)
            old_segments_count = len(old_segment_files)
            
            # Captures older than cutoff
            old_capture_files = get_files_by_pattern(captures_subdir, r'^capture_.*\.jpg$', max_mtime=cutoff_time)
            old_captures_count = len(old_capture_files)
            
            is_healthy = old_segments_count == 0 and old_captures_count == 0
            
            return {
                'old_segments_24h': old_segments_count,
                'old_captures_24h': old_captures_count,
                'is_healthy': is_healthy,
                'warning': f'Files older than {max_age_hours}h found - cleanup may not be working' if not is_healthy else None
            }
        except Exception as e:
            return {'error': str(e)}
    
    @staticmethod
    def analyze_capture_directory(capture_dir: str) -> Dict[str, Any]:
        """Complete analysis of a single capture directory"""
        from shared.src.lib.utils.storage_path_utils import get_capture_storage_path
        
        capture_name = os.path.basename(capture_dir)
        # Use centralized storage path utilities for hot/cold architecture
        captures_subdir = get_capture_storage_path(capture_dir, 'captures')
        
        analysis = {
            'capture_name': capture_name,
            'path': capture_dir,
            'exists': os.path.exists(capture_dir)
        }
        
        if not analysis['exists']:
            return analysis
        
        # Calculate total size
        analysis['total_size'] = DiskUsageService.calculate_directory_size(capture_dir)
        
        # Analyze segments
        analysis['segments'] = DiskUsageService.analyze_file_type(
            capture_dir, 
            r'^segment_.*\.ts$'
        )
        
        # Analyze full-res captures
        analysis['captures'] = DiskUsageService.analyze_file_type(
            captures_subdir, 
            r'^capture_.*[0-9]\.jpg$',
            exclude_pattern=r'_thumbnail\.jpg$'
        )
        
        # Analyze thumbnails
        analysis['thumbnails'] = DiskUsageService.analyze_file_type(
            captures_subdir, 
            r'.*_thumbnail\.jpg$'
        )
        
        # Analyze JSON files
        analysis['json_files'] = DiskUsageService.analyze_file_type(
            captures_subdir, 
            r'.*\.json$'
        )
        
        # Analyze transcripts
        analysis['transcripts'] = DiskUsageService.analyze_file_type(
            capture_dir, 
            r'^transcript_.*\.json$'
        )
        
        # Cleanup health check
        analysis['cleanup_health'] = DiskUsageService.analyze_cleanup_health(
            capture_dir, 
            captures_subdir
        )
        
        return analysis
    
    @staticmethod
    def analyze_temp_files() -> Dict[str, Any]:
        """Check for temp file accumulation (leaked resources)"""
        try:
            # Audio extract temp directories
            temp_dirs = get_files_by_pattern('/tmp', r'^audio_extract_.*$')
            temp_dirs_count = len([d for d in temp_dirs if os.path.isdir(d)])
            
            # Old audio files (>60 min)
            cutoff = time.time() - 3600
            old_audio = get_files_by_pattern('/tmp', r'^audio_.*\.wav$', max_mtime=cutoff)
            old_audio_count = len(old_audio)
            
            # Old merged TS files (>60 min)
            old_merged = get_files_by_pattern('/tmp', r'^merged_ts_.*\.ts$', max_mtime=cutoff)
            old_merged_count = len(old_merged)
            
            is_healthy = temp_dirs_count == 0 and old_audio_count == 0 and old_merged_count == 0
            
            return {
                'leaked_temp_dirs': temp_dirs_count,
                'old_audio_files': old_audio_count,
                'old_merged_ts': old_merged_count,
                'is_healthy': is_healthy,
                'warning': 'Temp file accumulation detected' if not is_healthy else None
            }
        except Exception as e:
            return {'error': str(e)}
    
    @staticmethod
    def get_cleanup_status() -> Dict[str, Any]:
        """Check cleanup process status"""
        status = {}
        try:
            # Check cleanup log
            if os.path.exists('/tmp/clean.log'):
                with open('/tmp/clean.log', 'r') as f:
                    lines = f.read().strip().split('\n')
                    status['log_exists'] = True
                    status['last_run'] = lines[0] if lines else None
                    status['log_lines'] = len(lines)
            else:
                status['log_exists'] = False
                status['warning'] = 'Cleanup log not found'
            
            # Check active cleanup processes
            ps_result = subprocess.run(
                ['ps', 'aux'],
                capture_output=True, text=True, timeout=5
            )
            cleanup_processes = [
                l for l in ps_result.stdout.split('\n') 
                if 'clean_captures' in l and 'grep' not in l
            ]
            status['active_processes'] = len(cleanup_processes)
            
        except Exception as e:
            status['error'] = str(e)
        
        return status
    
    @staticmethod
    def get_config_status() -> Dict[str, Any]:
        """Check active captures configuration (CSV format: directory,pid,quality)"""
        try:
            from shared.src.lib.utils.storage_path_utils import parse_active_captures_conf
            
            config_entries = parse_active_captures_conf()
            
            if config_entries:
                return {
                    'exists': True,
                    'configured_captures': config_entries,
                    'count': len(config_entries)
                }
            
            return {
                'exists': False,
                'warning': 'Config file missing'
            }
        except Exception as e:
            return {'error': str(e)}
    
    @staticmethod
    def get_complete_diagnostics(capture_filter: str = 'all') -> Dict[str, Any]:
        """
        Complete disk usage diagnostics for all or specific capture directories.
        
        Args:
            capture_filter: 'all' for all captures, or specific capture name (e.g., 'capture1')
        
        Returns:
            Complete diagnostics report
        """
        if capture_filter == 'all':
            capture_dirs = get_capture_base_directories()
        else:
            from shared.src.lib.utils.storage_path_utils import get_device_base_path
            capture_dirs = [get_device_base_path(capture_filter)]
        
        capture_dirs = [d for d in capture_dirs if os.path.exists(d)]
        
        if not capture_dirs:
            return {
                'success': False,
                'error': 'No capture directories found'
            }
        
        # System disk info
        system_disk = DiskUsageService.get_system_disk_info()
        
        # Analyze each capture directory
        captures_analysis = [
            DiskUsageService.analyze_capture_directory(capture_dir)
            for capture_dir in capture_dirs
        ]
        
        # Cleanup and config status
        cleanup_status = DiskUsageService.get_cleanup_status()
        config_status = DiskUsageService.get_config_status()
        temp_files_status = DiskUsageService.analyze_temp_files()
        
        # Build summary
        total_segments = sum(c.get('segments', {}).get('count', 0) for c in captures_analysis)
        total_captures = sum(c.get('captures', {}).get('count', 0) for c in captures_analysis)
        total_thumbnails = sum(c.get('thumbnails', {}).get('count', 0) for c in captures_analysis)
        
        # Collect warnings
        warnings = []
        for c in captures_analysis:
            if c.get('cleanup_health', {}).get('warning'):
                warnings.append(c['cleanup_health']['warning'])
        
        if config_status.get('warning'):
            warnings.append(config_status['warning'])
        
        if temp_files_status.get('warning'):
            warnings.append(temp_files_status['warning'])
        
        return {
            'success': True,
            'system_disk': system_disk,
            'summary': {
                'captures_analyzed': len(captures_analysis),
                'total_segments': total_segments,
                'total_captures': total_captures,
                'total_thumbnails': total_thumbnails,
                'cleanup_healthy': all(
                    c.get('cleanup_health', {}).get('is_healthy', False) 
                    for c in captures_analysis
                ),
                'temp_files_healthy': temp_files_status.get('is_healthy', False)
            },
            'captures': captures_analysis,
            'cleanup_status': cleanup_status,
            'config_status': config_status,
            'temp_files_status': temp_files_status,
            'warnings': warnings if warnings else []
        }

