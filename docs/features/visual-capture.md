# Visual Capture & Monitoring

**See everything. Miss nothing.**

Watch your devices live, take a screenshot of each step and record the whole test. You keep visual proof of what happened.

---

## The Problem

A test with no pictures is hard to trust. You cannot tell if the screen was black, or what the tester actually saw.

---

## The VirtualPyTest Solution

- **Live streaming:** watch devices in real time from anywhere
- **Automatic screenshots:** a picture of every test step
- **Video replay:** review a test frame by frame

---

## Features

### Live Streaming

**Watch your devices in real time through the web interface.**

- Real devices (set-top boxes, TVs, phones and tablets) are filmed through an HDMI capture card. The picture never comes from the device's own software.
- Several devices can stream at once.
- Web and desktop test hosts can be viewed in the browser, with no plugin.

<div data-technical>

#### HDMI Capture (all real devices)
- Capture cards can be USB or PCIe.
- The picture streams to your browser in real time.
- Several devices can stream at once.

Supported capture cards: USB HDMI, PCIe cards.

#### Emulators
- Android emulators are the only exception. They are captured by taking a screen image through ADB.

Android emulators are the only case captured through ADB screencap.

#### VNC Streaming (virtual displays)
- You can see the virtual display of a web or desktop test host from your browser.
- A VNC server is built in.
- The viewer runs in the browser, so you do not install a plugin.

Remote view of the virtual display on web and desktop test hosts.
Built-in VNC server integration. NoVNC web client (no plugins needed).

#### Network Cameras
- Add IP cameras to watch physical devices.
- Show several cameras in one view.
- Detect motion.

IP camera integration. Physical device monitoring. Multi-camera views. Motion detection.

</div>

**Use cases:** watch a remote device, debug test failures visually, and check streaming quality around the clock.

---

### Automatic Screenshots

**Every action is captured automatically.** A screenshot is taken before and after each step, and grouped by test run.

<div data-technical>

#### Test Execution Screenshots

A screenshot is taken before and after each step of a test. A check of text on screen also saves its own picture.

```python
# Automatic screenshots at each step
controller.navigate_to("settings")  # Screenshot: before_navigate.png
controller.press_key("DOWN")        # Screenshot: after_press_down.png
controller.verify_text("Audio")     # Screenshot: verification_result.png
```

#### Screenshot Timeline
- A picture before and after each action
- File names carry a timestamp
- Pictures are grouped by test run
- Easy to browse and review

Before and after each action. Timestamped file names. Organized by test execution ID.

#### Storage Options
- Pictures and videos are kept in cloud storage (Cloudflare R2).
- You can set how long they are kept.
- Old captures are cleaned up automatically.

Local filesystem storage. Cloudflare R2 cloud storage. Configurable retention policies. Automatic cleanup of old captures.

</div>

---

### Video Recording

**Record entire test sessions.** Each test run gets a full video that lines up with its log. You can play it back frame by frame and share it as a report.

<div data-technical>

#### Continuous Recording
- The camera can record all the time, for monitoring.
- It keeps the last few hours in a loop.
- It can start recording when an event happens.
- You can export a clip you need.

Always-on recording for monitoring. Circular buffer (keeps last N hours). Triggered recording on events. Export clips of interest.

#### Test Session Recording
- A full video of each test run
- The video lines up with the test log
- You can play it back frame by frame
- You can share the video as a report

Full video of test execution. Synchronized with test logs. Frame-accurate playback. Shareable video reports.

</div>

**Formats:** MP4 plays in most browsers. MKV gives high quality. HLS segments are used for live streaming.

---

## Setup Examples

You set up capture in the web interface. You do not edit a settings file.

<div data-technical>

Device capture settings are **not** static YAML files — devices are configured through the web
interface and stored in the `device`/`device_models` tables
(`setup/db/schema/001_core_tables.sql`). On the host side, HDMI/USB capture runs through FFmpeg
(`backend_host/scripts/run_ffmpeg.sh`, runtime-tunable — see the FFmpeg troubleshooting docs
internally), and VNC sharing of virtual displays (web/desktop hosts) uses a standard VNC server +
NoVNC web bridge (ports 5900 / 6080) — configured per device via the UI, not a checked-in YAML file.

</div>

---

## Web Interface Integration

### Live View Dashboard

Open the **Rec** menu. You see a grid of your devices. Click a stream to enlarge it, or go full screen, and use the recording controls.

### Screenshot Gallery

Browse the captured screenshots, filter them by test run, view them as a timeline, and compare or share them.

---

## Visual Testing Workflow

### 1. Run Test with Visual Capture

The first and last screenshots and the video of the run are taken for you. You do not need to ask for them in the script. You can turn this off for a script if you need to.

<div data-technical>

Initial/final screenshots and the execution video are captured automatically by the script
executor unless disabled (`ScriptExecutionContext.capture_artifacts`, off only when a script sets
`capture_artifacts=False` via the `@script` decorator) — there is no separate `run_test(...,
capture_video=True)` call a script needs to make.

</div>

### 2. Review Results

Open the test report, which has the screenshots inside it, and play back the video. You can compare the expected and actual images and see exactly when and where the failure happened.

<div data-technical>

- Read the test report, with the screenshots inside it
- Play back the video
- Compare the expected and actual images
- See exactly when and where the failure happened

