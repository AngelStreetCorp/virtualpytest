#!/usr/bin/env python3
"""
Simple OCR test script - compares Safe vs Smart crop methods

Usage:
    # Compare both methods (default - shows side-by-side comparison)
    python test_ocr.py img/subtitles_original.jpg
    
    # Test all images in img/subt/ directory
    python test_ocr.py

Automatically compares safe and smart crop methods on the same image,
showing crop size reduction, performance gains, and text extraction differences.
"""

import cv2
import numpy as np
import os
import sys
import time
from pathlib import Path
from typing import Optional, Tuple
import re

# Add project root to Python path for shared module
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

# === CONFIGURATION ===
# OCR Crop Method: 'smart' (dark mask-based, 60-70% smaller) or 'safe' (fixed region)
OCR_CROP_METHOD = 'safe'  # Disabled smart crop - using safe area (faster, more reliable)

# Import the smart cropping algorithm
from crop_subtitles import find_subtitle_bbox

def clean_ocr_noise(text: str) -> str:
    """
    Remove OCR noise:
    - Double/triple consonants without vowels (ng, nl, afg, etc.)
    - Special characters EXCEPT . , ? !
    - Consecutive 1-2 char patterns
    - Words with no vowels (likely OCR errors)
    
    Examples: 
    - "ng nl" → removed (consonant clusters)
    - "Af } i : |" → removed (no vowels + special chars)
    - "# @ $" → removed (special chars)
    - "Hello, world!" → kept (valid punctuation)
    """
    if not text:
        return text
    
    # Split into lines
    lines = text.split('\n')
    cleaned_lines = []
    
    for line in lines:
        # Remove special characters EXCEPT . , ? ! and alphanumeric
        # Keep spaces for word splitting
        allowed_chars = re.sub(r'[^a-zA-Z0-9\s\.,?!\'\-]', ' ', line)
        
        # Split into words
        words = allowed_chars.split()
        filtered_words = []
        
        for word in words:
            # Remove punctuation for analysis
            word_alpha = re.sub(r'[^a-zA-Z]', '', word)
            
            # Skip if no letters
            if not word_alpha:
                continue
            
            # Skip if word is all consonants (OCR noise like "ng", "nl", "afg")
            # Check if word has at least one vowel
            if len(word_alpha) <= 3:
                has_vowel = any(c in 'aeiouAEIOU' for c in word_alpha)
                if not has_vowel:
                    continue  # Skip consonant-only short words
            
            # Skip very short words (1-2 chars) unless they're common words
            if len(word_alpha) < 3:
                common_short = ['I', 'a', 'A', 'an', 'on', 'in', 'to', 'is', 'it', 'be', 'we', 'he', 'or', 'no', 'so', 'up', 'my', 'me', 'at', 'by', 'do', 'go']
                if word_alpha not in common_short and word_alpha.upper() not in common_short:
                    # Exception: Keep short words if they're at the start/middle of line with nearby real words
                    # But skip isolated single chars at end of lines (OCR noise)
                    continue
            
            # Keep the original word (with punctuation)
            filtered_words.append(word)
        
        # Reconstruct line
        if filtered_words:
            cleaned_line = ' '.join(filtered_words)
            
            # Clean up multiple spaces
            cleaned_line = re.sub(r'\s+', ' ', cleaned_line).strip()
            
            # Clean trailing/leading punctuation noise (but keep valid punctuation)
            cleaned_line = re.sub(r'^[\s\-]+', '', cleaned_line)
            cleaned_line = re.sub(r'[\s\-]+$', '', cleaned_line)
            
            # Remove isolated single characters at start/end (likely OCR noise)
            # Keep uppercase "I" at start (valid pronoun), remove lowercase
            cleaned_line = re.sub(r'^[a-z]\s+', '', cleaned_line)  # Leading lowercase single char
            cleaned_line = re.sub(r'\s+[a-zA-Z]$', '', cleaned_line)  # Trailing single char
            
            # Remove lines that are just single characters or "a a" patterns
            if re.match(r'^[a-zA-Z](\s+[a-zA-Z])*$', cleaned_line):
                continue  # Skip lines like "i", "a a", "i t s"
            
            if cleaned_line:
                cleaned_lines.append(cleaned_line)
    
    return '\n'.join(cleaned_lines).strip()

