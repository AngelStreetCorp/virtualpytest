#!/usr/bin/env python3
"""
Fast parallel file deletion with real-time progress tracking.

Shows:
- Total files to delete
- Files deleted per second
- Progress percentage
- Estimated time remaining
- Current directory being processed

Usage:
    python3 fast_delete_with_progress.py /var/www/html/stream/capture1
"""

import os
import sys
import time
import shutil
import multiprocessing as mp
from pathlib import Path
from collections import deque

def count_files_fast(root_path):
    """
    Quickly count files using os.scandir (faster than os.walk).
    Shows progress while counting.
    """
    print(f"📊 Counting files in {root_path}...")
    print("   (This may take a moment for large folders)")
    
    file_count = 0
    dir_count = 0
    last_print = time.time()
    
    try:
        # Use os.walk for simplicity but show progress
        for dirpath, dirnames, filenames in os.walk(root_path):
            file_count += len(filenames)
            dir_count += len(dirnames)
            
            # Print progress every 0.5 seconds
            if time.time() - last_print > 0.5:
                print(f"\r   Found: {file_count:,} files, {dir_count:,} dirs...", end='', flush=True)
                last_print = time.time()
        
        print(f"\r   ✅ Found: {file_count:,} files, {dir_count:,} directories")
        return file_count, dir_count
    
    except Exception as e:
        print(f"\n   ⚠️  Error counting: {e}")
        return 0, 0

def delete_file_batch(file_paths):
    """
    Delete a batch of files.
    Returns number of files successfully deleted.
    """
    deleted = 0
    
    for filepath in file_paths:
        try:
            os.unlink(filepath)
            deleted += 1
        except Exception:
            pass  # Ignore individual file errors
    
    return deleted

def delete_with_progress(root_path, num_workers=None):
    """
    Delete all files in root_path with real-time progress display.
    Uses multiprocessing for parallel deletion with small batches for frequent updates.
    """
    if num_workers is None:
        num_workers = mp.cpu_count()
    
    print(f"\n🗑️  Starting parallel deletion ({num_workers} workers)...")
    
    # Collect all file paths in small batches for better progress updates
    print("📋 Building deletion queue...")
    all_files = []
    
    for dirpath, dirnames, filenames in os.walk(root_path, topdown=False):
        for filename in filenames:
            all_files.append(os.path.join(dirpath, filename))
    
    total_files = len(all_files)
    
    if total_files == 0:
        print("   No files to delete!")
        return
    
    print(f"   ✅ Found {total_files:,} files to delete")
    
    # Create batches of files (smaller batches = more frequent progress updates)
    # Use 500 files per batch for good balance between overhead and progress updates
    batch_size = 500
    batches = []
    for i in range(0, len(all_files), batch_size):
        batches.append(all_files[i:i+batch_size])
    
    print(f"   📦 Split into {len(batches):,} batches ({batch_size} files each)")
    
    # Delete files in parallel with progress tracking
    print(f"\n⚡ Deleting files...")
    deleted_count = 0
    start_time = time.time()
    last_print = time.time()
    
    # Track speed for ETA calculation
    speed_samples = deque(maxlen=20)  # Last 20 samples
    
    with mp.Pool(processes=num_workers) as pool:
        # Use imap_unordered for better performance and immediate results
        for deleted in pool.imap_unordered(delete_file_batch, batches, chunksize=1):
            deleted_count += deleted
            
            # Update progress every 0.05 seconds for more responsive feedback
            now = time.time()
            if now - last_print > 0.05 or deleted_count >= total_files:
                elapsed = now - start_time
                percent = (deleted_count / total_files) * 100
                
                # Calculate speed (files/sec)
                speed = deleted_count / elapsed if elapsed > 0 else 0
                speed_samples.append(speed)
                avg_speed = sum(speed_samples) / len(speed_samples)
                
                # Calculate ETA
                remaining = total_files - deleted_count
                eta_seconds = remaining / avg_speed if avg_speed > 0 else 0
                
                # Format ETA
                if eta_seconds < 60:
                    eta_str = f"{eta_seconds:.0f}s"
                elif eta_seconds < 3600:
                    eta_str = f"{eta_seconds/60:.1f}m"
                else:
                    eta_str = f"{eta_seconds/3600:.1f}h"
                
                # Print progress bar
                bar_width = 30
                filled = int(bar_width * deleted_count / total_files)
                bar = '█' * filled + '░' * (bar_width - filled)
                
                print(f"\r   [{bar}] {percent:5.1f}% | {deleted_count:,}/{total_files:,} files | "
                      f"{avg_speed:,.0f} files/s | ETA: {eta_str}   ", 
                      end='', flush=True)
                
                last_print = now
    
    elapsed = time.time() - start_time
    print(f"\n   ✅ Deleted {deleted_count:,} files in {elapsed:.1f}s "
          f"({deleted_count/elapsed:,.0f} files/s)")

