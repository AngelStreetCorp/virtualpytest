#!/usr/bin/env python3
"""
Test script for freeze detection optimization
Tests dHash-based freeze detection on sample images

Usage:
    python3 test_freeze.py
    
Expected:
    - freeze1.jpg and freeze2.jpg should match (frozen)
    - freeze1.jpg and freeze3.jpg should NOT match (different content)
"""

import cv2
import numpy as np
import os
import sys
import time
from pathlib import Path


def compute_dhash(image, hash_size=8):
    """
    Compute dHash (difference hash) for an image
    Fast perceptual hash for comparing images
    """
    # Resize to hash_size+1 x hash_size (grayscale)
    if len(image.shape) == 3:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    else:
        gray = image
    
    resized = cv2.resize(gray, (hash_size + 1, hash_size), interpolation=cv2.INTER_AREA)
    
    # Compute horizontal gradient (diff between adjacent pixels)
    diff = resized[:, 1:] > resized[:, :-1]
    
    # Flatten to 1D hash
    return diff.flatten()


def compare_images_dhash(img1, img2, hash_size=8):
    """
    Compare two images using dHash (NEW METHOD)
    Returns: hamming distance percentage (0% = identical, 100% = completely different)
    """
    hash1 = compute_dhash(img1, hash_size)
    hash2 = compute_dhash(img2, hash_size)
    
    # Hamming distance = count of differing bits
    hamming = np.sum(hash1 != hash2)
    total_bits = len(hash1)
    
    # Convert to percentage
    diff_percentage = (hamming / total_bits) * 100
    
    return diff_percentage, hamming, total_bits


def compare_images_pixel_diff(img1, img2):
    """
    Compare two images using pixel difference (OLD METHOD)
    Returns: difference percentage based on pixel-by-pixel comparison
    """
    # Convert to grayscale if needed
    if len(img1.shape) == 3:
        gray1 = cv2.cvtColor(img1, cv2.COLOR_BGR2GRAY)
    else:
        gray1 = img1
    
    if len(img2.shape) == 3:
        gray2 = cv2.cvtColor(img2, cv2.COLOR_BGR2GRAY)
    else:
        gray2 = img2
    
    # Resize to same size if needed (for fair comparison)
    if gray1.shape != gray2.shape:
        gray2 = cv2.resize(gray2, (gray1.shape[1], gray1.shape[0]))
    
    # Compute absolute difference
    diff = cv2.absdiff(gray1, gray2)
    
    # Count pixels with difference > 10 (threshold for "different")
    different_pixels = np.sum(diff > 10)
    total_pixels = diff.size
    
    # Convert to percentage
    diff_percentage = (different_pixels / total_pixels) * 100
    
    return diff_percentage, different_pixels, total_pixels


def test_freeze_detection_both_methods(images, threshold=5.0):
    """
    Test freeze detection using BOTH old and new methods for comparison
    
    Args:
        images: List of (name, cv2_image) tuples
        threshold: Difference threshold (default 5.0%)
    
    Returns:
        Results dictionary with both methods
    """
    if len(images) < 2:
        return {'error': 'Need at least 2 images to compare'}
    
    results = []
    
    # Compare each image with all previous images using BOTH methods
    for i in range(1, len(images)):
        current_name, current_img = images[i]
        
        comparisons = []
        frozen_dhash = True
        frozen_pixel = True
        
        for j in range(i):
            prev_name, prev_img = images[j]
            
            # NEW METHOD: dHash
            start = time.perf_counter()
            dhash_pct, hamming, total_bits = compare_images_dhash(current_img, prev_img)
            dhash_time = (time.perf_counter() - start) * 1000
            
            if dhash_pct > threshold:
                frozen_dhash = False
            
            # OLD METHOD: Pixel difference
            start = time.perf_counter()
            pixel_pct, diff_pixels, total_pixels = compare_images_pixel_diff(current_img, prev_img)
            pixel_time = (time.perf_counter() - start) * 1000
            
            if pixel_pct > threshold:
                frozen_pixel = False
            
            comparisons.append({
                'prev_image': prev_name,
                'dhash': {
                    'diff_percentage': dhash_pct,
                    'hamming_distance': hamming,
                    'total_bits': total_bits,
                    'time_ms': dhash_time,
                    'match': dhash_pct <= threshold
                },
                'pixel_diff': {
                    'diff_percentage': pixel_pct,
                    'different_pixels': diff_pixels,
                    'total_pixels': total_pixels,
                    'time_ms': pixel_time,
                    'match': pixel_pct <= threshold
                }
            })
        
        results.append({
            'image': current_name,
            'frozen_dhash': frozen_dhash,
            'frozen_pixel': frozen_pixel,
            'comparisons': comparisons
        })
    
    return {
        'results': results,
        'threshold': threshold
    }


