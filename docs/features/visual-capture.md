# 📹 Visual Capture & Monitoring

**See everything. Miss nothing.**

Automatic video capture, live streaming, and screenshot generation for comprehensive visual testing and monitoring.

---

## The Problem

Testing without visual evidence is blind testing:
- ❌ "The test passed but the screen was black"
- ❌ "I can't reproduce what the tester saw"
- ❌ "The UI was broken but the test didn't catch it"
- ❌ "No evidence of what actually happened"

---

## The VirtualPyTest Solution

✅ **Live streaming** - Watch devices in real-time from anywhere  
✅ **Automatic screenshots** - Capture every test step  
✅ **Video replay** - Review test execution frame-by-frame  
✅ **Visual evidence** - Prove what happened with timestamped captures  

---

## Features

### 📺 Live Streaming

**Watch your devices in real-time through the web interface.**

#### HDMI Capture (all real devices)
- Every real device — set-top box, TV, phone or tablet — is always captured through an HDMI acquisition card; the stream never comes from the device's own APIs
- Supported capture cards: USB HDMI, PCIe cards
- Real-time streaming to web browser
- Multiple devices simultaneously

#### Emulators
- Android emulators are the only case captured through ADB screencap

#### VNC Streaming (virtual displays)
- Remote view of the virtual display on web and desktop test hosts
- Built-in VNC server integration
- NoVNC web client (no plugins needed)

#### Network Cameras
- IP camera integration
- Physical device monitoring
- Multi-camera views
- Motion detection

**Use cases:**
- Monitor streaming quality 24/7
- Debug test failures visually
- Remote device observation
- Quality assurance validation

---

### 📸 Automatic Screenshots

**Every action captured automatically.**

#### Test Execution Screenshots
```python
# Automatic screenshots at each step
controller.navigate_to("settings")  # Screenshot: before_navigate.png
controller.press_key("DOWN")        # Screenshot: after_press_down.png
controller.verify_text("Audio")     # Screenshot: verification_result.png
```

#### Screenshot Timeline
- Before and after each action
- Timestamped file names
- Organized by test execution ID
- Easy navigation and review

#### Storage Options
- Local filesystem storage
- Cloudflare R2 cloud storage
- Configurable retention policies
- Automatic cleanup of old captures

---

### 🎬 Video Recording

**Record entire test sessions.**

#### Continuous Recording
- Always-on recording for monitoring
- Circular buffer (keeps last N hours)
- Triggered recording on events
- Export clips of interest

#### Test Session Recording
- Full video of test execution
- Synchronized with test logs
- Frame-accurate playback
- Shareable video reports

**Formats supported:**
- MP4 (web-friendly)
- MKV (high quality)
- HLS segments (live streaming)

---

## Setup Examples

Device capture settings are **not** static YAML files — devices are configured through the web
interface and stored in the `device`/`device_models` tables
(`setup/db/schema/001_core_tables.sql`). On the host side, HDMI/USB capture runs through FFmpeg
(`backend_host/scripts/run_ffmpeg.sh`, runtime-tunable — see the FFmpeg troubleshooting docs
internally), and VNC sharing of virtual displays (web/desktop hosts) uses a standard VNC server +
NoVNC web bridge (ports 5900 / 6080) — configured per device via the UI, not a checked-in YAML file.

---

## Web Interface Integration

### Live View Dashboard

Access via **Rec** menu in web interface:

- Grid view of all devices
- Click to enlarge any stream
- Fullscreen mode
- Recording controls

### Screenshot Gallery

Browse captured screenshots:

- Filter by test execution
- Timeline view
- Compare screenshots
- Download or share

---

## Visual Testing Workflow

### 1. Run Test with Visual Capture

Initial/final screenshots and the execution video are captured automatically by the script
executor unless disabled (`ScriptExecutionContext.capture_artifacts`, off only when a script sets
`capture_artifacts=False` via the `@script` decorator) — there is no separate `run_test(...,
capture_video=True)` call a script needs to make.

