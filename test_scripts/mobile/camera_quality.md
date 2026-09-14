# camera_quality

Camera capture and quality analysis script for VirtualPyTest framework.

## Description

This script **actually captures real photos using the device camera hardware** and performs comprehensive quality analysis combining both technical metrics and AI-powered visual assessment. The analysis includes BRISQUE scoring, sharpness analysis, noise level detection, contrast measurement, and AI-based image description and quality assessment with coherence checking.

**Important**: This script does NOT take screenshots. It launches the phone's camera app, triggers the shutter to take an actual photo, and then analyzes the resulting camera image file.

## Usage

```bash
# Basic usage with default settings (includes AI analysis if OPENROUTER_API_KEY is set)
python test_scripts/mobile/camera_quality.py

# Specify output file
python test_scripts/mobile/camera_quality.py --output /tmp/camera_capture.jpg

# Use specific device and interface
python test_scripts/mobile/camera_quality.py --device device1 --userinterface example_mobile

# Analysis includes both technical metrics and AI-powered visual assessment
```

## Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `--userinterface` | string | `example_mobile` | The user interface framework to use |
| `--output` | string | (temp file) | Output path for captured image. If not specified, uses a temporary file |
| `--device` | string | `device1` | Specific device to use |

## Output

The script generates a comprehensive HTML report including:

### Capture Results
- Success/failure status of camera capture
- Image file path and size
- Device information

### Technical Quality Analysis
- **Overall Quality Score**: 0-10 scale composite score
- **Quality Assessment**: Verbal description (Excellent/Good/Fair/Poor/Very Poor)

### AI-Powered Analysis (New)
- **Image Description**: AI-generated short description of captured content (10-20 words)
- **AI Quality Assessment**: AI visual quality evaluation (EXCELLENT/GOOD/FAIR/POOR)
- **AI Quality Score**: AI-assigned quality score (0-10 scale)
- **Coherence Check**: AI verification that technical metrics align with visual quality
- **Discrepancy Analysis**: Detailed explanation of any significant differences between technical and AI assessments

### Technical Metrics
- **BRISQUE Score**: Blind/Referenceless Image Spatial Quality Evaluator
  - **Range**: 0-100 (lower = better quality)
  - **Quality Levels**:
    - 0-30: EXCELLENT (near-perfect image quality)
    - 30-60: GOOD (clear, natural appearance)
    - 60-80: FAIR (acceptable with minor artifacts)
    - 80+: POOR (significant quality issues)

- **Sharpness (Laplacian variance)**: Measures edge clarity and focus
  - **Range**: 0+ (higher = sharper)
  - **Quality Levels**:
    - >1000: EXCELLENT (very sharp, professional quality)
    - 500-1000: GOOD (clear focus)
    - 200-500: FAIR (acceptable sharpness)
    - <200: POOR (blurry, out of focus)

- **Noise Level**: Estimated image noise (signal-to-noise ratio)
  - **Range**: 0+ (lower = less noise, cleaner image)
  - **Quality Levels**:
    - <0.5: EXCELLENT (very clean, minimal noise)
    - 0.5-2.0: GOOD (low noise, clear details)
    - 2.0-5.0: FAIR (moderate noise, acceptable)
    - >5.0: POOR (high noise, grainy appearance)

- **Contrast (StdDev)**: Standard deviation of lightness channel in LAB color space
  - **Range**: 0+ (higher = better contrast, more detail)
  - **Quality Levels**:
    - >60: EXCELLENT (rich tonal range, high detail)
    - 40-60: GOOD (good contrast, clear details)
    - 25-40: FAIR (moderate contrast, acceptable)
    - <25: POOR (flat, low contrast, washed out)

### Component Scores (0-10 scale)
- **BRISQUE Quality**: Quality based on BRISQUE algorithm
- **Sharpness**: Sharpness component score
- **Noise**: Noise level component score
- **Contrast**: Contrast component score

## AI Analysis Features

