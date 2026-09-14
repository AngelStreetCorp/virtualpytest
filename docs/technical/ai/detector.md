# Detector.py - Optimized Frame Analysis

## Overview

`detector.py` is the core frame analysis engine that runs in real-time via `inotify` monitoring. It analyzes each captured frame for quality issues, zapping events, subtitles, and more.

**Performance**: ~2-10ms per frame (without OCR), ~150-300ms with OCR (sampled every 1s)

---

## Optimized Workflow (Edge-Based Analysis + Zap State Tracking)

### **🎯 Zap State Optimization** - **NEW!**
Before starting regular detection, check if device is currently zapping:

**IF ZAPPING** (state file exists) → **FAST PATH** (~0.3-2ms):
1. Load image (~0.5ms)
2. Quick blackscreen check (~0.1ms) - no edge detection!
3. **IF blackscreen disappeared** → Write zap_sequence_end + clear state
4. **IF still blackscreen** → Return minimal JSON (skip all expensive ops)

**Savings: ~99% CPU** (300ms → 0.3ms per frame during zap)

---

### **Normal Detection Workflow** (not zapping)

### **1. Load Image** (~5ms)
- Loads frame in grayscale
- Extract dimensions for region calculations

### **2. Edge Detection** (~1-2ms) - **CORE**
- Runs Canny edge detection
- **Reused** for zap confirmation and subtitle detection
- Cost: Runs once per frame

### **3. Blackscreen Detection** (~0.1-0.3ms)
- **Region**: 5-70% of image (skip TV header & banner area)
- **Threshold**: ≤10 pixel intensity (dark grey/black)
- **Sampling**: Every 3rd pixel (11% sample) for speed
- **Full scan**: Only if ambiguous (70-90% dark range)
- **Result**: `blackscreen: true` if >85% dark

### **4. Zap Detection** (~0.1ms) - **CONDITIONAL**
- **Only runs if**: `blackscreen == true`
- **Check**: Bottom 30% for edge density (banner/channel info)
- **Result**: `zap: true` if blackscreen + bottom content (3-20% edges)
- **🆕 State tracking**: If zap detected, save state to `.zap_state.json`

### **5. Subtitle Detection** (~0.1ms + 150-300ms OCR) - **CONDITIONAL**
- **Skipped if**: `zap == true` (mutually exclusive)
- **Sampling**: Every 1 second (every 5th frame at 5fps)
- **Steps**:
  1. Check bottom 15% for edge density (2-25%)
  2. If edges found → Find subtitle boxes (width>30%, height 20-150px, aspect>3)
  3. Take lowest box (bottom-most)
  4. Downscale to 80px height
  5. Run Tesseract OCR (`--psm 6 --oem 3`)
  6. Detect language & confidence

### **6. Freeze Detection** (~5-10ms)
- Compare last 3 thumbnails using MSE
- **Skipped**: Not skipped (independent)
- Uses 320x180 thumbnails for speed

### **7. Macroblock Detection** (~3-5ms) - **CONDITIONAL**
- **Skipped if**: `blackscreen == true` OR `freeze == true`
- Analyzes compression artifacts

### **8. Audio Detection** (~0.1ms cached, ~50ms FFmpeg)
- **Sampling**: Every 5 seconds
- **Caching**: Result cached for intermediate frames
- Checks latest HLS segment

---

## JSON Output Schema

### **Complete Example** (All Fields)

```json
{
  "timestamp": "2025-10-08T15:23:45.123456",
  "filename": "capture_001234.jpg",
  
  "blackscreen": false,
  "blackscreen_percentage": 23.3,
  "blackscreen_threshold": 10,
  "blackscreen_region": "5-70%",
  
  "zap": false,
  "has_bottom_content": false,
  "bottom_edge_density": 0.0,
  "zap_sequence_start": false,
  
  "freeze": false,
  "freeze_diffs": [0.5, 1.2, 0.8],
  "last_3_filenames": [
    "/path/to/capture_001232.jpg",
    "/path/to/capture_001233.jpg",
    "/path/to/capture_001234.jpg"
  ],
  "last_3_thumbnails": [
    "/path/to/thumbnails/capture_001232_thumbnail.jpg",
    "/path/to/thumbnails/capture_001233_thumbnail.jpg",
    "/path/to/capture_001234_thumbnail.jpg"
  ],
  
  "macroblocks": false,
  "quality_score": 98.5,
  
  "audio": true,
  "volume_percentage": 45,
  "mean_volume_db": -23.5,
  
  "subtitle_analysis": {
    "has_subtitles": true,
    "extracted_text": "# It's time to ride\nCome on, the wind's begun to blow",
    "detected_language": "en",
    "confidence": 1.0,
    "box": {
      "x": 330,
      "y": 523,
      "width": 623,
      "height": 124
    },
    "ocr_method": "edge_based_box_detection",
    "downscaled_to_height": 80,
    "psm_mode": 6,
    "subtitle_edge_density": 2.2,
    "skipped": false,
    "skip_reason": null
  },
  
  "performance_ms": {
    "image_load": 4.71,
    "edge_detection": 9.29,
    "blackscreen": 0.26,
    "zap": 0.1,
    "subtitle_area_check": 0.07,
    "subtitle_ocr": 301.55,
    "freeze": 5.73,
    "macroblocks": 3.2,
    "audio": 0.06,
    "audio_cached": true,
    "total": 322.12
  }
}
```