def print_results(test_results):
    """Print test results in clean format - comparing OLD vs NEW methods"""
    
    if 'error' in test_results:
        print(f"❌ Error: {test_results['error']}")
        return
    
    print(f"\n{'='*80}")
    print(f"🧊 FREEZE DETECTION COMPARISON: OLD vs NEW")
    print(f"{'='*80}")
    print(f"Threshold: {test_results['threshold']:.1f}% difference")
    print(f"OLD: Pixel difference (cv2.absdiff)")
    print(f"NEW: dHash (perceptual hashing)")
    
    total_dhash_time = 0
    total_pixel_time = 0
    total_comparisons = 0
    
    for result in test_results['results']:
        image_name = result['image']
        frozen_dhash = result['frozen_dhash']
        frozen_pixel = result['frozen_pixel']
        
        status_dhash = '🧊 FROZEN' if frozen_dhash else '✅ MOVING'
        status_pixel = '🧊 FROZEN' if frozen_pixel else '✅ MOVING'
        
        # Check if methods agree
        agreement = '✅ AGREE' if frozen_dhash == frozen_pixel else '⚠️ DISAGREE'
        
        print(f"\n{'─'*80}")
        print(f"📸 {image_name}")
        print(f"   OLD: {status_pixel} | NEW: {status_dhash} | {agreement}")
        print(f"{'─'*80}")
        
        for comp in result['comparisons']:
            prev_img = comp['prev_image']
            
            # dHash results
            dhash = comp['dhash']
            dhash_pct = dhash['diff_percentage']
            dhash_time = dhash['time_ms']
            dhash_match = dhash['match']
            dhash_icon = '✓' if dhash_match else '✗'
            
            # Pixel diff results
            pixel = comp['pixel_diff']
            pixel_pct = pixel['diff_percentage']
            pixel_time = pixel['time_ms']
            pixel_match = pixel['match']
            pixel_icon = '✓' if pixel_match else '✗'
            
            # Speedup calculation
            speedup = pixel_time / dhash_time if dhash_time > 0 else 0
            
            print(f"  vs {prev_img}:")
            print(f"    OLD {pixel_icon}: {pixel_pct:6.2f}% diff | {pixel_time:6.2f}ms")
            print(f"    NEW {dhash_icon}: {dhash_pct:6.2f}% diff | {dhash_time:6.2f}ms | {speedup:.1f}x faster")
            
            total_dhash_time += dhash_time
            total_pixel_time += pixel_time
            total_comparisons += 1
    
    # Summary
    print(f"\n{'='*80}")
    print(f"📊 PERFORMANCE SUMMARY")
    print(f"{'='*80}")
    
    if total_comparisons > 0:
        avg_dhash = total_dhash_time / total_comparisons
        avg_pixel = total_pixel_time / total_comparisons
        overall_speedup = total_pixel_time / total_dhash_time if total_dhash_time > 0 else 0
        
        print(f"Total comparisons: {total_comparisons}")
        print(f"\nOLD (Pixel diff):")
        print(f"  Total time: {total_pixel_time:.2f}ms")
        print(f"  Average per comparison: {avg_pixel:.2f}ms")
        
        print(f"\nNEW (dHash):")
        print(f"  Total time: {total_dhash_time:.2f}ms")
        print(f"  Average per comparison: {avg_dhash:.2f}ms")
        
        print(f"\n🚀 SPEEDUP: {overall_speedup:.1f}x faster with dHash!")
        
        # Production impact
        print(f"\n💡 Production impact (3 frame comparison):")
        print(f"  OLD: {avg_pixel * 3:.1f}ms per freeze check")
        print(f"  NEW: {avg_dhash * 3:.1f}ms per freeze check")
        print(f"  Savings: {(avg_pixel - avg_dhash) * 3:.1f}ms per check")


def main():
    """Test freeze detection on images in img/freeze/ folder"""
    
    # Get script directory
    script_dir = Path(__file__).parent
    img_dir = script_dir / 'img' / 'freeze'
    
    if not img_dir.exists():
        print(f"❌ Error: Image directory not found: {img_dir}")
        return 1
    
    print("\n" + "="*80)
    print("🚀 FREEZE DETECTION TEST: OLD vs NEW")
    print("="*80)
    print(f"Testing images from: {img_dir}")
    print("\nComparing two methods:")
    print("  OLD: Pixel difference (cv2.absdiff) - checks every pixel")
    print("  NEW: dHash (perceptual hashing) - fast perceptual comparison")
    print("\nThreshold: 5.0% difference")
    print("  < 5%  = Images match (frozen)")
    print("  > 5%  = Images differ (moving)")
    print("\n⚠️  For accurate results, use thumbnail-sized images (320x180)")
    print("    Production uses thumbnails, not full-resolution images!")
    
    # Find all *.jpg images in freeze folder
    freeze_images = sorted(img_dir.glob('*.jpg'))
    
    if not freeze_images:
        print(f"\n❌ Error: No .jpg images found in {img_dir}")
        print("   Expected: almost_freeze1.jpg, almost_freeze2.jpg, etc.")
        return 1
    
    print(f"\nFound {len(freeze_images)} freeze images:")
    for img_path in freeze_images:
        print(f"  - {img_path.name}")
    
    # Load images (use as-is, should be thumbnails for fair comparison)
    loaded_images = []
    for img_path in freeze_images:
        img = cv2.imread(str(img_path))
        if img is None:
            print(f"⚠️  Warning: Failed to load {img_path.name}")
            continue
        
        loaded_images.append((img_path.name, img))
        print(f"  → Loaded: {img_path.name} ({img.shape[1]}x{img.shape[0]})")
    
    if len(loaded_images) < 2:
        print(f"\n❌ Error: Need at least 2 images to test freeze detection")
        return 1
    
    # Test freeze detection with BOTH methods
    test_results = test_freeze_detection_both_methods(loaded_images, threshold=5.0)
    
    # Print results
    print_results(test_results)
    
    print(f"\n✅ Test complete!")
    return 0


if __name__ == '__main__':
    sys.exit(main())

