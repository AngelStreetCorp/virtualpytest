"""
Frame Metadata Utilities

Shared utilities for writing action metadata to frame JSON files.
This enables automatic zap measurement by correlating actions with captured frames.
"""

import os
import json
import time
import logging
from datetime import datetime
from typing import Dict, Any, Optional
from shared.src.lib.utils.storage_path_utils import get_metadata_path, get_capture_folder
from shared.src.lib.utils.file_lock_utils import lock_file, unlock_file

# Get capture monitor logger for frame JSON operations
logger = logging.getLogger('capture_monitor')


def write_action_to_frame_json(device, action: Dict[str, Any], action_completion_timestamp: float):
    """
    Write action metadata to last_action.json for zapping detection (CRITICAL).
    Optionally enriches frame JSON files if they exist (NICE-TO-HAVE).
    
    ✅ CRITICAL PATH: Writes last_action.json for capture_monitor to detect zapping
    ✅ OPTIONAL PATH: Adds action metadata to recent frame JSONs (requires FFmpeg + capture_monitor)
    
    Non-blocking - failures are logged but don't affect action success.
    
    Args:
        device: Device instance with get_capture_dir() method
        action: Action dictionary with 'command' and 'params' keys
        action_completion_timestamp: Unix timestamp when action completed
    """
    try:
        # Get capture_folder from device
        # Device has capture_dir attribute like '/var/www/html/stream/capture1'
        capture_dir = device.get_capture_dir('captures')
        if not capture_dir:
            return  # No capture directory configured
        
        # Extract capture_folder name (e.g., 'capture1')
        capture_folder = get_capture_folder(capture_dir)
        
        # ✅ STORE ACTION IN DEVICE STATE (in-memory for fast zapping detection)
        # ✅ INTER-PROCESS COMMUNICATION via last_action.json
        # capture_monitor.py runs as SEPARATE PROCESS - can't share device_state memory
        # Write to single last_action.json file (same pattern as last_zapping.json)
        
        metadata_path = get_metadata_path(capture_folder)
        
        if not os.path.exists(metadata_path):
            return  # No metadata directory yet
        
        # ✅ WRITE last_action.json (instant read for capture_monitor)
        # ✅ ATOMIC WRITE: Write to .tmp first, then rename (prevents partial reads)
        try:
            last_action_path = os.path.join(metadata_path, 'last_action.json')
            last_action_tmp_path = last_action_path + '.tmp'
            last_action_data = {
                'command': action.get('command'),
                'timestamp': action_completion_timestamp,
                'params': action.get('params', {}),
                'written_at': datetime.utcnow().isoformat() + 'Z'
            }
            
            # Write to temp file first
            with open(last_action_tmp_path, 'w') as f:
                json.dump(last_action_data, f, indent=2)
                f.flush()  # Flush to OS buffer
                os.fsync(f.fileno())  # Sync to disk (ensures data is written)
            
            # Windows-safe atomic overwrite (os.rename fails if destination exists)
            os.replace(last_action_tmp_path, last_action_path)
            
        except Exception as e:
            print(f"[@frame_metadata_utils:write_action_to_frame_json] ❌ Failed to write last_action.json: {e}")
            import traceback
            traceback.print_exc()
        
        # ═══════════════════════════════════════════════════════════════════════════════
        # OPTIONAL: Enrich frame JSON files (if they exist)
        # ═══════════════════════════════════════════════════════════════════════════════
        # This section adds action metadata to recent capture_*.json files for historical
        # analysis. This is OPTIONAL - zapping detection works via last_action.json above.
        # Frame JSONs are created by capture_monitor when FFmpeg captures video frames.
        # ═══════════════════════════════════════════════════════════════════════════════
        
        # Get last 5 JSON files by mtime (fastest approach - uses cached stat)
        json_files = []
        with os.scandir(metadata_path) as entries:
            for entry in entries:
                if entry.name.startswith('capture_') and entry.name.endswith('.json'):
                    json_files.append((entry.path, entry.stat().st_mtime))
        
        if not json_files:
            return  # No JSON files yet - but last_action.json was written successfully
        
        # Sort by mtime (newest first) and take top 5
        json_files.sort(key=lambda x: x[1], reverse=True)
        last_5_files = [path for path, _ in json_files[:5]]
        
        # Find JSON with timestamp closest to action_completion_timestamp
        best_match_file = None
        min_delta = float('inf')
        
        for json_file in last_5_files:
            try:
                with open(json_file, 'r') as f:
                    data = json.load(f)
                
                frame_timestamp_str = data.get('timestamp')
                if not frame_timestamp_str:
                    continue
                
                # Handle both ISO format with and without Z suffix
                frame_timestamp = datetime.fromisoformat(frame_timestamp_str.replace('Z', '+00:00')).timestamp()
                delta = abs(frame_timestamp - action_completion_timestamp)
                
                if delta < min_delta:
                    min_delta = delta
                    best_match_file = json_file
            except Exception:
                # Skip files that can't be read or parsed (silent)
                continue
        
        # Update matching JSON if within 1500ms tolerance
        # Frames are written every 1s, so we need tolerance > 1000ms
        if best_match_file and min_delta < 1.5:
            lock_path = best_match_file + '.lock'
            try:
                with open(lock_path, 'w') as lock_fh:
                    lock_file(lock_fh, exclusive=True)
                    try:
                        # Read current data
                        with open(best_match_file, 'r') as f:
                            data = json.load(f)
                        
                        # Add action metadata
                        data['last_action_executed'] = action.get('command')
                        data['last_action_timestamp'] = action_completion_timestamp
                        data['action_params'] = action.get('params', {})
                        
                        # Calculate action-to-frame delay
                        frame_timestamp_str = data.get('timestamp')
                        if frame_timestamp_str:
                            frame_timestamp = datetime.fromisoformat(frame_timestamp_str.replace('Z', '+00:00')).timestamp()
                            data['action_to_frame_delay_ms'] = int((frame_timestamp - action_completion_timestamp) * 1000)
                        
                        # Atomic write
                        with open(best_match_file + '.tmp', 'w') as f:
                            json.dump(data, f, indent=2)
                        # Windows-safe atomic overwrite (os.rename fails if destination exists)
                        os.replace(best_match_file + '.tmp', best_match_file)
                        
                        # Log to capture_monitor with prominent visual separators
                        logger.info("=" * 80)
                        logger.info("🎬 ACTION TIMESTAMP WRITTEN TO FRAME JSON")
                        logger.info("-" * 80)
                        logger.info(f"📁 File: {os.path.basename(best_match_file)}")
                        logger.info(f"⚡ Action: {action.get('command')}")
                        logger.info(f"⏱️  Timestamp: {action_completion_timestamp}")
                        logger.info(f"🎯 Delta: {int(min_delta*1000)}ms (tolerance: 1500ms)")
                        logger.info(f"📋 Params: {action.get('params', {})}")
                        logger.info("=" * 80)
                    finally:
                        unlock_file(lock_fh)
                
                # Clean up lock file
                try:
                    os.remove(lock_path)
                except:
                    pass
                    
            except Exception as e:
                pass  # Failure is silent - frame enrichment is optional
    
    except Exception as e:
        # Non-blocking - log error but don't fail action execution
        print(f"[@frame_metadata_utils:write_action_to_frame_json] Error writing to frame JSON: {e}")