### **Zap Sequence Examples**

#### **Start Frame** - `capture_001238.json`
```json
{
  "timestamp": "2025-10-08T15:23:45.123",
  "filename": "capture_001238.jpg",
  
  "blackscreen": true,
  "blackscreen_percentage": 96.7,
  "blackscreen_threshold": 10,
  "blackscreen_region": "5-70%",
  
  "zap": true,
  "has_bottom_content": true,
  "bottom_edge_density": 7.0,
  "zap_sequence_start": true,
  
  "freeze": false,
  "freeze_diffs": [],
  
  "macroblocks": false,
  "quality_score": 0.0,
  
  "audio": true,
  "volume_percentage": 45,
  "mean_volume_db": -23.5,
  
  "subtitle_analysis": {
    "has_subtitles": false,
    "skipped": true,
    "skip_reason": "zap"
  },
  
  "performance_ms": {
    "total": 10.5
  }
}
```

#### **Middle Frame (Fast Path)** - `capture_001239.json`
```json
{
  "timestamp": "2025-10-08T15:23:45.323",
  "filename": "capture_001239.jpg",
  
  "blackscreen": true,
  "blackscreen_percentage": 97.2,
  "blackscreen_threshold": 10,
  "blackscreen_region": "5-70%",
  
  "zap": true,
  "zap_in_progress": true,
  "has_bottom_content": true,
  "bottom_edge_density": 0.0,
  
  "subtitle_analysis": {
    "skipped": true,
    "skip_reason": "zap_in_progress"
  },
  
  "performance_ms": {
    "total": 0.3  ← 99% faster! No OCR, no edges
  }
}
```

#### **End Frame** - `capture_001241.json`
```json
{
  "timestamp": "2025-10-08T15:23:45.923",
  "filename": "capture_001241.jpg",
  
  "blackscreen": false,
  "blackscreen_percentage": 12.1,
  "blackscreen_threshold": 10,
  "blackscreen_region": "5-70%",
  
  "zap": false,
  "has_bottom_content": false,
  "bottom_edge_density": 0.0,
  "zap_sequence_end": true,
  "zap_sequence_info": {
    "start_frame": "capture_001238.jpg",
    "end_frame": "capture_001241.jpg",
    "next_frame": "capture_001242.jpg",
    "duration_seconds": 0.8,
    "start_timestamp": "2025-10-08T15:23:45.123",
    "end_timestamp": "2025-10-08T15:23:45.923",
    "frames_in_sequence": 4
  },
  
  "freeze": false,
  "freeze_diffs": [],
  "last_3_filenames": [],
  "last_3_thumbnails": [],
  
  "macroblocks": false,
  "quality_score": 0.0,
  
  "audio": true,
  "volume_percentage": 45,
  "mean_volume_db": -23.5,
  
  "subtitle_analysis": {
    "has_subtitles": false,
    "extracted_text": "",
    "detected_language": null,
    "confidence": 0.0,
    "box": null,
    "ocr_method": null,
    "downscaled_to_height": null,
    "psm_mode": null,
    "subtitle_edge_density": 0.0,
    "skipped": true,
    "skip_reason": "zap"
  },
  
  "performance_ms": {
    "image_load": 4.5,
    "edge_detection": 1.5,
    "blackscreen": 0.08,
    "zap": 0.1,
    "subtitle_area_check": 0.0,
    "subtitle_ocr": 0.0,
    "freeze": 0.08,
    "macroblocks": 0.0,
    "audio": 0.1,
    "audio_cached": true,
    "total": 6.4
  }
}
```

---

## Field Reference

### **Blackscreen Fields**