def test_ocr_on_image(image_path, save_crops=True, crop_method_override=None):
    """
    Run OCR testing with configurable cropping (smart or safe area).
    
    Flow:
    1. Load image in grayscale
    2. Edge detection
    3. Find subtitle region
    4. Crop (smart edge-based or safe area)
    5. Run OCR: Grayscale + PSM 6 (uniform block - best for subtitles)
    6. Clean noise with regex (remove consecutive 1-2 char patterns)
    7. Detect language
    
    Tesseract config:
    - PSM 6 (uniform block of text)
    - OEM 3 (default LSTM mode)
    - Languages: English, French, Italian, German, Spanish
    
    Saves cropped image for visual inspection.
    
    Args:
        image_path: Path to image file
        save_crops: Save cropped regions to disk
        crop_method_override: Override OCR_CROP_METHOD ('safe' or 'smart')
    """
    method = crop_method_override if crop_method_override else OCR_CROP_METHOD
    
    print(f"\n{'='*70}")
    print(f"🔍 OCR TEST: {os.path.basename(image_path)} [{method.upper()}]")
    print(f"{'='*70}\n")
    
    # Load image in grayscale
    print("1. Loading image...")
    img_gray = cv2.imread(image_path, cv2.IMREAD_GRAYSCALE)
    if img_gray is None:
        print(f"❌ Error: Failed to load image: {image_path}")
        return None
    
    img_height, img_width = img_gray.shape[:2]
    print(f"   Image size: {img_width}x{img_height}")
    
    # Cropping (matches detector.py logic)
    print(f"\n2. Cropping ({method} mode)...")
    start = time.perf_counter()
    
    # Calculate crop based on method
    if method == 'smart':
        # SMART CROP: Dark mask-based (proven implementation from crop_subtitles.py)
        try:
            bbox = find_subtitle_bbox(img_gray)
            x, y, w, h = bbox.x, bbox.y, bbox.w, bbox.h
            crop_method = "smart_dark_mask"
        except (ValueError, Exception) as e:
            # Fall back to safe area if smart crop fails
            x = int(img_width * 0.10)
            y = int(img_height * 0.60)
            w = int(img_width * 0.80)
            h = int(img_height * 0.35)
            crop_method = f"smart_fallback_safe ({str(e)[:30]})"
            print(f"   ⚠️  Smart crop failed: {str(e)[:50]}")
    else:
        # SAFE AREA: Fixed region (60-95% height, 10-90% width)
        x = int(img_width * 0.10)
        y = int(img_height * 0.60)
        w = int(img_width * 0.80)
        h = int(img_height * 0.35)
        crop_method = "safe_area_fixed"
    
    crop_img = img_gray[y:y+h, x:x+w]
    crop_time = (time.perf_counter() - start) * 1000
    print(f"   ✓ Crop: {w}x{h} at ({x},{y}) in {crop_time:.2f}ms [{crop_method}]")
    
    # Downscale to 50% for faster OCR (reduces pixels by 75%)
    downscale_start = time.perf_counter()
    crop_img_downscaled = cv2.resize(crop_img, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)
    downscale_time = (time.perf_counter() - downscale_start) * 1000
    downscaled_h, downscaled_w = crop_img_downscaled.shape
    print(f"   ✓ Downscaled: {downscaled_w}x{downscaled_h} (50%) in {downscale_time:.2f}ms")
    
    # Save crop for visual inspection (save downscaled version)
    if save_crops:
        base_name = Path(image_path).stem
        save_dir = Path(image_path).parent
        crop_path = save_dir / f"{base_name}_{method}_crop.jpg"
        cv2.imwrite(str(crop_path), crop_img_downscaled)
        print(f"   💾 Saved: {crop_path.name}")
    
    # STEP 3: Run OCR (Grayscale + PSM 6 - production method)
    print("\n3. Running OCR (Grayscale + PSM 6)...")
    
    try:
        import pytesseract
        
        # Grayscale + PSM 6 (uniform block) - production method on DOWNSCALED image
        start = time.perf_counter()
        config = '--psm 6 --oem 3 -l eng+fra+ita+deu+spa'
        text_raw = pytesseract.image_to_string(crop_img_downscaled, config=config).strip()
        ocr_time = (time.perf_counter() - start) * 1000
        text_clean = clean_ocr_noise(text_raw)
        
        print(f"   Time: {ocr_time:.0f}ms | Raw: {len(text_raw)} chars → Cleaned: {len(text_clean)} chars")
        print(f"   Raw text:     {text_raw if text_raw else '(no text)'}")
        if text_clean != text_raw:
            print(f"   Cleaned text: {text_clean if text_clean else '(no text)'}")
        
        subtitle_text = text_clean
        
    except ImportError:
        print(f"   ❌ Error: pytesseract not available")
        return None
    except Exception as e:
        print(f"   ❌ Error: OCR failed: {e}")
        return None
    
    # Language detection
    print("\n4. Detecting language...")
    detected_language = None
    if subtitle_text and len(subtitle_text.strip()) > 0:
        try:
            from shared.src.lib.utils.image_utils import detect_language
            start = time.perf_counter()
            detected_language = detect_language(subtitle_text)
            lang_time = (time.perf_counter() - start) * 1000
            print(f"   ✓ Language detected in {lang_time:.0f}ms: {detected_language}")
        except:
            detected_language = 'unknown'
            print(f"   ⚠️  Language detection failed, marked as 'unknown'")
    else:
        print(f"   ⚠️  No text to detect language")
    
    # Results summary
    print(f"\n{'='*70}")
    print(f"📊 FINAL RESULT")
    print(f"{'='*70}")
    print(f"Crop: {w}x{h} at ({x},{y}) in {crop_time:.2f}ms [{crop_method}]")
    print(f"Downscaled: {downscaled_w}x{downscaled_h} (50%) in {downscale_time:.2f}ms")
    print(f"OCR: Grayscale + PSM 6 in {ocr_time:.0f}ms")
    print(f"Text extracted: {'YES' if subtitle_text else 'NO'}")
    if subtitle_text:
        print(f"Text length: {len(subtitle_text)} characters")
        print(f"Language: {detected_language}")
        print(f"\nFull extracted text:")
        print(f"┌{'─' * 68}┐")
        for line in subtitle_text.split('\n'):
            print(f"│ {line:<66} │")
        print(f"└{'─' * 68}┘")
    else:
        print(f"⚠️  No text extracted")
    
    return {
        'text': subtitle_text,
        'language': detected_language,
        'bbox': {'x': x, 'y': y, 'width': w, 'height': h},
        'bbox_downscaled': {'width': downscaled_w, 'height': downscaled_h},
        'method': crop_method,
        'filter': 'grayscale',
        'psm': 6,
        'crop_time_ms': crop_time,
        'downscale_time_ms': downscale_time,
        'ocr_time_ms': ocr_time
    }


