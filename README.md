# VirtualPyTest

[![License: AGPL v3](https://img.shields.io/badge/License-AGPL_v3-blue.svg)](https://www.gnu.org/licenses/agpl-3.0)
[![Docker](https://img.shields.io/badge/docker-ready-blue.svg)](https://www.docker.com/)
[![Python](https://img.shields.io/badge/python-3.9%2B-blue)](https://www.python.org/)
[![Documentation](https://img.shields.io/badge/docs-latest-brightgreen)](https://virtualpytest.angelstreet.io/docs)
[![Live demo](https://img.shields.io/badge/Try_Live-VirtualPyTest.com-orange)](https://www.virtualpytest.com/)

<div align="center">
  <h3><b>Open-source automation and monitoring for any device with a screen.</b></h3>
  <p>One script, every device. No per-seat licenses. No vendor lock-in.</p>
  <p>
    <a href="https://www.virtualpytest.com/"><b>Live demo</b></a> •
    <a href="https://virtualpytest.angelstreet.io/docs/features"><b>Features</b></a> •
    <a href="docs/get-started/README.md"><b>Get started</b></a> •
    <a href="https://virtualpytest.angelstreet.io/docs"><b>Documentation</b></a> •
    <a href="#community--support"><b>Community</b></a>
  </p>
</div>

<div align="center">
  <a href="https://www.virtualpytest.com/">
    <img src="/frontend/public/screenshot/dashboard.png" alt="VirtualPyTest dashboard" width="100%">
  </a>
</div>

---

## What it is

VirtualPyTest captures what a device shows (HDMI, camera, screen mirroring, browser) and drives it back (IR, Bluetooth remote, ADB, Appium, Playwright). On top of that it gives you a navigation graph of your app, a test runner, 24/7 monitoring, and Grafana analytics.

It runs on Linux, Raspberry Pi, Docker, or the cloud, and targets set-top boxes, Android TV, mobile phones, web apps, and anything else you can point a capture card at. It is built to replace commercial device-testing suites that cost $50k+ per year.

---

## Features

<!-- Mirror of docs/features/README.md (the in-app Features page). Keep order and titles in sync. -->

<table>
  <tr>
    <td width="50%" valign="top">
      <img src="/frontend/public/screenshot/features/navigation-tree.webp" alt="Navigation tree" width="100%"><br>
      <b>Map your app once, every test reuses it.</b><br>
      Every screen and path becomes a reusable graph. Change a screen once and every test follows.
    </td>
    <td width="50%" valign="top">
      <img src="/frontend/public/screenshot/features/no-code-python.webp" alt="No-code builder and Python" width="100%"><br>
      <b>No-code for the team, Python for the engineers.</b><br>
      Visual drag-and-drop builder for everyone. Full Python the moment you need real logic.
    </td>
  </tr>
  <tr>
    <td width="50%" valign="top">
      <img src="/frontend/public/screenshot/features/cross-platform.webp" alt="One script, every platform" width="100%"><br>
      <b>One script, every platform.</b><br>
      The navigation graph keeps the UI out of the script. Named variants override only what differs per model.
    </td>
    <td width="50%" valign="top">
      <img src="/frontend/public/screenshot/features/verification-proof.webp" alt="Verification proof" width="100%"><br>
      <b>It proves what is actually on screen.</b><br>
      Image matching, OCR text, and AI detectors. Every check shows source, reference, and pixel diff.
    </td>
  </tr>
  <tr>
    <td width="50%" valign="top">
      <img src="/frontend/public/screenshot/features/black-screen-detection.webp" alt="Black screen detection" width="100%"><br>
      <b>Black screen, freeze, audio loss, caught in real time.</b><br>
      Every device watched around the clock. Incidents alerted the moment they happen and tracked to resolution.
    </td>
    <td width="50%" valign="top">
      <img src="/frontend/public/screenshot/features/ai-agent.webp" alt="AI agent" width="100%"><br>
      <b>Talk to your lab. The AI drives the device.</b><br>
      A real agent on a real model, with a built-in MCP server so any AI client can inspect and control devices.
    </td>
  </tr>
</table>

<details>
<summary><b>Show 10 more features</b> (references, A/V quality, reports, Grafana, heatmap and rewind, fleet, device info, permissions, web UI, health)</summary>
<br>

<table>
  <tr>
    <td width="50%" valign="top">
      <img src="/frontend/public/screenshot/features/reference-images.webp" alt="Reference library" width="100%"><br>
      <b>Reference images and text, easy to maintain.</b><br>
      One library for every reference. Auto OCR and focus detection, one-click recapture when the UI changes.
    </td>
    <td width="50%" valign="top">
      <img src="/frontend/public/screenshot/features/avq-quality.webp" alt="Audio and video quality" width="100%"><br>
      <b>Audio and video quality, measured every minute.</b><br>
      Per-minute A/V quality KPIs per device, with trends per platform and software version.
    </td>
  </tr>
  <tr>
    <td width="50%" valign="top">
      <img src="/frontend/public/screenshot/features/test-report.webp" alt="Test report" width="100%"><br>
      <b>Every run, a report you can read.</b><br>
      Pass/fail summary with initial and final state, video, and KPI and zapping times captured automatically.
    </td>
    <td width="50%" valign="top">
      <img src="/frontend/public/screenshot/features/grafana-dashboards.webp" alt="Grafana dashboards" width="100%"><br>
      <b>Every result, in native Grafana dashboards.</b><br>
      Pass rates, duration, and volume per script. Per-step KPI radars across versions. Standard Grafana, yours to extend.
    </td>
  </tr>
  <tr>
    <td width="50%" valign="top">
      <img src="/frontend/public/screenshot/features/fleet-heatmap.webp" alt="Fleet heatmap" width="100%"><br>
      <b>A fleet heatmap and 24h of screen to scrub back.</b><br>
      One glance shows where the fleet hurts. Every device's screen is recorded, so you can see what happened at 3 a.m.
    </td>
    <td width="50%" valign="top">
      <img src="/frontend/public/screenshot/features/fleet-status.webp" alt="Fleet status" width="100%"><br>
      <b>Your whole fleet, status and live screen.</b><br>
      Hosts, devices, and system metrics on one dashboard. Live screen of every device, restart services from the browser.
    </td>
  </tr>
  <tr>
    <td width="50%" valign="top">
      <img src="/frontend/public/screenshot/features/device-details-1.webp" alt="Device details" width="100%"><br>
      <b>Device details, read straight off the screen.</b><br>
      Model, firmware, and version auto-extracted from the device's own About screen, in any language.
    </td>
    <td width="50%" valign="top">
      <img src="/frontend/public/screenshot/features/permissions.webp" alt="Permissions" width="100%"><br>
      <b>Permissions, down to the last action.</b><br>
      Scoped per workspace, team, and user. Grant or deny every single action.
    </td>
  </tr>
  <tr>
    <td width="50%" valign="top">
      <img src="/frontend/public/screenshot/features/cross-browser-1.webp" alt="Web UI on desktop and phone" width="100%"><br>
      <b>Runs in any browser, desktop to phone.</b><br>
      Nothing to install. Fully responsive, so you can operate the whole lab from anywhere.
    </td>
    <td width="50%" valign="top">
      <img src="/frontend/public/screenshot/features/device-health-1.webp" alt="Device occupancy and host health" width="100%"><br>
      <b>Every device accounted for, every host healthy.</b><br>
      Device occupancy (busy vs idle, manual vs script) and host CPU, memory, disk, and temperature, 24/7.
    </td>
  </tr>
</table>

</details>

<p align="center">Full feature tour with larger screenshots: <a href="https://virtualpytest.angelstreet.io/docs/features"><b>virtualpytest.angelstreet.io/docs/features</b></a></p>

---

## Quick start

```bash
git clone https://github.com/AngelStreetCorp/virtualpytest.git
cd virtualpytest
./setup/docker/install_docker.sh   # only if Docker is not installed yet
./setup/docker/launch.sh           # full stack: database, server, host, web UI, Grafana
```

`launch.sh` generates every secret, builds the images and prints the URLs when the API answers —
the web UI is on `http://<this-machine>:5073`. Every install path (Docker, one VM, Proxmox
fleet, developer setup) starts from the [Get Started guide](docs/get-started/README.md).

---

## Why VirtualPyTest

| | VirtualPyTest | Commercial tools |
| :--- | :---: | :---: |
| **Cost** | Free, open source | $50k+ / year |
| **Runs on** | Linux, Raspberry Pi, Docker, cloud | Often Windows only |
| **Source code** | Yours to read and modify | Vendor locked |
| **Monitoring, analytics, AI** | Included | Paid add-ons |

---

## Status

Actively developed and used in production. See the [release notes](docs/release_note/README.md) for what ships in each build, and [GitHub Issues](https://github.com/AngelStreetCorp/virtualpytest/issues) for what is planned or in progress.

Running it yourself? The installers ship LAN-friendly defaults. Before a deployment faces the internet, go through the [production hardening checklist](docs/get-started/production-checklist.md).

---

## Community & Support

- **🐛 Issues**: report bugs or request features on [GitHub Issues](https://github.com/AngelStreetCorp/virtualpytest/issues).
- **💬 Discussions**: ask questions and share ideas in [GitHub Discussions](https://github.com/AngelStreetCorp/virtualpytest/discussions).
- **🤝 Contributing**: see [CONTRIBUTING.md](CONTRIBUTING.md).
- **💖 Sponsor**: support the project on [GitHub Sponsors](https://github.com/sponsors/angelstreet).

---

## License

VirtualPyTest is open source under the [GNU AGPL v3](LICENSE). Free to use, study, modify, and self-host, including for commercial internal use. If you distribute a modified version or offer it to others as a service, you must publish your modifications under the same license. For commercial licensing outside these terms, contact the author.
