# BUG-0142 — The mobile app took whatever rotation the device was in, so the same test produced sideways evidence on one vendor

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                                       |
|-----------|-----------------------------------------------------------------------------|
| ID        | BUG-0142                                                                    |
| Reported  | 2026-09-17                                                                  |
| Status    | Fixed (APK rebuilt and uploaded to both farms; not yet in a released build)  |
| Severity  | Medium (screenshots and video unusable for comparison; no functional failure) |
| Area      | `features/mobile-app/app/android/app/src/main/AndroidManifest.xml`           |

---

## Symptom

The same navigation script, the same tree, the same APK, run against two cloud device farms:

| | Sauce Labs (Galaxy S23 FE) | BrowserStack (Galaxy S23) |
|---|---|---|
| Report screenshot | 1080x2340 portrait | **2340x1080 landscape** |

Both runs passed. Only the evidence differed — the BrowserStack frames were sideways, with the
Android navigation bar down the right-hand edge.

## Root cause

`MainActivity` declared no `android:screenOrientation`, so it adopted whatever rotation the
device happened to be in when it was launched. On a phone in someone's hand that is the right
behaviour and nobody notices. On a cloud farm there is no hand, and two vendors' devices differ.

Isolated against a live BrowserStack session:

| Step | `driver.orientation` | Screenshot |
|---|---|---|
| Session auto-launches the app (`appium:app`) | `PORTRAIT` | 1080x2340 |
| `activate_app(...)` — what the tree's `launch_app` action calls | *empty* | **2340x1080** |
| Then forcing `driver.orientation = 'PORTRAIT'` | `PORTRAIT` | **2340x1080** |

So the flip happens on relaunch, and setting the orientation back over the wire does **not**
restore it — the activity has already taken landscape. Sauce's device happened to relaunch
portrait, which is why only one vendor looked wrong.

## Fix

Pin `MainActivity` to `android:screenOrientation="portrait"`.

The file already carried the precedent and the argument: `CaptureActivity` (the QR scanner) was
pinned to portrait with a comment noting every screen in this "phone-held-in-portrait app" is
laid out for it. `MainActivity` was simply the one that had never been asked to prove it on a
device nobody was holding. `android:configChanges` already lists `orientation`, so the lock costs
no activity recreation.

## Gate

The built APK's own manifest, read back with `aapt2 dump xmltree`: two activities with
`android:screenOrientation=1` (`SCREEN_ORIENTATION_PORTRAIT`) — `MainActivity` and
`CaptureActivity`.

Then at the consumer, on `host-clone-1`, with the rebuilt APK uploaded to both farms and both
slots repointed at it:

| | Sauce Labs | BrowserStack |
|---|---|---|
| Result | SUCCESS, 58.4s, 4 screenshots | SUCCESS, 55.2s, 6 screenshots |
| Report | HTTP 200, 66,727 B | HTTP 200, 67,686 B |
| Final frame | **1080x2340** | **1080x2340** |

Both portrait, nav bar at the bottom, layout correct.

## Not to be confused with

[BUG-0141](BUG-0141-2026-09-17-new-farm-slot-blocks-every-grabber.md)'s placeholder, which had its
own orientation fault: the host grabber reads portrait-vs-landscape off the source image's aspect,
so a square 16x16 seed read as landscape and rotated the pipeline regardless of the device. That
was fixed separately (the seed is now 108x234). Both had to be right before the evidence was.