def compare_methods(image_path):
    """
    Compare safe and smart crop methods side-by-side on the same image.
    Shows differences in crop size, OCR time, and extracted text.
    """
    print("\n" + "="*70)
    print("🔬 COMPARISON MODE: Safe vs Smart Crop")
    print("="*70)
    print(f"Image: {os.path.basename(image_path)}\n")
    
    results = {}
    
    # Test both methods
    for method in ['safe', 'smart']:
        result = test_ocr_on_image(image_path, save_crops=True, crop_method_override=method)
        if result:
            results[method] = result
    
    if len(results) != 2:
        print("\n❌ Could not complete comparison (one or both methods failed)")
        return 1
    
    # Simple comparison summary
    print("\n" + "="*70)
    print("📊 COMPARISON SUMMARY")
    print("="*70)
    
    safe = results['safe']
    smart = results['smart']
    
    safe_text = safe.get('text', '')
    smart_text = smart.get('text', '')
    
    # Crop size + time
    safe_pixels = safe['bbox']['width'] * safe['bbox']['height']
    smart_pixels = smart['bbox']['width'] * smart['bbox']['height']
    reduction_pct = ((safe_pixels - smart_pixels) / safe_pixels) * 100
    
    # Downscaled size (after 50% reduction)
    safe_down_w = safe['bbox_downscaled']['width']
    safe_down_h = safe['bbox_downscaled']['height']
    smart_down_w = smart['bbox_downscaled']['width']
    smart_down_h = smart['bbox_downscaled']['height']
    safe_down_pixels = safe_down_w * safe_down_h
    smart_down_pixels = smart_down_w * smart_down_h
    down_reduction_pct = ((safe_down_pixels - smart_down_pixels) / safe_down_pixels) * 100
    
    print(f"\n📐 CROP SIZE + TIME:")
    print(f"  Safe:  {safe['bbox']['width']:4d}×{safe['bbox']['height']:3d} → {safe_down_w:3d}×{safe_down_h:3d} = {safe_down_pixels:>6,} px | {safe.get('crop_time_ms', 0):4.1f}ms + {safe.get('downscale_time_ms', 0):4.1f}ms")
    print(f"  Smart: {smart['bbox']['width']:4d}×{smart['bbox']['height']:3d} → {smart_down_w:3d}×{smart_down_h:3d} = {smart_down_pixels:>6,} px | {smart.get('crop_time_ms', 0):4.1f}ms + {smart.get('downscale_time_ms', 0):4.1f}ms | {-down_reduction_pct:+.0f}%")
    
    # Text extracted + OCR time
    print(f"\n📝 TEXT EXTRACTED + TIME:")
    print(f"  Safe:  {len(safe_text):3d} chars | {safe.get('ocr_time_ms', 0):5.0f}ms OCR")
    print(f"  Smart: {len(smart_text):3d} chars | {smart.get('ocr_time_ms', 0):5.0f}ms OCR")
    if safe_text and smart_text:
        if safe_text == smart_text:
            print(f"  ✅ Identical text")
        else:
            print(f"  ⚠️  Different ({calculate_similarity(safe_text, smart_text):.0f}% similar)")
    
    # Language detected
    print(f"\n🌍 LANGUAGE:")
    print(f"  Safe:  {safe.get('language', 'unknown')}")
    print(f"  Smart: {smart.get('language', 'unknown')}")
    
    # Total time (crop + downscale + OCR)
    safe_total = safe.get('crop_time_ms', 0) + safe.get('downscale_time_ms', 0) + safe.get('ocr_time_ms', 0)
    smart_total = smart.get('crop_time_ms', 0) + smart.get('downscale_time_ms', 0) + smart.get('ocr_time_ms', 0)
    time_saved = safe_total - smart_total
    time_saved_pct = (time_saved / safe_total * 100) if safe_total > 0 else 0
    
    print(f"\n⏱️  TOTAL TIME (crop + downscale + OCR):")
    print(f"  Safe:  {safe_total:5.0f}ms")
    print(f"  Smart: {smart_total:5.0f}ms | {-time_saved:+.0f}ms ({-time_saved_pct:+.0f}%)")
    
    # Text preview
    if safe_text or smart_text:
        print(f"\n📄 EXTRACTED TEXT:")
        text_to_show = smart_text if smart_text else safe_text
        for line in text_to_show.split('\n')[:3]:  # Show first 3 lines
            preview = line[:66] if len(line) > 66 else line
            print(f"  {preview}")
    
    # Saved files
    base_name = Path(image_path).stem
    save_dir = Path(image_path).parent
    print(f"\n💾 Crops saved: {base_name}_safe_crop.jpg, {base_name}_smart_crop.jpg")
    
    print(f"\n✅ Comparison complete!\n")
    
    return 0