</div>

### 3. Debug Issues

Use the screenshot timeline and play the video at normal or slow speed to jump to a specific step.

<div data-technical>

- The screenshot timeline shows how the run went
- Play the video at normal or slow speed
- Jump to a specific step
- See the visual difference between attempts

</div>

---

## Advanced Features

The platform checks for frozen pictures, black screens and subtitles on its own. You do not call these checks from a script.

<div data-technical>

These live in `backend_host/src/controllers/verification/` (real, current implementation):

**Frame Comparison (Freeze Detection):** `VideoVerificationController.detect_freeze(image_paths, freeze_threshold)` — compares a sequence
of recent captures to detect identical/frozen frames.

**Black Screen / Color Detection:** color and brightness analysis lives in `verification/color.py`.

**Subtitle Detection:** `VideoVerificationController.detect_subtitles(image_paths, extract_text)` (and AI-assisted
variants `detect_subtitles_ai*`) — runs OCR/vision analysis on a region to check for subtitle
presence and text.

None of the above are called via a generic `detector.detect_x(video_stream=..., threshold=...)`
API from test scripts — they're internal controller methods invoked as part of the verification
pipeline attached to navigation nodes/edges.

</div>

---

## Storage

Pictures and videos are uploaded to cloud storage. You set the storage keys when the platform is deployed. Old files are removed by a rule you set in the storage bucket.

<div data-technical>

Screenshots and videos upload to Cloudflare R2 (S3-compatible), configured via the `R2_*`
environment variables at deploy time — see [Cloud Setup](../get-started/cloud-setup.md) and
[configuration reference](../get-started/configuration.md). There is no built-in retention/cleanup YAML
config or a configurable public CDN URL beyond what R2 itself provides; manage lifecycle rules
directly in your R2 bucket settings if you need automatic expiry.

</div>

---

## Streaming & Encoding

The host turns the picture into a stream with FFmpeg, and the stream adjusts itself. If the host has a supported graphics chip, the stream is encoded on the chip, which is faster. NVIDIA chips are not supported.

<div data-technical>

Live streaming and capture run through FFmpeg on the host
(`backend_host/scripts/run_ffmpeg.sh`), with runtime-tunable parameters (adaptive fps,
restart-only tuning) rather than a checked-in HLS/encoding YAML config file.

**Hardware acceleration (VAAPI).** On a host with an Intel or AMD GPU that exposes H.264 encode
through VAAPI, the HLS stream is encoded on the GPU (`h264_vaapi`), and network sources
(RTSP / HLS / video files) are also decoded on it. The capture pipeline detects this by itself
at startup. Without it (e.g. Raspberry Pi 5) it uses software `libx264`. Captures and
thumbnails are always produced on the CPU. To enable it, install the VAAPI driver, plus
`vainfo` and, on AMD, `firmware-amd-graphics`, then restart the stream service. NVIDIA NVENC
is not supported.

</div>

---

## Integration with Tests

Screenshots are taken and compared as part of the test run. You do not call a separate screen check.

<div data-technical>

Screenshot capture and comparison happen as part of the same verification pipeline described
above (navigation-node `verifications`, `ScriptExecutionContext` screenshot tracking) — there is
no separate `controller.verify_screen(reference_image=..., capture_on_fail=...)` call. Test
reports (validation report `.md`, inlined as base64 image data) include source/reference/overlay
images for each verification — see [Running Tests](../user-guide/running-tests.md).

</div>

The report for each run shows the source, reference and overlay pictures for every check. See [Running Tests](../user-guide/running-tests.md).

---

## Monitoring & Alerts

The platform spots black screens, frozen pictures and missing subtitles while it monitors. You set up the alerts in Grafana.

<div data-technical>

Visual-quality issue detection (black screen, freeze, subtitle presence) happens as part of
verification and the monitoring pipeline (`vpt-monitor-img`) — there is no built-in declarative YAML
alert-rule engine wiring these to Slack/incident-creation/device-restart actions. Wire alerting
through Grafana (see [Analytics](analytics.md)) against the underlying metrics tables instead.

</div>

---

## Hardware Requirements

### For HDMI Capture

- An HDMI capture card (USB or PCIe). Elgato, AVerMedia or a generic USB 3.0 card all work.
- A USB 3.0 port for USB capture cards
- Enough disk space, or cloud storage

### For VNC Capture (virtual displays)

- A VNC server on the web or desktop test host
- A network connection, with under 1 Mbps per stream

---

## Benefits

Visual evidence shows what happened at every step. It makes reports clear to people who are not engineers, and it spots problems as they happen.

<div data-technical>

- **Complete Visibility:** nothing is left to guess. There is a full visual record of every action.
- **Faster Debugging:** screenshot timeline and video replay cut debugging time by 90%.
- **Better Reporting:** visual evidence makes test reports clear to people who are not engineers.
- **Continuous Monitoring:** round-the-clock streaming spots problems as they happen.

</div>

---

## Next Steps

- [AI Validation](./ai-validation.md): analyze captures automatically
- [Analytics](./analytics.md): monitor quality metrics
- User Guide: Monitoring: set up monitoring
- Technical Docs: Video Architecture

---

**Ready to see everything your devices do?**
[Get Started](../get-started/README.md)