| Field | Type | Description |
|-------|------|-------------|
| `blackscreen` | boolean | True if >85% of pixels are dark (≤10 intensity) |
| `blackscreen_percentage` | float | Percentage of dark pixels in analysis region |
| `blackscreen_threshold` | int | Pixel intensity threshold used (default: 10) |
| `blackscreen_region` | string | Region analyzed (e.g., "5-70%" - skip header & banner) |

### **Zap Detection Fields** (NEW)

| Field | Type | Description |
|-------|------|-------------|
| `zap` | boolean | **True if blackscreen + bottom content** |
| `has_bottom_content` | boolean | Edge density in bottom 30% (banner/channel info) |
| `bottom_edge_density` | float | Percentage of edge pixels in bottom region |
| `zap_sequence_start` | boolean | **NEW** - True if zap sequence starts this frame |
| `zap_in_progress` | boolean | **NEW** - True if device is currently zapping (fast path) |
| `zap_sequence_end` | boolean | **NEW** - True if zap sequence ends this frame |
| `zap_sequence_info` | object | **NEW** - Zap sequence metadata (only on end frame) |

**Zap Logic**: `zap = blackscreen AND (3% < bottom_edge_density < 20%)`

**Zap State Tracking**:
- When `zap: true` first detected → Save state to `.zap_state.json`
- While zapping → Fast path (skip OCR, just monitor blackscreen)
- When blackscreen disappears → Write `zap_sequence_info` + clear state

**Banner Detection Optimization**:
- `next_frame` field provides the ideal frame for channel banner/EPG detection
- Calculated automatically (end_frame + 1)
- zap_executor.py can immediately analyze banner without guessing frame

#### **Zap Sequence Info Object** (on end frame)

| Field | Type | Description |
|-------|------|-------------|
| `start_frame` | string | Filename where zap started (e.g., "capture_001238.jpg") |
| `end_frame` | string | Filename where zap ended (e.g., "capture_001241.jpg") |
| `next_frame` | string | **Next frame after zap** (e.g., "capture_001242.jpg") - ideal for banner detection |
| `duration_seconds` | float | Total zap duration (end - start timestamps) |
| `start_timestamp` | string | ISO timestamp when zap started |
| `end_timestamp` | string | ISO timestamp when zap ended |
| `frames_in_sequence` | int | Number of frames in zap sequence |

### **Subtitle Analysis Fields** (ENHANCED)

| Field | Type | Description |
|-------|------|-------------|
| `subtitle_analysis` | object | Subtitle detection results (null if not sampled) |
| `has_subtitles` | boolean | True if text extracted |
| `extracted_text` | string | OCR text result |
| `detected_language` | string | Language code (e.g., 'en', 'fr') or null |
| `confidence` | float | 1.0 if language detected, 0.75 if text only, 0.0 if none |
| `box` | object | `{x, y, width, height}` - subtitle box coordinates |
| `ocr_method` | string | "edge_based_box_detection" |
| `downscaled_to_height` | int | OCR region height (80px for optimization) |
| `psm_mode` | int | Tesseract PSM mode (6 = multi-line) |
| `subtitle_edge_density` | float | Edge density in subtitle area (bottom 15%) |
| `skipped` | boolean | True if OCR skipped |
| `skip_reason` | string | Why skipped: "zap", "no_edges", "no_boxes_found" |

### **Freeze Detection Fields**

| Field | Type | Description |
|-------|------|-------------|
| `freeze` | boolean | True if last 3 frames are identical (MSE < 5.0) |
| `freeze_diffs` | array | MSE differences between consecutive frames |
| `last_3_filenames` | array | Paths to last 3 full-resolution captures |
| `last_3_thumbnails` | array | Paths to last 3 thumbnails (used for comparison) |

### **Macroblock Fields**

| Field | Type | Description |
|-------|------|-------------|
| `macroblocks` | boolean | True if compression artifacts detected |
| `quality_score` | float | Video quality score (0-100, higher = better) |

### **Audio Fields**

| Field | Type | Description |
|-------|------|-------------|
| `audio` | boolean | True if audio present in latest HLS segment |
| `volume_percentage` | int | Volume level (0-100) |
| `mean_volume_db` | float | Mean volume in dB (-100 = silence) |

### **Performance Fields**

