#!/usr/bin/env python3
"""
Simple blackscreen + banner detection test
Fast sampling + edge detection only

Tests images from:
- img/zap/ - Expected to detect zapping (blackscreen + banner)
- img/blackscreen/ - Expected to detect false positives (blackscreen but no banner)
"""

import cv2
import numpy as np
import sys
import os
import time
from pathlib import Path

def analyze_blackscreen(image_path, threshold=5, verbose=True):
    """Analyze blackscreen with edge-based banner detection"""
    
    # Read image
    img = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
    if img is None:
        if verbose:
            print(f"❌ Error: Could not read image: {image_path}")
        return None
    
    img_height, img_width = img.shape
    is_thumbnail = '_thumbnail' in image_path or img_width < 1000
    
    # Split into top 70% (content) and bottom 30% (banner)
    split_y = int(img_height * 0.7)
    top_region = img[0:split_y, :]
    banner_region = img[split_y:img_height, :]
    
    # === STEP 1: Blackscreen Detection (Fast Sampling) ===
    start = time.perf_counter()
    total_pixels = top_region.shape[0] * top_region.shape[1]
    
    # Sample every 3rd pixel (11% of pixels)
    sample = top_region[::3, ::3]
    sample_dark = np.sum(sample <= threshold)
    sample_total = sample.shape[0] * sample.shape[1]
    dark_percentage = (sample_dark / sample_total) * 100
    
    # Full scan only if edge case (70-90%)
    if 70 <= dark_percentage <= 90:
        dark_pixels = np.sum(top_region <= threshold)
        dark_percentage = (dark_pixels / total_pixels) * 100
        pixels_checked = total_pixels
        method = "FULL"
    else:
        pixels_checked = sample_total
        method = "SAMPLE"
    
    blackscreen_time = (time.perf_counter() - start) * 1000
    is_black = dark_percentage > 85
    
    # === STEP 2: Banner Detection (Edge Detection) ===
    start = time.perf_counter()
    edges = cv2.Canny(banner_region, 50, 150)
    edge_density = np.sum(edges > 0) / edges.size * 100
    has_banner = 3 < edge_density < 20
    banner_time = (time.perf_counter() - start) * 1000
    
    # === FINAL DECISION ===
    is_zapping = is_black and has_banner
    
    # === PRINT RESULTS ===
    if verbose:
        print(f"\n🔍 Image: {os.path.basename(image_path)}")
        print(f"   Size: {img_width}x{img_height} ({'thumbnail' if is_thumbnail else 'full-res'})")
        print()
        
        print(f"⬛ BLACKSCREEN CHECK (top 70%)")
        print(f"   Time: {blackscreen_time:.2f}ms [{method}]")
        print(f"   Pixels: {pixels_checked:,} of {total_pixels:,}")
        print(f"   Dark: {dark_percentage:.1f}% → {'✅ BLACK' if is_black else '❌ NOT BLACK'}")
        print()
        
        print(f"📊 BANNER CHECK (bottom 30%)")
        print(f"   Time: {banner_time:.2f}ms [EDGES]")
        print(f"   Edges: {edge_density:.1f}% → {'✅ DETECTED' if has_banner else '❌ NOT DETECTED'}")
        print()
        
        print(f"{'='*50}")
        if is_zapping:
            print(f"  RESULT: 🎯 ZAPPING BLACKSCREEN")
        elif is_black:
            print(f"  RESULT: ⬛ BLACK (no banner - false positive)")
        else:
            print(f"  RESULT: 📺 CONTENT")
        print(f"{'='*50}")
        print()
    
    return {
        'is_zapping': is_zapping,
        'is_black': is_black,
        'has_banner': has_banner,
        'dark_percentage': dark_percentage,
        'edge_density': edge_density,
        'blackscreen_time': blackscreen_time,
        'banner_time': banner_time
    }


