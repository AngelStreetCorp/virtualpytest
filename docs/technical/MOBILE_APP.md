# Mobile app & phone as a device (`features/mobile-app`)

> Optional feature, see [FEATURES.md](FEATURES.md). Plan and decisions:
> `docs/tasks/TASK-17-mobile-app-phone-agent.md` (internal). Reuses the image-file capture
> path described in `docs/agent/devices/ANDROID_EMULATOR_TROUBLESHOOT.md`.

## What it is

One Android APK, two jobs:

1. **The VirtualPyTest frontend in an app**, so an admin can run the whole platform from a
   phone. The phone/tablet *layout* it shows (bottom nav, mobile Run Tests, responsive pages) is
   **core** web UI, served to any small-screen browser and unaffected by disabling this feature;
   the app only wraps it and injects the server address at runtime.
2. **A phone as an extra device under test.** Scan a QR code and the phone streams its screen to
   a host and accepts taps, swipes, keys, text and app launches. The rest of the platform (HLS
   stream, captures, image/OCR/video verification, navigation trees, scripts, reports) drives it
   exactly like any other device.

The phone never runs Python and is never a host. It is a frame source and input sink attached to
an existing host (Raspberry Pi, VM, host-clone). Device model `phone_agent`, remote
implementation `phone_agent`, AV controller `hdmi_stream`.

## How the phone becomes a device

The phone captures its own screen (Android MediaProjection) and encodes JPEG frames natively. It
pushes each frame to the host over Socket.IO. The host writes every frame to
`phone_frames/deviceN/latest.jpg`. `run_ffmpeg.sh` picks this up through its existing `imagefile`
source, the same path the Android emulator fleet already uses to turn a still-image file into an
HLS stream and numbered captures. Nothing in the streaming or verification pipeline changes.

Input runs the other way: the host sends a command over the same socket, and an
AccessibilityService on the phone performs it (gesture, global action, text input into the
focused field, or a UI node-tree dump). Coordinates are native device pixels, reported once at
pairing time, the same contract `android_mobile` already uses for the stream-click overlay.

Frames and commands stay entirely between the phone and the host. They never transit
`backend_server`.

## Slot provisioning

A phone attaches to a **pre-provisioned slot** on a host, the same `DEVICEn_*` block any other
device uses. Add one block per phone slot to the host's `.env`:

```bash
DEVICE2_NAME=Phone slot 1
DEVICE2_MODEL=phone_agent
DEVICE2_VIDEO=/var/www/html/stream/phone_frames/device2/latest.jpg   # .jpg -> run_ffmpeg "imagefile"
DEVICE2_VIDEO_CAPTURE_PATH=/var/www/html/stream/capture2
DEVICE2_VIDEO_STREAM_PATH=/host/stream/capture2      # same convention as every other device
DEVICE2_VIDEO_FPS=3
# optional
PHONE_AGENT_FPS=3            # frames/s requested from the phone (default 3)
PHONE_AGENT_MAX_SIDE=1280    # phone scales frames so the long side <= this
PHONE_AGENT_STATE_FILE=/var/www/html/stream/phone_frames/state.json
```

Restart the host services after editing: `sudo systemctl restart vpt-host vpt-stream`.

> ⚠️ **A new slot also needs RAM hot storage, or its report videos are silently truncated.**
>
> ```bash
> sudo ./setup/local/linux/backend_host/setup_ram_hot_storage.sh
> ```
>
> Hot storage is a tmpfs at `<DEVICEn_VIDEO_CAPTURE_PATH>/hot`, and nothing creates it
> automatically — no installer, no deploy, no boot hook calls that script. A capture folder
> without `/hot` puts the archiver in "SD mode", where it prunes but never writes the
> 10-minute chunks the report video is rebuilt from. The run still passes and a video is still
> produced; it is just cut down to the live HLS window (about 30 s), with the rest reported as
> `missing` in the log and nowhere else. A 94 s test came back as 30 s of footage before this
> was noticed.
>
> This is **per slot, not per pairing** — `/hot` belongs to the capture folder, so pairing,
> unpairing or swapping the phone on an existing slot needs nothing. It is also not specific to
> phones: any device added to any host after the last run of that script has the same hole.
> Verify with `ls -d <capture path>/hot` and `ls <capture path>/segments/*/chunk_10min_*.mp4`.

