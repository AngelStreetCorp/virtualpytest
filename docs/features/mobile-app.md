# Mobile App & Phone as a Device

**Install one app. Run the lab from your phone, or turn the phone into a device under test.**

The VirtualPyTest mobile app is an Android app. It shows the web app in a phone layout, and it can turn your phone into a test device.

---

## Why it exists

Testing a real phone usually means cables, developer mode and a computer beside it.

<div data-technical>

- Connecting by ADB needs USB debugging, a computer, and a working driver.
- A phone that testers use all day cannot be tied to a desk.
- Checking a run or restarting a test from another room means opening a laptop.

</div>

---

## What you get

- **Scan a QR code, and the phone is a device.** Pick a free phone slot on a host, then scan the code in the app.
- **Your Android tests work too.** A navigation map built for an Android phone runs on a paired phone unchanged.
- **No root, no cable.** The app uses Android's own screen-capture and accessibility features. Any phone works over Wi-Fi.
- **You can see when it is under test.** A phone being driven shows a pulsing `● UNDER TEST` badge.

<div data-technical>

- **Everything else stays the same.** The stream, captures, image, text and video checks, navigation maps, scripts and reports all work on the phone, just as on any other device. Its on-screen checks read the phone's own accessibility information instead of using ADB.
- **The lab in your pocket.** The same app opens the dashboard, run tests, last runs and monitoring.
- Rerun a test or check a device from your phone, wherever you are. Each command appears on screen as it arrives.
- A blue notification also shows while the phone is under test. Each command gets a ripple where a tap landed, a trail for a swipe, and a caption naming the action. Without this, a phone moving by itself on a desk looks broken.

</div>

---

## What it is good for

- Add a real phone to the fleet in under a minute, with nothing installed on a computer.
- Test on the exact phone models your users have, not only on emulators.

The server address is set when you scan the code, so one app works with every deployment.

---

## Where to find it

- **Settings → Mobile app & phones.** Download the app, pair a phone, and see every phone slot and its state.
- **In the app: More → This phone.** Pairing status, the permissions checklist, and buttons to scan or unpair.

<div data-technical>

A phone slot is a device line in a host's `.env` with model `phone_agent`. The technical page below shows the exact lines.

</div>

---

## Next Steps

- [Technical: pairing walkthrough, permissions, troubleshooting](../technical/MOBILE_APP.md)
- [Test Automation](./test-automation.md): build navigation maps and tests for the paired phone
- [Unified Device Controller](./unified-controller.md): the same script across phone, TV and set-top box

---

**Ready to pair your first phone?**
[Get Started](../get-started/README.md)