def main():
    """Test images from zap/ and blackscreen/ folders"""
    
    # Get script directory
    script_dir = Path(__file__).parent
    img_dir = script_dir / 'img'
    
    # Check if single image mode
    if len(sys.argv) >= 2:
        image_path = sys.argv[1]
        if not os.path.exists(image_path):
            print(f"❌ Error: Image not found: {image_path}")
            return 1
        
        result = analyze_blackscreen(image_path, verbose=True)
        return 0 if result and result['is_zapping'] else 1
    
    # Batch mode - scan folders
    zap_dir = img_dir / 'zap'
    blackscreen_dir = img_dir / 'blackscreen'
    
    print("\n" + "="*80)
    print("🧪 BLACKSCREEN + BANNER DETECTION TEST")
    print("="*80)
    print("Testing zap detection with false positive detection")
    print("\nExpected:")
    print("  ✅ img/zap/         → Detect as ZAPPING (blackscreen + banner)")
    print("  ⚠️  img/blackscreen/ → Detect as FALSE POSITIVE (blackscreen, no banner)")
    print("="*80)
    
    # Collect images from both folders
    test_cases = []
    
    # Zap images (should detect as zapping)
    if zap_dir.exists():
        for img_path in sorted(zap_dir.glob('*.jpg')):
            test_cases.append({
                'path': str(img_path),
                'name': img_path.name,
                'folder': 'zap',
                'expected': 'zapping'
            })
    
    # Blackscreen images (should detect as false positive)
    if blackscreen_dir.exists():
        for img_path in sorted(blackscreen_dir.glob('*.jpg')):
            test_cases.append({
                'path': str(img_path),
                'name': img_path.name,
                'folder': 'blackscreen',
                'expected': 'false_positive'
            })
    
    if not test_cases:
        print("\n❌ No images found in img/zap/ or img/blackscreen/")
        return 1
    
    print(f"\nFound {len(test_cases)} images to test\n")
    
    # Test each image
    results = []
    for test in test_cases:
        result = analyze_blackscreen(test['path'], verbose=False)
        if result is None:
            continue
        
        test['result'] = result
        results.append(test)
        
        # Determine if correct
        is_zapping = result['is_zapping']
        is_black = result['is_black']
        has_banner = result['has_banner']
        
        if test['expected'] == 'zapping':
            correct = is_zapping
            status = '✅ CORRECT' if correct else '❌ WRONG'
        else:  # false_positive
            correct = is_black and not has_banner
            status = '✅ CORRECT' if correct else '❌ WRONG'
        
        test['correct'] = correct
        
        # Print compact result
        folder_label = f"[{test['folder']}]".ljust(15)
        name_label = test['name'].ljust(35)
        
        if is_zapping:
            result_label = '🎯 ZAPPING'
        elif is_black:
            result_label = '⬛ BLACK (no banner)'
        else:
            result_label = '📺 CONTENT'
        
        print(f"{folder_label} {name_label} → {result_label.ljust(25)} {status}")
        print(f"{'':15} Dark: {result['dark_percentage']:.1f}% | Edges: {result['edge_density']:.1f}%")
    
    # Summary
    print("\n" + "="*80)
    print("📊 SUMMARY")
    print("="*80)
    
    zap_results = [r for r in results if r['folder'] == 'zap']
    blackscreen_results = [r for r in results if r['folder'] == 'blackscreen']
    
    total_correct = sum(1 for r in results if r['correct'])
    total_wrong = len(results) - total_correct
    
    print(f"\nTotal images tested: {len(results)}")
    print(f"  ✅ Correct: {total_correct}")
    print(f"  ❌ Wrong: {total_wrong}")
    
    if zap_results:
        zap_correct = sum(1 for r in zap_results if r['correct'])
        print(f"\nZap images (img/zap/):")
        print(f"  {zap_correct}/{len(zap_results)} correctly detected as zapping")
    
    if blackscreen_results:
        black_correct = sum(1 for r in blackscreen_results if r['correct'])
        print(f"\nBlackscreen images (img/blackscreen/):")
        print(f"  {black_correct}/{len(blackscreen_results)} correctly detected as false positive")
    
    # Performance
    avg_time = sum(r['result']['blackscreen_time'] + r['result']['banner_time'] for r in results) / len(results)
    print(f"\nAverage processing time: {avg_time:.2f}ms per image")
    
    print("\n✅ Test complete!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