| Field | Type | Description |
|-------|------|-------------|
| `performance_ms.image_load` | float | Image loading time |
| `performance_ms.edge_detection` | float | Edge detection time (core - runs always) |
| `performance_ms.blackscreen` | float | Blackscreen detection time |
| `performance_ms.zap` | float | Zap confirmation time (0 if skipped) |
| `performance_ms.subtitle_area_check` | float | Subtitle edge detection time |
| `performance_ms.subtitle_ocr` | float | OCR execution time (0 if skipped) |
| `performance_ms.freeze` | float | Freeze detection time |
| `performance_ms.macroblocks` | float | Macroblock analysis time (0 if skipped) |
| `performance_ms.audio` | float | Audio check time |
| `performance_ms.audio_cached` | boolean | True if audio result was cached |
| `performance_ms.total` | float | Total detection time |

---

## Smart Skip Logic

### **Cost Savings Through Mutual Exclusivity**

```
IF blackscreen:
    → Run zap check (0.1ms)
    
IF zap:
    → Skip subtitle check (save 150-300ms OCR)
    → Skip freeze check (conceptual - not implemented)
    → Skip macroblocks (already done for blackscreen)
ELSE:
    → Run subtitle check (if sampled)
    → Run freeze check
    → Run macroblocks (if no freeze)
```

### **Sampling Strategy**

- **Subtitles**: Every 1 second (every 5th frame at 5fps)
- **Audio**: Every 5 seconds (cached for intermediate frames)
- **Freeze/Macroblocks/Zap**: Every frame

---

## Production Integration

### **inotify Monitoring**

```python
from backend_host.scripts.detector import detect_issues

# Called by capture_monitor.py on new frame
result = detect_issues('/path/to/capture_001234.jpg', fps=5)

# Save to JSON
with open('/path/to/capture_001234.json', 'w') as f:
    json.dump(result, f)
```

### **Frontend Consumption**

```typescript
// useMonitoring.ts
const parseJsonData = (data: any) => {
  return {
    blackscreen: data.blackscreen,
    zap: data.zap,  // NEW
    freeze: data.freeze,
    audio: data.audio,
    subtitle_analysis: data.subtitle_analysis,
    ...
  };
};
```

---

## Performance Benchmarks

### **Frame Analysis (5fps)**

| Scenario | Time | Cost | Notes |
|----------|------|------|-------|
| Normal frame (no issues) | ~10-15ms | Low | Full detection |
| Blackscreen (no zap) | ~5-7ms | Very Low | Skipped macroblocks |
| **Zap start frame** | ~10-15ms | Low | Full detection, state saved |
| **Zap middle frame** 🚀 | ~0.3-2ms | **Minimal** | **Fast path! No OCR, no edges** |
| **Zap end frame** | ~2-5ms | Very Low | Blackscreen check + sequence info |
| Subtitle frame (sampled 1s) | ~150-300ms | Medium | OCR |
| Freeze frame | ~10-15ms | Low | MSE comparison |

### **Per-Frame Breakdown**

| Operation | Time | Frequency |
|-----------|------|-----------|
| Image Load | ~5ms | Every frame |
| Edge Detection | ~1-2ms | Every frame |
| Blackscreen | ~0.1-0.3ms | Every frame |
| Zap Check | ~0.1ms | If blackscreen |
| Subtitle Edge Check | ~0.1ms | Every 1s |
| Subtitle OCR | ~150-300ms | If edges detected (every 1s) |
| Freeze | ~5-10ms | Every frame |
| Macroblocks | ~3-5ms | If no blackscreen/freeze |
| Audio | ~0.1ms (cached) | Every 5s (FFmpeg ~50ms) |

### **Cost Savings**

- **Zap Detection**: Saves ~150-300ms by skipping OCR
- **Edge Reuse**: Saves ~1-2ms by reusing for zap + subtitles
- **Smart Sampling**: 80% reduction in audio checks (5s intervals)
- **Subtitle Sampling**: 80% reduction in OCR calls (1s intervals)

---

## Optimizations Applied

1. **🎯 Zap State Tracking** - **BIGGEST SAVINGS!**
   - Track when device is zapping (state file)
   - Fast path during zap: ~0.3-2ms (vs 300ms)
   - Skip OCR, edge detection, freeze, macroblocks
   - **~99% CPU savings during zap** (typical 4-10 frames @ 5fps)

2. **Edge Detection Reuse**
   - Run once, use for zap + subtitles
   - ~1-2ms saved per frame

3. **Smart Blackscreen Sampling**
   - Sample every 3rd pixel (11% sample)
   - Full scan only if ambiguous (70-90% dark)
   - ~0.2ms saved for clear cases

4. **Conditional Zap Check**
   - Only check bottom content if blackscreen
   - Skip if not needed (most frames)

