# 📱 Mobile App & Phone as a Device

**Install one app. Run the lab from your phone, or turn the phone into a device under test.**

The VirtualPyTest mobile app is an Android APK that does two things: it runs the web UI in a phone-friendly shell, and it can pair the phone to a host so the phone itself becomes a test device — screen streamed, taps and keys driven by scripts, like any set-top box or emulator.

---

## The Problem

Testing a real phone usually means cables, developer mode and a computer next to it:
- ❌ ADB needs USB debugging, a workstation and a driver that behaves
- ❌ A phone used by testers all day can't be tied to a desk
- ❌ Checking a run or restarting a test from the corridor means opening a laptop

---

## The VirtualPyTest Solution

✅ **Scan a QR code, the phone is a device** — pick a free phone slot on a host, scan the code from the app, and the phone starts streaming its screen to that host
✅ **Everything else is unchanged** — the stream, captures, image/OCR/video verification, navigation trees, scripts and reports drive the phone exactly like every other device
✅ **Your Android tests just work** — a navigation tree built for an Android phone runs on a paired one unchanged: its on-screen element checks read the phone's own accessibility tree instead of ADB
✅ **No root, no cable** — the app uses Android's own screen-capture and accessibility services, so any phone works, on Wi-Fi, from anywhere the host is reachable
✅ **You can see when it's under test** — a phone being driven shows a pulsing `● UNDER TEST` badge and a blue notification, and draws each command as it arrives: a ripple where a tap landed, a trail for a swipe, a caption naming the action. A phone doing things by itself on a desk is otherwise indistinguishable from a broken one
✅ **The lab in your pocket** — the same app opens the platform in a phone layout: dashboard, run tests, last runs, monitoring

---

## How It Helps

- Add a real phone to the fleet in under a minute, with nothing installed on a computer
- Test on the exact phone models your users own, not only on emulators
- Rerun a test or check a device from the phone, wherever you are
- One APK serves every deployment: the server address is set when you scan the code, not when the app is built

---

## Where to Find It

- **Settings → Mobile app & phones** — download the app, pair a phone, see every phone slot and its state
- **In the app: More → This phone** — pairing status, permissions checklist, scan or unpair

A phone slot is a device line in a host's `.env` with model `phone_agent`; the technical page below shows the exact lines.

---

## Next Steps

- 🔧 [Technical: pairing walkthrough, permissions, troubleshooting](../technical/MOBILE_APP.md)
- 🧪 [Test Automation](./test-automation.md) - Build navigation trees and tests for the paired phone
- 🎮 [Unified Device Controller](./unified-controller.md) - The same script across phone, TV and STB

---

**Ready to pair your first phone?**
➡️ [Get Started](../get-started/README.md)