### Overview
The script now includes AI-powered visual analysis that complements the technical quality metrics with human-like image assessment and coherence verification.

### AI Image Description
- **Purpose**: Provides a concise 10-20 word description of what the AI "sees" in the captured image
- **Use Cases**: Content verification, automated documentation, visual regression detection
- **Example**: "A clear photo of a computer screen displaying a web browser with code"

### AI Quality Assessment
- **Scale**: EXCELLENT / GOOD / FAIR / POOR
- **Criteria**: Visual clarity, sharpness, color accuracy, overall usability, and professional appearance
- **Assessment Guidelines**:
  - **EXCELLENT**: Professional quality, crystal clear, no visible issues
  - **GOOD**: Clear and usable for most purposes
  - **FAIR**: Acceptable but has noticeable issues
  - **POOR**: Significant problems affecting usability

### Coherence Check
- **Purpose**: Verifies alignment between technical metrics and AI visual assessment
- **Detection**: Identifies discrepancies >2.0 points between technical score and AI score
- **Analysis**: AI explains any significant differences and provides reasoning
- **Status**: COHERENT / INCOHERENT with detailed explanation

### AI Technical Details
- **Model**: Qwen/Qwen-2.5-VL-7B-Instruct (via OpenRouter)
- **API**: Uses centralized AI utilities from `shared.src.lib.utils.ai_utils`
- **Fallback**: Gracefully handles AI service failures without breaking technical analysis
- **Cost**: Single vision API call per image analysis

## Quality Metrics Explanation

### Composite Score Calculation
```
Overall Score = (0.5 × BRISQUE_note) + (0.3 × Sharpness_note) + (0.1 × Noise_note) + (0.1 × Contrast_note)
```

### Quality Thresholds
- **9-10**: Excellent (Professional grade)
- **7-8**: Good (Clear and usable)
- **5-6**: Fair (Acceptable for basic use)
- **3-4**: Poor (Significant issues)
- **0-2**: Very Poor (Unusable)

### Technical Details
- **BRISQUE**: Uses OpenCV's blind image quality assessment with pre-trained model
- **Sharpness**: Calculated using Laplacian variance on grayscale image
- **Noise**: Estimated by comparing image with denoised version
- **Contrast**: Measured as standard deviation in LAB color space lightness channel

### Camera Capture Process
The script performs actual camera captures (not screenshots) using this process:
1. **List existing photos** in device camera directories (`/sdcard/DCIM/Camera`, etc.)
2. **Launch camera app** using `adb shell am start -a android.media.action.STILL_IMAGE_CAMERA`
3. **Wait for focus** (configurable wait time, default 3 seconds)
4. **Trigger shutter** using `adb shell input keyevent 27` (KEYCODE_CAMERA)
5. **Wait for photo to save** (5 seconds to ensure image file is fully written to disk)
6. **Find new photo** using time-based sorting (`ls -1t`) to get the most recently modified image file
7. **Pull image file** from device using `adb pull` to the specified output path

**Photo Detection Strategy**: Since we just triggered a camera capture, the most recently modified photo file in the camera directory should be our new image. The system uses `ls -1t` (sort by modification time) to find the newest photo, with fallback logic for edge cases.

This ensures analysis of genuine camera-captured images, not display screenshots.

## Dependencies

- OpenCV with quality assessment module
- BRISQUE model files (`brisque_model_live.yml`, `brisque_range_live.yml`)
- Android device with camera access
- ADB (Android Debug Bridge) for device control
- AI Analysis (Optional):
  - OpenRouter API key (`OPENROUTER_API_KEY` environment variable)
  - Internet connection for AI vision API calls
  - `shared.src.lib.utils.ai_utils` module

## Error Handling

The script handles various failure scenarios:
- Camera capture failures
- Image file access issues
- Quality analysis errors
- Device connectivity problems
- AI analysis failures (graceful degradation to technical-only analysis)

All errors are logged with detailed messages and included in the final report. AI analysis failures do not prevent technical quality assessment from completing.