5. **Mutually Exclusive OCR**
   - Skip subtitle OCR if zap detected
   - ~150-300ms saved per zap start frame

6. **Box-Based OCR**
   - Find specific subtitle box using edges
   - Downscale to 80px height
   - ~50% faster than full-region OCR

7. **Audio Caching**
   - Check every 5 seconds, cache result
   - 80% reduction in FFmpeg calls

8. **Subtitle Sampling**
   - Run every 1 second (not every frame)
   - 80% reduction in OCR calls at 5fps

---

## Testing

### **Test Script**

```bash
cd ~/virtualpytest
python3 backend_host/scripts/test_detector.py
```

### **Test Images**

- `android_tv_blackscreen.jpg` - Zap with TV banner
- `android_mobile_blackscreen.jpg` - Zap with mobile banner
- `subtitles_original.jpg` - Game with subtitles

### **Expected Results**

```
android_tv_blackscreen.jpg:
  ✅ Zap detected (blackscreen + banner)
  ⏭️  OCR skipped (zap)
  ⏱️  ~0.5-1ms total

android_mobile_blackscreen.jpg:
  ✅ Zap detected (blackscreen + banner)
  ⏭️  OCR skipped (zap)
  ⏱️  ~2-3ms total

subtitles_original.jpg:
  ❌ No zap
  ✅ Subtitles detected
  ✅ OCR: "It's time to ride\nCome on, the wind's begun to blow"
  ⏱️  ~150-300ms total (OCR)
```

---

## Backward Compatibility

✅ **All existing JSON fields preserved**
✅ **New fields are additive only**
✅ **Frontend parsing unchanged** (`useMonitoring`, `useHeatmap`)
✅ **Optional fields use null-safe defaults**

---

## Future Enhancements

1. **GPU Acceleration**
   - Move edge detection to GPU (OpenCV CUDA)
   - ~10x speedup for edge operations

2. **Parallel OCR**
   - Run OCR in separate thread
   - Non-blocking for main detection loop

3. **ML-Based Subtitle Detection**
   - Train YOLO model for subtitle boxes
   - ~50% faster than edge-based detection

4. **Adaptive Sampling**
   - Increase OCR frequency during subtitle-heavy content
   - Decrease during non-subtitle periods

---

## Troubleshooting

### **OCR Not Working**

```python
# Check pytesseract availability
import pytesseract
pytesseract.get_tesseract_version()

# Install if missing
# macOS: brew install tesseract
# Linux: apt-get install tesseract-ocr
```

### **Slow Detection (>50ms/frame)**

1. Check if OCR is running every frame (should be 1s intervals)
2. Verify edge detection runs once (not duplicated)
3. Check freeze detection uses thumbnails (not full-res)

### **False Zap Detection**

- Adjust `bottom_edge_density` thresholds (3-20%)
- Check `blackscreen_threshold` (default: 10)
- Verify region skip (5-70%, not 0-100%)

### **Missing Subtitles**

- Check `subtitle_edge_density` thresholds (2-25%)
- Verify box filtering criteria (width>30%, height 20-150px)
- Ensure sampling interval allows detection (1s)

---

## Zap State Files

### **`.zap_state.json`** (transient)

Located in capture directory (e.g., `/var/www/html/stream/capture1/.zap_state.json`)

```json
{
  "zapping": true,
  "start_frame": "capture_001238.jpg",
  "start_timestamp": "2025-10-08T15:23:45.123",
  "start_frame_number": 1238
}
```

**Lifecycle**:
- Created: When `zap: true` first detected
- Exists: While device is zapping (fast path active)
- Deleted: When blackscreen disappears (zap ends)
- Survives: Process restarts (file-based + in-memory cache)

**Purpose**:
- Tell detector to use fast path
- Store start frame info for sequence metadata
- Enable CPU optimization during zap

---

## Related Files

- `backend_host/scripts/detector.py` - Main detection script (with zap state tracking)
- `backend_host/scripts/capture_monitor.py` - inotify monitoring
- `backend_host/src/controllers/verification/video_content_helpers.py` - Helper functions
- `shared/src/lib/utils/image_utils.py` - OCR utilities
- `shared/src/lib/executors/zap_executor.py` - Zap analysis consumer
- `frontend/src/hooks/monitoring/useMonitoring.ts` - Frontend consumer
- `frontend/src/hooks/useHeatmap.ts` - Heatmap consumer
- `docs/DETECTOR_JSON_SCHEMA.md` - Complete JSON schema reference