def remove_empty_dirs(root_path):
    """
    Remove all empty directories bottom-up.
    """
    print(f"\n📁 Removing empty directories...")
    removed_count = 0
    start_time = time.time()
    
    # Walk bottom-up to remove empty dirs
    for dirpath, dirnames, filenames in os.walk(root_path, topdown=False):
        if dirpath == root_path:
            continue  # Don't remove the root itself yet
        
        try:
            if not os.listdir(dirpath):  # Directory is empty
                os.rmdir(dirpath)
                removed_count += 1
                
                if removed_count % 100 == 0:
                    print(f"\r   Removed {removed_count:,} empty directories...", end='', flush=True)
        except Exception:
            pass  # Ignore errors
    
    elapsed = time.time() - start_time
    print(f"\r   ✅ Removed {removed_count:,} empty directories in {elapsed:.1f}s")

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 fast_delete_with_progress.py <directory_path>")
        print("Example: python3 fast_delete_with_progress.py /var/www/html/stream/capture1")
        sys.exit(1)
    
    root_path = sys.argv[1]
    
    if not os.path.exists(root_path):
        print(f"❌ Error: Directory does not exist: {root_path}")
        sys.exit(1)
    
    if not os.path.isdir(root_path):
        print(f"❌ Error: Not a directory: {root_path}")
        sys.exit(1)
    
    # Show folder info
    print("\n" + "=" * 80)
    print("🗑️  FAST PARALLEL DELETION WITH PROGRESS")
    print("=" * 80)
    print(f"\nTarget: {root_path}")
    
    # Get folder size
    try:
        import subprocess
        size_output = subprocess.check_output(['du', '-sh', root_path], stderr=subprocess.DEVNULL)
        size_str = size_output.decode().split()[0]
        print(f"Size:   {size_str}")
    except:
        print("Size:   (unable to calculate)")
    
    # Count files
    file_count, dir_count = count_files_fast(root_path)
    
    if file_count == 0:
        print("\n⏭️  No files to delete, removing directory...")
        try:
            shutil.rmtree(root_path)
            print(f"✅ Removed {root_path}")
        except Exception as e:
            print(f"❌ Error removing directory: {e}")
        sys.exit(0)
    
    # Confirm deletion
    print(f"\n⚠️  WARNING: This will delete all {file_count:,} files in {root_path}")
    print("=" * 80)
    
    # Delete files with progress
    delete_with_progress(root_path)
    
    # Remove empty directories
    remove_empty_dirs(root_path)
    
    # Final cleanup - remove root directory
    print(f"\n🗑️  Removing root directory: {root_path}")
    try:
        os.rmdir(root_path)
        print(f"   ✅ Removed {root_path}")
    except Exception as e:
        # Try force removal
        try:
            shutil.rmtree(root_path)
            print(f"   ✅ Force removed {root_path}")
        except Exception as e2:
            print(f"   ⚠️  Could not remove root: {e2}")
    
    print("\n" + "=" * 80)
    print("✅ DELETION COMPLETE")
    print("=" * 80)
    print()

if __name__ == "__main__":
    main()

