# Frequently Asked Questions

Quick answers to the most common questions about VirtualPyTest.

---

## Overview

### What is VirtualPyTest?

VirtualPyTest tests and monitors any device with a screen: phones, TVs, set-top boxes, web browsers and anything with an HDMI output. Write a test once and run it on every platform.

<div data-technical>

AI also watches the screens 24/7 and flags black screens, freezes and lost audio. The test says what to check. A navigation tree says how to get to each screen on each device. AI looks at the screen itself instead of fragile selectors, so tests keep working after a redesign. For monitoring, every device's screen is captured through HDMI all the time, and Grafana dashboards show the health of the whole fleet.

</div>

**Software:** free and open source under AGPL v3. You host it yourself. See [Is it really free?](#is-it-really-free).

**Hardware:** a Raspberry Pi 5 host with HDMI capture cards. See the [hardware guide](../get-started/hardware.md).

**Where to start:** the [Get started](../get-started/README.md) guide walks through installation and your first test.

---

## Core Concepts

### How does one script work for all devices?

Your test says what to check. The navigation tree knows how to reach each screen on each device.

<div data-technical>

Navigation is stored as a tree:

- **Nodes** are screens or destinations, such as "home", "settings" or "live_tv".
- **Edges** are the actions that move between screens, such as pressing OK or swiping left.

Your test only says what to check:

```python
navigate_to("settings")
verify_screen("settings")
# Run your test logic here
```

The navigation tree works out the button presses for each device. The same test runs on Android, iOS, a set-top box or the web, each with its own tree. AI can generate navigation trees automatically.

</div>

<div data-technical>

**Benefits:** write once, run on any device, and change the navigation without touching the test logic.

</div>

---

### What is a navigation tree?

A map of the screens and the actions between them. The pathfinder finds the route between any two screens.

<div data-technical>

Each edge stores the way forward and the way back: forward actions (how to go from A to B) and reverse actions (how to go from B to A).

```
home ──[press OK]──► settings ──[press DOWN, OK]──► wifi_settings
  ▲                      │
  └──────[press BACK]────┘
```

</div>

---

### What devices are supported?

Almost any device that can be controlled remotely. The table lists the main kinds.

| Category | Examples |
|----------|----------|
| **Mobile** | Android phones/tablets, iOS (iPhone, iPad) |
| **TV/Streaming** | Android TV, Apple TV, Fire TV, Smart TVs (Samsung, LG) |
| **Set-Top Boxes** | Any STB with IR or network control |
| **Web** | Any browser (Chrome, Firefox, Safari, Edge) |
| **Desktop** | Windows, macOS, Linux applications |
| **HDMI Devices** | Any device with HDMI output + remote control capability |

<div data-technical>

**Control methods supported:**

- ADB (Android)
- Appium (iOS/Android)
- IR blasters (STB, TV)
- Network APIs (Smart TVs)
- Browser automation (Web)

</div>

---

## Features

### How does AI validation work?

Instead of fragile selectors or pixel matching, **vision AI** checks the screen:

1. Take a screenshot of the current screen.
2. A vision model describes what is visible.
3. Check that the expected content is there.

<div data-technical>

**Example:**

```python
# Instead of: find_element(id="settings_title").text == "Settings"
# You do:
verify_screen("settings")  # AI confirms this looks like a settings screen
```

</div>

**Why this matters:** it works the same on every platform, and it survives UI redesigns.

<div data-technical>

Because there are no brittle selectors, it also spots visual bugs that a person would notice.

</div>

---

### How does visual capture work?

**Real devices:** the picture comes from an HDMI capture card, the video users actually see. **Emulators:** ADB screencap.

**What you get:** a frame-by-frame replay of every test, a screenshot timeline and visual evidence for bug reports.

<div data-technical>

The HDMI picture does not depend on the device's accessibility features.

</div>

---

## Getting Started

### What are the prerequisites?

You need Docker and Docker Compose. Each device type needs its own access, shown in the table.

| Device Type | Requirements |
|-------------|--------------|
| Android | ADB access (USB or WiFi) |
| iOS | Mac with Xcode, Appium |
| STB/TV | IR blaster or network API |
| HDMI capture | USB capture card |
| Web | Chrome/Firefox installed |

<div data-technical>

**Minimum requirements:** Docker and Docker Compose (recommended), and Python 3.11+ for local development.

**Quick start:**

```bash
git clone https://github.com/AngelStreetCorp/virtualpytest.git
cd virtualpytest
./setup/docker/install_docker.sh
./setup/docker/launch.sh
```

</div>

See the [Get started guide](../get-started/README.md) for the full walkthrough.

---

### How is VirtualPyTest different from Appium/Selenium?

| Aspect | VirtualPyTest | Appium/Selenium |
|--------|---------------|-----------------|
| **Approach** | Visual-first, platform-agnostic | DOM/selector-based, platform-specific |
| **Script portability** | Same script for all devices | Different scripts per platform |
| **Validation** | AI vision (semantic) | Element selectors (brittle) |
| **STB/TV support** | Built-in (IR, HDMI capture) | Not supported |
| **Cost** | Free (AGPL v3) | Free (but commercial tools cost $50k+) |
| **Monitoring** | Built-in Grafana dashboards | Requires separate tools |

**VirtualPyTest works alongside Appium and Selenium.** It uses them for mobile and web, and adds one layer on top.

---

## Practical Usage

### How do I add a new device?

1. **Create a controller** for your platform.
2. **Build a navigation tree.** AI can help.
3. **Configure the connection** with the device's details.

For common platforms, controllers already exist: Android (ADB), iOS (Appium), Web (Playwright/Selenium) and IR-controlled devices. See the [Controller Creation Guide](../technical/architecture/CONTROLLER_CREATION_GUIDE.md).

---

### Can I run tests in CI/CD pipelines?

Yes. Your pipeline starts a run through the REST API, then reads the result.

<div data-technical>

```bash
# Trigger a script execution via the backend_server API
curl -X POST "http://localhost:5109/server/script/execute?team_id=<your-team-id>" \
  -H "Content-Type: application/json" \
  -d '{"host_name": "my-host", "device_id": "device1", "script_name": "validation"}'
```

VirtualPyTest itself does not publish a single all-in-one Docker image for CI. Instead, run the stack with the setup scripts (`setup/docker/`) as part of your pipeline. Or point your CI at a server and host that are already running, and drive them through the REST API above.

</div>

**Completion messages:** long runs can send a message to an address you give when they finish. See the [webhook documentation](../technical/webhook.md). It is a generic web call, not a built-in Slack or JIRA integration.

<div data-technical>

The message is an HTTP POST to the `callback_url` you provide.

</div>

---

### Is it really free?

**Yes.** It is free and open source under the [GNU AGPL v3](https://www.gnu.org/licenses/agpl-3.0). You can use and host it yourself at no cost.

If you distribute a modified version, or offer it as a service, publish your changes under the same license.

<div data-technical>

There are no paid tiers, feature limits or usage limits, and you get the full source code. Including internal business use is allowed. For commercial licensing outside these terms, contact the author. The license text is in the `LICENSE` file.

</div>

**Why free?** Commercial tools cost $50k+ a year and lock you into one vendor's ecosystem.

<div data-technical>

**How to support the project:** star the repo, report bugs, contribute code or spread the word.

</div>

---

## Evaluating a Testing Vendor

Five questions to ask any vendor, with our answers.

### Can you test our production app on multiple platforms without changing our code?

**Yes.** Nothing is installed in your app. The same script runs on TV, mobile and web. The [navigation tree](#what-is-a-navigation-tree) holds what differs per platform.

<div data-technical>

The screen is captured from the outside: HDMI capture, camera, screen mirroring or browser. The device is driven with IR or Bluetooth remote, ADB, Appium or Playwright. Per-model variants override only the screens that change.

</div>

See [Unified controller](../features/unified-controller.md).

---

### Can you show a live event monitored on multiple platforms, with a recording of what viewers saw?

**Yes.** Every screen is visible at once, and each HDMI output is recorded all the time in a rolling 24-hour buffer.

<div data-technical>

A fleet heatmap shows which devices are in trouble. The recording is video and audio, with a transcript. An incident keeps its start and end frames as evidence.

</div>

See [Visual capture](../features/visual-capture.md).

---

### Do you measure picture and sound quality, or only whether a screen appeared?

**Both.** Every captured frame is checked, 24/7.

| Check | Detects |
|-------|---------|
| **Picture** | Black screen, freeze, blurriness, blockiness (macroblocks are optional, off by default to save CPU) |
| **Sound** | Audio loss, silence, loudness (LKFS), saturation or distortion |
| **Content** | Subtitles (OCR with language detection), zapping, banners |
| **Score** | An approximate MOS from 1 to 5 each minute, charted in Grafana |

The score is an indicator, not a certified broadcast-lab measurement.

<div data-technical>

VMAF is not included, which is why the MOS is only approximate.

</div>

See [AV quality](../features/avq.md).

---

### What happens to our tests when we redesign the app or switch language?

**The tests do not change.** A redesign only touches the navigation tree.

**Limit:** a full redesign still needs a person to review the updated tree. There is no fully automatic re-mapping.

<div data-technical>

Tests name destinations such as `navigate_to("settings")`.

- **Redesign:** recapture the affected reference images in one click, or let AI exploration rebuild the screens and actions. The tree keeps its history, so each version can be looked at again.
- **Language switch:** screens are recognised by a layout fingerprint that tolerates translated text. Text checks use OCR with language detection and fuzzy matching. Transcripts can be translated.

</div>

---

### What will 24/7 monitoring on all our devices cost per month, with no surprises?

**Software: €0 a month.** You host it yourself.

**Hardware is a one-time cost.** See the [hardware guide](../get-started/hardware.md):

| Setup | Approx. cost |
|-------|--------------|
| 1 device (Raspberry Pi 5 host + HDMI capture card) | ~€420 |
| Up to 4 devices on the same host | ~€480 |
| Each extra capture card | ~€7 |

Your only running cost is electricity, plus storage if you keep recordings longer than the default 24 hours.

<div data-technical>

There are no licence fees, no per-device fees and no usage limits. Keeping recordings costs roughly 7.5 GB per device per day.

</div>

---

## Need More Help?

- [Full Documentation](../README.md)
- [GitHub Discussions](https://github.com/AngelStreetCorp/virtualpytest/discussions)
- [Report Issues](https://github.com/AngelStreetCorp/virtualpytest/issues)