### 2. Review Results

- View test report with embedded screenshots
- Play back video recording
- Compare expected vs. actual images
- Identify exactly when/where failure occurred

### 3. Debug Issues

- Screenshot timeline shows progression
- Video replay at normal or slow speed
- Jump to specific test steps
- Visual diff between attempts

---

## Advanced Features

These live in `backend_host/src/controllers/verification/` (real, current implementation):

### Frame Comparison (Freeze Detection)
`VideoVerificationController.detect_freeze(image_paths, freeze_threshold)` — compares a sequence
of recent captures to detect identical/frozen frames.

### Black Screen / Color Detection
Color and brightness analysis lives in `verification/color.py`.

### Subtitle Detection
`VideoVerificationController.detect_subtitles(image_paths, extract_text)` (and AI-assisted
variants `detect_subtitles_ai*`) — runs OCR/vision analysis on a region to check for subtitle
presence and text.

None of the above are called via a generic `detector.detect_x(video_stream=..., threshold=...)`
API from test scripts — they're internal controller methods invoked as part of the verification
pipeline attached to navigation nodes/edges.

---

## Storage

Screenshots and videos upload to Cloudflare R2 (S3-compatible), configured via the `R2_*`
environment variables at deploy time — see [Cloud Setup](../get-started/cloud-setup.md) and
[configuration reference](../get-started/configuration.md). There is no built-in retention/cleanup YAML
config or a configurable public CDN URL beyond what R2 itself provides; manage lifecycle rules
directly in your R2 bucket settings if you need automatic expiry.

---

## Streaming & Encoding

Live streaming and capture run through FFmpeg on the host
(`backend_host/scripts/run_ffmpeg.sh`), with runtime-tunable parameters (adaptive fps,
restart-only tuning) rather than a checked-in HLS/encoding YAML config file. There is no
documented GPU/NVENC hardware-encoding path in the current implementation.

---

## Integration with Tests

Screenshot capture and comparison happen as part of the same verification pipeline described
above (navigation-node `verifications`, `ScriptExecutionContext` screenshot tracking) — there is
no separate `controller.verify_screen(reference_image=..., capture_on_fail=...)` call. Test
reports (validation report `.md`, inlined as base64 image data) include source/reference/overlay
images for each verification — see [Running Tests](../user-guide/running-tests.md).

---

## Monitoring & Alerts

Visual-quality issue detection (black screen, freeze, subtitle presence) happens as part of
verification and the monitoring pipeline (`vpt-monitor`) — there is no built-in declarative YAML
alert-rule engine wiring these to Slack/incident-creation/device-restart actions. Wire alerting
through Grafana (see [Analytics](analytics.md)) against the underlying metrics tables instead.
```

---

## Hardware Requirements

### For HDMI Capture

- HDMI capture card (USB or PCIe)
- Recommended: Elgato, AVerMedia, or generic USB 3.0 HDMI capture
- USB 3.0 port (for USB capture cards)
- Sufficient disk space or cloud storage

### For VNC Capture (virtual displays)

- VNC server on the web/desktop test host
- Network connectivity
- Minimal bandwidth (<1 Mbps per stream)

---

## Benefits

### 🔍 Complete Visibility
Never wonder what happened during a test. Full visual record of every action.

### 🐛 Faster Debugging
Screenshot timeline and video replay cut debugging time by 90%.

### 📊 Better Reporting
Visual evidence makes test reports meaningful to non-technical stakeholders.

### ⚡ Continuous Monitoring
24/7 streaming detects issues in real-time, not after the fact.

---

## Next Steps

- 📖 [AI Validation](./ai-validation.md) - Analyze captures automatically
- 📖 [Analytics](./analytics.md) - Monitor quality metrics
- 📚 User Guide - Monitoring - Set up monitoring
- 🔧 Technical Docs - Video Architecture

---

**Ready to see everything your devices do?**  
➡️ [Get Started](../get-started/README.md)