At start, the feature writes a placeholder frame ("Phone slot 1 - not paired", portrait
720x1280) into every configured slot, so `vpt-stream` has a valid source immediately. On
disconnect it writes a "phone offline" placeholder after 5 seconds, so the stream and the
capture monitor never see a frozen file.

## Pairing walkthrough

1. Open **Settings -> Mobile app & phones** (`/configuration/mobile-app`).
2. Pick a host that has `phone_agent` slots and click **Pair...** on a free slot.
3. The page shows a QR code that expires in 10 minutes.
4. On the phone, open the app's **Phone** tab and choose **Scan QR code** (first run) or
   **Scan pairing QR** (already installed). Scan the code from step 3.
5. The phone stores the config, starts its background service and connects to the host. The
   slot's status turns from "pending" to the phone's real name and resolution, and the stream
   goes live within one HLS segment.

There are two kinds of QR code:

| Kind | Contains | Effect when scanned |
|---|---|---|
| `pair` | Server URL, Supabase settings, host connection info, one-time token | Configures the app **and** pairs it to the slot |
| `config` | Server URL, Supabase settings only, no host or token | Configures the app only (no pairing); shown under "Get the app" for a fresh install |

Unpairing (from the web page or from the phone's Phone tab) revokes the phone's credentials,
disconnects it, and restores the slot's placeholder name and image.

## Execution overlay

Every command the host sends draws itself on the phone's own screen: a ripple where a tap
landed, a trail following a swipe, and a caption naming the command — `tap 540,1200`,
`swipe left`, `key BACK`, `launch com.android.settings`, `dump UI`, `screenshot`.

Without it a phone under test looks possessed: things happen with no sign that a script rather
than a person is driving, and when nothing happens there is no way to tell a command that never
arrived from one that arrived and was ignored.

It is drawn by the **AccessibilityService** (`TYPE_ACCESSIBILITY_OVERLAY`), so it costs no extra
permission — drawing from anywhere else would need SYSTEM_ALERT_WINDOW, another settings trip
and another row that could hold up pairing.

**The per-action visuals are transient by design.** The overlay is part of the screen, so
MediaProjection records it like anything else, and a caption still up when a verification grabs
its frame is a caption inside the evidence. A ripple lasts 450 ms, a swipe trail 600 ms, a
caption 900 ms — all well inside the shortest `wait_time` a tree uses. `screenshot` is announced
*after* the grab for the same reason, and `text` is announced without its value, since a tree
can carry a credential there.

### "Under test", while it lasts

Per-action flashes answer "what just happened?" but not "is something driving this phone right
now?" — which is the question you have when you glance at a handset on a desk. So a phone being
driven also shows a pulsing **`● UNDER TEST`** badge in its top-right corner, and its
notification turns blue and reads *"under test"* instead of *"connected"*.

The protocol carries no run-start or run-end event, so that state is **inferred from traffic**:
every command raises it and 45 s of quiet drops it. The number is a compromise worth knowing
about — a navigation step can sit quiet for a while (a 60 s video verification runs entirely on
the host and sends the phone nothing), so a shorter window flickers mid-run and a longer one
outstays a finished script.

The badge is the one visual here that **deliberately persists**, which means it *is* in the
captured frames for as long as a script runs. It is kept small and pinned to the strip above app
content for that reason. A dropped link clears it immediately, whatever the timer thinks.

Turn the whole overlay off — badge included — with **This phone → "Execution overlay"** when a
capture must be pristine, or when a tree's image references were captured before the badge
existed. On by default: a phone being driven should say so unless someone decides otherwise.

## Starting an app from a known place

`close_app` on a phone **does not close the app**. Unrooted Android has no force-stop API, so
the agent does the closest thing available to it — `performGlobalAction(GLOBAL_ACTION_HOME)` —
and the app carries on in the background exactly as it was. A following `launch_app` then
resumes that task.

So the familiar `close_app` → `launch_app` pair, which on an adb device really does restart the
app, on a phone means *"go to the launcher, then put the app back where it was"*. Leave YouTube
on a video and that pair returns you to the video, not the feed — and a first step that verifies
the feed's bottom nav fails on a screen that has never had one.

`launch_app` therefore takes `reset` (agent ≥ 1.0.38):

```json
{"command": "launch_app", "params": {"package": "com.google.android.youtube", "reset": true}}
```

`reset` adds `FLAG_ACTIVITY_CLEAR_TASK` to the launch intent, which clears the app's task before
starting it — the same end state a force-stop would give, with no permission. In the action list
it is **Restart App (from its entry point)**, a preset of the same `launch_app` command rather
than a new one, so nothing else has to learn about it.

It is **off by default** in both directions: a tree that relies on resuming where it left off
keeps working, and an agent older than 1.0.39 simply ignores the flag and launches as it always
did (the host omits the key entirely when it is false, so the payload is byte-identical to
before). The two are deployed independently, so neither side may assume the other has been
updated.

`reset` does **not** need a `close_app` in front of it — it replaces one. `close_app` only
presses HOME, so pairing the two just puts the launcher in front for a moment before the
relaunch. Measured on a Galaxy S21 (agent 1.0.39), starting from a full-screen player:

| sequence | where it ends up |
|---|---|
| `launch_app` | **player** — resumed, which is the whole problem |
| `launch_app` + `reset: true` | **feed**, within 5s |
| `close_app` then `launch_app` + `reset: true` | feed |

CLEAR_TASK is not combined with CLEAR_TOP: the two are not meaningful together, and the plain
launch keeps CLEAR_TOP as it always had.

Not offered on `android_mobile`: an adb device gets the same effect from `close_app`, which
there really is a force-stop.

## Permissions the phone must grant

| Permission | Why |
|---|---|
| Accessibility service | Required for every input command (tap, swipe, key, text, UI dump). Without it, commands from the host silently do nothing. |
| Screen capture (MediaProjection) | Requested once per app session; without it the phone cannot produce frames and the stream stays on the placeholder. |
| Battery: unrestricted | The capture and Socket.IO connection run in a foreground service; an aggressive battery saver can kill it between test runs. |

## Reachability

The phone tries the host's LAN address first (`host_api_url`, direct port `6109`). If that
fails, it falls back to the host's proxied URL through nginx
(`<host_url>/phone/socket.io`, namespace `/phone`). The fallback location is a **manual nginx
edit** on the existing reverse proxy (the standard `/host/<name>/api/` block does not forward
WebSocket upgrade headers, so a dedicated location is added for the phone path). This edit is a
deploy/ops step, not something the feature configures automatically.

## What works and what does not

| Capability | Status |
|---|---|
| Taps | Yes |
| Swipes | Yes |
| Keys: BACK, HOME, RECENTS, VOLUME_UP, VOLUME_DOWN, POWER, NOTIFICATIONS, QUICK_SETTINGS | Yes |
| Text input into the focused field | Yes |
| Launch app | Yes |
| List launchable apps | Yes |
| UI element dump | Yes |
| UI element verification (`waitForElementToAppear` / `Disappear`, verification type `adb`) read from the accessibility tree — a navigation tree built for an Android phone runs on a paired one unchanged | Yes |
| Screenshot | Yes |
| Image / OCR / video verification (via the normal capture pipeline) | Yes |
| Force-stop an app | No, and it will not be: unrooted Android has no force-stop API. `close_app` presses HOME. Where a tree needs the app to start clean rather than resume, use `launch_app` with `reset: true` — see [Starting an app from a known place](#starting-an-app-from-a-known-place) |
| Audio capture from the phone | Not yet, see follow-ups |
| IR / BLE from the phone | Not yet, see follow-ups |

## Acceptance without a phone

`features/mobile-app/backend_host/phone_sim.py` is a fake phone: a Python Socket.IO client that
pairs with a one-time token, streams a still image at a set frame rate and answers every
command. It is useful to check a slot end to end before an APK is available:

```bash
python3 features/mobile-app/backend_host/phone_sim.py --qr '<payload>'
```

`<payload>` is the JSON from the pairing QR (copy it from the pairing dialog, or from the
`POST /server/mobile-app/pairings` response). The slot should go online, the stream should show
the sim's image, and the slot should be selectable from Run Tests.

## Troubleshooting

| Symptom | Cause |
|---|---|
| Slot stays "pending" | The pairing token expired (10 minute TTL) or the phone is on a different network than the host's `host_api_url` and the nginx fallback location has not been deployed. |
| Stream shows the placeholder image | The phone has not connected, or it has not been granted screen-capture consent for this session. |
| Taps do nothing | The AccessibilityService is disabled on the phone. Enable it from the app's Phone tab permission checklist. |
| Stream is landscape while the phone is held portrait | `run_ffmpeg.sh` detects orientation once, at ffmpeg start. Restart `vpt-stream` on the host after a phone rotates or reconnects at a different orientation. |
| The status-bar dot stays green while a test runs | That dot is **Android's own screen-capture privacy indicator**, not ours — no app can recolour or remove it, and it is there whenever the phone is streaming. What turns blue is VirtualPyTest's notification, plus the `● UNDER TEST` badge the overlay draws. |
| Permissions were green yesterday, screen capture is amber today | Installing a new APK wipes it: MediaProjection consent is per-session and cannot be persisted, and Android also disables an AccessibilityService on package replace. Both are one tap each from the checklist. |
| A verification says "Video did not appear" while the video is plainly playing | Almost always the motion **region**, not the video. Motion detection defaults to the centre 60% of the frame — right for a TV, wrong for a portrait phone, where the player sits across the top ~28% and the middle is static page content. Read the `Motion restricted to area x=…` log line and check that rectangle against where the player actually is, then set an explicit `area` on the verification (in **capture** pixels, not device pixels). [BUG-0122](../bugs/BUG-0122-2026-09-16-motion-check-measures-below-a-portrait-players-video.md) |
| Consecutive `capture_*.jpg` are byte-identical | Normal: the phone streams ~3 fps while ffmpeg writes captures faster, so frames repeat. Not evidence of a stall — compare frames further apart. |
| A relaunched app shows an empty feed or an undrawn player for seconds | Also normal, and it imitates both of the rows above. Give it time before drawing conclusions from a frame. |
| Download looks "stuck" after tapping the APK link | It usually isn't the download — the APK is outside the Play Store, so Android blocks the install with "not allowed to install unknown apps from this source" once the file lands. Open the downloaded file, tap Settings on that warning, enable "Allow from this source" for the browser, then install. |

## Building the APK

See `features/mobile-app/app/README.md` for build, run and signing instructions for the
Capacitor/Android project.

## What stays in core when the feature is off

Only inert hooks: the controller registry (remote **and** verification implementations) and
`register_feature_controllers`, the `phone_agent` model in `device_capabilities.py` / `device.py`
(verification map `['adb']`), the `phone_agent` case of the remote panel, the `previewActions`
slot of `config/features.ts` (an unpaired slot's REC card offers its pairing code), the
runtime config reader (`window.__VPT_CONFIG__`, shared with the Docker install), the APK's
origin in the default CORS list, the feature-gated More-menu and footer entries, the commented
phone-slot block in the host `.env.example`, and the nginx `/host/<name>/phone/socket.io/`
location. The full table, kept current, is `features/mobile-app/README.md` ("Core hooks").

## See also

- [Feature page](../features/mobile-app.md): what it is and where to find it, for users.
- `features/mobile-app/README.md`: parts, core hooks, tests, how to disable.
- `docs/agent/devices/PHONE_AGENT.md`: for agents — pair from the API, the fake phone, what commands and verifications work, the isolation check.
- `docs/tasks/TASK-17-mobile-app-phone-agent.md`: full architecture, wire protocol and work plan.
- `docs/agent/devices/ANDROID_EMULATOR_TROUBLESHOOT.md`: the image-file capture path this feature reuses.
- `docs/technical/FEATURES.md`: how optional features are packaged and deployed.


## What the QR codes contain

Both QR codes carry only the server URL, the web app's origin and, for a pairing, the host
addresses plus a one-time token. The public Supabase settings and the project name are not in
the QR: the app fetches them from `<frontend origin>/runtime-config.json`, a file the frontend
build emits. Embedding them made the code too dense for a phone camera.

The APK link on the page shows the version it hands out when a sidecar `<apk>.json`
(`version`, `version_code`, `built`, `size_bytes`, `commit`) is published next to the file.
