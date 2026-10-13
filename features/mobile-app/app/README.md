# VirtualPyTest mobile app (Capacitor shell + phone agent)

One Android APK that is (a) the VirtualPyTest web frontend running in a WebView and (b) a
native Kotlin "phone agent" that streams the screen and accepts input, turning the phone into
an extra device under test. See `docs/tasks/TASK-17-mobile-app-phone-agent.md` for the full
design (§1 architecture, §1.3 wire protocol).

## Prerequisites

- Node 18+ and npm (`node_modules` here is gitignored — run `npm install` once — this also
  pulls in `typescript` as a devDependency, pinned to match the root frontend's version;
  `npx cap sync` needs it to read `capacitor.config.ts`, and a too-new TypeScript — e.g. one
  installed loose without a version pin — breaks the Capacitor CLI's internal `.ts` loader with
  `Cannot read properties of undefined (reading 'CommonJS')`).
- Android SDK with `platforms;android-35`, `build-tools;35.0.0`, `platform-tools` installed
  (`sdkmanager "platforms;android-35" "build-tools;35.0.0"` after `yes | sdkmanager --licenses`),
  and `ANDROID_HOME` set.
- **A JDK 21 for Gradle.** AGP 8.7.2 / Gradle 8.11.1 (the versions the Capacitor 7 Android
  template pins) require a JDK that supports source/target release 21 — Capacitor's own
  `capacitor-android` module compiles with `sourceCompatibility 21`. A machine-default JDK 23
  (e.g. Homebrew's `openjdk`) is rejected (`error: invalid source release: 21` — javac can target
  *older* releases than the JDK it runs on, never newer). Fix, without touching anything
  system-wide:
  ```bash
  mkdir -p ~/.jdks && cd ~/.jdks
  curl -sL "https://api.adoptium.net/v3/binary/latest/21/ga/mac/<arch>/jdk/hotspot/normal/eclipse" -o jdk21.tar.gz
  tar -xzf jdk21.tar.gz && rm jdk21.tar.gz   # -> ~/.jdks/jdk-21.<version>/Contents/Home
  ```
  Use `mac/x64` on Intel Macs, `mac/aarch64` on Apple Silicon — grabbing the wrong one fails
  with `bad CPU type in executable`, not a helpful Java error.

  `npm run apk` runs `scripts/apk.sh`, which resolves the JDK in this order: `$VPT_ANDROID_JDK`,
  the first `~/.jdks/jdk-21*`, then `$JAVA_HOME`, and passes it to Gradle as
  `-Dorg.gradle.java.home=...`. The `-D` form is deliberate: a *global*
  `~/.gradle/gradle.properties` with its own `org.gradle.java.home` (common with Android Studio)
  picks the daemon JVM before the project's `gradle.properties` is read, so a project-level
  setting cannot win, and an absolute path committed there would break every other machine.
  IDE users set the Gradle JDK in the IDE. A bare `./gradlew` must be given the `-D` flag or a
  JDK 21 as `JAVA_HOME`.

## Build

```bash
npm install                 # once
npm run build:web           # builds frontend/dist (vite build)
npm run sync                # npx cap sync android + injects the runtime-config script tag
npm run apk                 # ./gradlew assembleDebug
```

The debug APK lands at `android/app/build/outputs/apk/debug/app-debug.apk` (~35 MB — it embeds
the entire web bundle). Install with `adb install -r app-debug.apk` or side-load the file.

`npx cap add android` was already run once to generate `android/`; there's no need to run it
again unless `android/` is deleted.

## Release build (signed, non-debuggable — TASK-19 P1 #6)

The publicly-distributed APK should be a signed release build, not the debug one above (debug
builds are `debuggable=true` by AGP default, which is not something to hand out on a public
download link). One-time setup, on whichever machine builds releases:

```bash
cd android
mkdir -p keystore
keytool -genkeypair -v -keystore keystore/release.jks -alias vpt-mobile-app \
  -keyalg RSA -keysize 2048 -validity 10000
cat > keystore.properties <<EOF
storeFile=keystore/release.jks
storePassword=<the password you just chose>
keyAlias=vpt-mobile-app
keyPassword=<the password you just chose>
EOF
```

Both `keystore/*.jks` and `keystore.properties` are git-ignored (`android/.gitignore`) — they
never leave this machine. **Back the keystore up somewhere durable and note the password
outside this repo.** Losing it means every future release needs a brand-new keystore, and every
device with the app already installed has to uninstall before it can take an update signed by a
different key — Android refuses to update an app across a signing-key change.

Then, same as the debug build but the last step differs:

```bash
npm run build:web
npm run sync
npm run apk:release         # ./gradlew assembleRelease, fails fast if keystore.properties is missing
```

Output: `android/app/build/outputs/apk/release/app-release.apk`. Verify it's actually signed with
your key (not the default AGP unsigned/debug fallback) before shipping it:

```bash
$ANDROID_HOME/build-tools/<version>/apksigner verify -v --print-certs app-release.apk
```

`minifyEnabled` is currently `false` on the `release` buildType (build.gradle) — R8/ProGuard
shrinking wasn't turned on here because Capacitor's plugin bridge, Kotlin coroutines,
socket.io-client and zxing all lean on reflection that a wrong `proguard-rules.pro` rule can
silently break at runtime with no build-time error. Turning it on is real hardening (smaller,
harder to reverse-engineer) but needs an actual install-and-exercise pass on a device before
shipping, not just a green `assembleRelease`.

## Automatic republish (codebox)

The public APK is rebuilt and published without anyone running the loop above.

| What | Where (on the downloads host, `ssh proxy`, `~/downloads/`) | When it is rebuilt |
|---|---|---|
| **Intermediary** — one file, replaced in place | `vpt-mobile-app-debug.apk` + `.json` sidecar (the name `VITE_MOBILE_APP_URL` and the app's update check use) | a push to `main` changed `features/mobile-app/**` or `frontend/**` |
| **Release** — one per release, kept forever | `releases/vpt-mobile-app-<tag>.apk` + `.json` | a new `release-YYYY.MM.DD` git tag (the pair tag of [RELEASING](../../../docs/agent/release/RELEASING.md)); built from the tagged commit |

Old releases are not backfilled (tags that exist when the job first ran were only recorded), and
nothing under `releases/` is ever overwritten or pruned automatically. Both are the signed
release build (same key as every installed phone), not a debuggable build.

**Trigger.** git has no post-push hook, and the pre-push hook only sees pushes made from one
checkout. Instead a systemd *user timer* on codebox (`vpt-apk-publish.timer`, every 5 min, lingering
enabled so it survives logout) runs `scripts/auto-publish.sh`, which fetches `origin/main` itself —
so a push from any machine or session is picked up within 5 minutes, and a push is never slowed.
CI was ruled out: the GitHub workflows have no Android SDK; codebox does.

`auto-publish.sh` is a no-op unless something is due (it diffs the last built commit against
`origin/main` over the two paths above, and looks for an unseen `release-*` tag). It takes a
`flock` so two builds never overlap, builds in its own detached worktree `~/vpt-apk-build` (never
touches `~/virtualpytest`), and after a failed build does not retry until `main` moves or you
pass `--force`. After each build attempt (success or failure) the Gradle and Kotlin compile
daemons are stopped (`./gradlew --stop`) to free ~4 GB of idle RAM on the shared 16 GB coding VM.

- State, signing key, lock and **log**: `~/.vpt-apk/` — `auto-publish.log` (read this first),
  `last-commit` (last built `origin/main`), `seen-tags`, `failed`, `keystore.properties` +
  `release.jks` (mode 600, copied into the git-ignored build inputs on each build). The signing keystore is kept in
  exactly two places: `~/.vpt-apk/` on the coding VM (the builder) and `~/.vpt-apk/` on the backend server VM (the
  backup), both mode 600. Never commit it; after replacing it, copy it to both.
- Space: release APKs (~40 MB each) are kept. Only if the proxy has less than 5 GB free, delete the oldest
  `releases/*.apk` (+ `.json`) by hand, always keeping the latest 10 releases. The intermediary file is always replaced.
- **Publish by hand now:** `bash features/mobile-app/app/scripts/auto-publish.sh --force`
  (rebuilds the intermediary from `origin/main`; a release for an unseen tag is built first).
  Re-publish a release tag by hand: remove it from `~/.vpt-apk/seen-tags`.
- Status: `systemctl --user list-timers vpt-apk-publish.timer`, `systemctl --user start vpt-apk-publish.service`.
- Install (once per machine): copy `scripts/systemd/vpt-apk-publish.{service,timer}` to
  `~/.config/systemd/user/`, then `systemctl --user daemon-reload && systemctl --user enable --now vpt-apk-publish.timer`
  and `sudo loginctl enable-linger $USER`. Needs a JDK 21 in `~/.jdks`, the Android SDK in
  `~/android-sdk` (or `ANDROID_HOME`), and ssh access to the downloads host (`VPT_APK_REMOTE_HOST`,
  default `proxy`).
- `versionName` is still bumped by hand in `android/app/build.gradle`. `versionCode` is set at build time to
  `git rev-list --count <built commit>` (env `VPT_APK_VERSION_CODE`; the hand-set value is only the fallback),
  so every intermediary build is newer than the last one: installed apps offer it in Settings and the
  download page's `?v=` cache-bust follows the `.json`.

## How runtime config injection works

The web bundle is generic — one APK serves every deployment (demo, customer overlays, other envs).
This reuses the SAME mechanism the Docker self-service install uses, not an app-specific one:
`getEnv()` (`frontend/src/config/constants.ts`) reads `window.__VPT_CONFIG__` before falling back
to the build-time `import.meta.env`, and `frontend/index.html` already loads `/config.js` as its
first classic script on every build (a container entrypoint writes that file from its own
environment for the Docker case) — so nothing here needs to patch the built `index.html`, `cap
sync` alone is enough.

- `MainActivity.kt` installs a `BridgeWebViewClient` subclass whose `shouldInterceptRequest`
  matches the `/config.js` request `index.html` already makes and returns a
  `window.__VPT_CONFIG__ = {...}` script built live from `PhoneAgentPrefs` (SharedPreferences)
  instead of the static empty default (`frontend/public/config.js`) — everything else falls
  through to Capacitor's normal local-server handling.
- `PhoneAgentPlugin#applyConfig`/`#setServer` write `PhoneAgentPrefs`; the config only takes
  effect on the next WebView load, so the plugin's `reloadApp()` method calls
  `bridge.webView.reload()` after a successful pairing/config so the freshly stored values apply
  immediately.

## Pairing a phone

1. Install the APK and open it. On first run it shows the "Connect to your server" screen
   (native only — `MobileBottomNav`'s Phone tab / `ThisPhonePage`, gated on
   `window.Capacitor.isNativePlatform()`).
2. In the web UI: **Settings → Mobile app & phones**, pick a host, **Pair…** on a free slot.
3. Scan the resulting QR from the app (`PhoneAgentPlugin#scanQr`, zxing-android-embedded). This
   both configures the app (server/Supabase URLs) and binds it to the host slot
   (`PhoneAgentPlugin#applyConfig`, `kind: "pair"`), then starts `PhoneAgentService` and
   connects.
4. Grant the two permissions the app then prompts for (see below). Once both are granted the
   slot goes from "not paired" to a live stream within one HLS segment.

## Permissions and why

| Permission | Why | Granted via |
|---|---|---|
| Accessibility service (`VptAccessibilityService`) | Only unrooted way to dispatch taps/swipes, global actions (BACK/HOME/RECENTS/…), set text in a focused field, and dump the UI tree (§1.3 `tap`/`swipe`/`key`/`text`/`dump_ui`/`launch_app`/`close_app`/`list_apps`). | Settings → Accessibility (`PhoneAgentPlugin#openAccessibilitySettings` opens it directly). |
| Screen capture (`MediaProjection`) | Only unrooted way to read the screen contents for streaming (§1.3 `frame`). Consent is **per session** — Android does not let an app remember a prior grant across process death, so `requestProjection()` must be called again whenever the app/service has been killed. | The system consent dialog (`PhoneAgentPlugin#requestProjection`). |
| `POST_NOTIFICATIONS` | The foreground-service notification ("VirtualPyTest link") required to keep `PhoneAgentService` alive while backgrounded. | Requested by the OS on first foreground-service start (API 33+). |
| Battery optimization exemption | Doze/App Standby throttle background sockets and the capture loop; without this the stream stalls when the screen is off or the app isn't focused. | `PhoneAgentPlugin#openBatterySettings` (optional — surfaced as a "!" checklist item, not blocking). |
| Camera | QR scanning only (zxing). | Runtime prompt on first `scanQr()` call. |

## Known limits

- **No force-stop.** `close_app` is best-effort: it presses HOME (backgrounds the app). Unrooted
  Android has no API to kill another app's process; scripts that need a true cold start should
  use `launch_app` after, or accept "backgrounded" as the close semantics.
- **MediaProjection consent is per session.** If Android kills the app/service (memory pressure,
  force-stop, reboot), the next capture needs a fresh `requestProjection()` — there's no way to
  silently re-arm it. `getStatus().projectionGranted` reflects this.
- **Battery optimizations are opt-in.** The app cannot force-exempt itself; it can only deep-link
  to the settings screen and ask.
- **`status.foreground_app` is currently always `""`.** A real value needs Usage Access
  (`PACKAGE_USAGE_STATS`), which is a separate special-access grant not covered by the plugin
  contract in this round — left for a follow-up rather than adding an undocumented permission
  flow.
- **`status.thermal`** is only available on API 29+ (`PowerManager.getCurrentThermalStatus`);
  reports `"unknown"` below that.
- **POWER key** maps to `GLOBAL_ACTION_LOCK_SCREEN` (API 28+ only) — the closest unrooted
  equivalent to a hardware power button, since there is no way to simulate the physical key.

## What could not be verified on this machine

No Android emulator/device was available in this environment (no AVD, no `adb devices`). The
acceptance bar per the task is a green `./gradlew assembleDebug`, confirmed above (including a
from-clean rebuild after `rm -rf .gradle build app/build`). The following need a real phone:
pairing end-to-end (QR scan → hello/ack → capture → frames arriving at the host), the
AccessibilityService gesture/dump_ui/text behavior, MediaProjection capture and rotation
handling, and the notification/foreground-service lifecycle across backgrounding.