def calculate_similarity(text1, text2):
    """Calculate simple similarity percentage between two texts"""
    if not text1 or not text2:
        return 0.0
    
    # Simple character-based similarity
    len1, len2 = len(text1), len(text2)
    max_len = max(len1, len2)
    min_len = min(len1, len2)
    
    # Count matching characters at same positions
    matches = sum(1 for i in range(min_len) if text1[i] == text2[i])
    
    return (matches / max_len) * 100

def main():
    """Main entry point"""
    
    # Single image mode - COMPARE BY DEFAULT
    if len(sys.argv) >= 2:
        image_path = sys.argv[1]
        
        if not os.path.exists(image_path):
            print(f"❌ Error: Image not found: {image_path}")
            return 1
        
        # Always compare both methods (default behavior)
        return compare_methods(image_path)
    
    # Batch mode - test all images in img/subt/
    script_dir = Path(__file__).parent
    subt_dir = script_dir / 'img' / 'subt'
    
    if not subt_dir.exists():
        print(f"❌ Error: Directory not found: {subt_dir}")
        print("Usage: python test_ocr.py [image_path]")
        print("Example: python test_ocr.py img/subt/subtitles.jpg")
        return 1
    
    # Find all images directly in subt/ (not in subdirectories)
    image_files = sorted(subt_dir.glob('*.jpg'))
    # Filter out crop images and any that contain "_crop_" in name
    image_files = [f for f in image_files if not any(x in f.stem for x in ['_crop'])]
    
    if not image_files:
        print(f"❌ Error: No .jpg images found in {subt_dir}")
        return 1
    
    print("\n" + "="*70)
    print("🧪 OCR TEST - BATCH MODE")
    print("="*70)
    print(f"Testing {len(image_files)} images from {subt_dir}")
    print("\nConfiguration:")
    print(f"  Crop method: {OCR_CROP_METHOD.upper()} ({'dark mask-based' if OCR_CROP_METHOD == 'smart' else 'fixed region'})")
    print("  OCR: Grayscale + PSM 6 (uniform block)")
    print("  Languages: English, French, Italian, German, Spanish")
    print("  Noise cleaning: Regex filter for consecutive 1-2 char patterns")
    print("="*70)
    
    # Test each image - compare both methods
    print("\nTesting each image with both crop methods...\n")
    for img_path in image_files:
        print(f"\n{'='*70}")
        print(f"Testing: {img_path.name}")
        print(f"{'='*70}")
        compare_methods(str(img_path))
    
    print(f"\n{'='*70}")
    print(f"✅ Batch test complete! All crops saved in: {subt_dir}/")
    print(f"{'='*70}\n")
    
    return 0

if __name__ == '__main__':
    sys.exit(main())
