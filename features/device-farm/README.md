# `features/device-farm` — a cloud farm device as an ordinary VPT device

Design and decisions: [`docs/tasks/TASK-20-device-farm-integration.md`](../../docs/tasks/TASK-20-device-farm-integration.md).

A phone in Sauce Labs is driven exactly like a phone on a desk: the same remote
panel, the same navigation trees, the same scripts, the same reports. What differs
is where the session lives and that it costs money by the minute — so everything
here exists to make a *leased, metered, pool-allocated* device behave like a
permanent one without pretending the lease isn't there.

## How it works

```
 command (host route / script)
        │
        ▼
 CloudAppiumRemoteController  ──►  FarmSession (lease)  ──►  farm hub (W3C Appium)
   inherits core's Appium              │   opens on first command,
   controller; only `appium_utils`     │   reused, replaced before the farm
   becomes a lazy lease                │   reaps it, released on disconnect
                                       │
 CloudAppiumVerificationController ────┘   same lease: one allocated device
                                       │
                                  FramePump
                                       │  screenshots, only while a session is open
                                       ▼
                       DEVICE{i}_VIDEO  (latest.jpg)
                                       │
                                       ▼
                       run_ffmpeg.sh "imagefile" grabber (core)
                                       │
                          HLS stream + captures/capture_*.jpg
                                       │
                    image / text / colour / video verification, REC preview,
                    report thumbnails — all core, all unchanged
```

The AV controller is core's `hdmi_stream`: it only reads the captures folder, so
anything that fills that folder is a valid picture source. That is the same trick
`features/mobile-app` uses for a paired phone, and it is why this feature needs no
AV controller of its own.

## Configuration

Per slot, in the host `.env` (full example in `backend_host/src/.env.example`):

| Key | Meaning |
|---|---|
| `DEVICE{i}_MODEL` | `cloud_android_mobile` or `cloud_ios_mobile` |
| `DEVICE{i}_APPIUM_PLATFORM_NAME` | `Android` or `iOS` |
| `DEVICE{i}_VIDEO` | `.jpg` path the pump writes and ffmpeg reads |
| `DEVICE{i}_FARM_PROVIDER` | `saucelabs` (implemented) / `browserstack` / `lambdatest` |
| `DEVICE{i}_FARM_USER`, `..._FARM_KEY` | account credentials — masked in every log line |
| `DEVICE{i}_FARM_REGION` | provider datacenter |
| `DEVICE{i}_FARM_DEVICE`, `..._FARM_OS_VERSION` | which device to allocate |
| `DEVICE{i}_FARM_APP` | build under test (`storage:` / `bs://` / `lt://`) |
| `DEVICE{i}_FARM_IDLE_TIMEOUT`, `..._FARM_MAX_DURATION`, `..._FARM_SCREENSHOT_FPS` | lease and pump tuning |
| `FARM_MAX_SESSIONS` | host-wide cap on concurrent sessions (not per device) |

A slot missing credentials is skipped with the exact keys named; the host's other
devices are unaffected.

**Naming a device.** It must exist in this account's pool, or Sauce answers a bare
`Internal Server Error` with nothing in it. `GET /v1/rdc/devices/available` lists the
ids the account can allocate and `GET /v1/rdc/devices/<id>` gives the descriptor,
whose `name` and `osVersion` are what these two keys want:

```
DEVICE4_FARM_DEVICE=Samsung Galaxy S23 FE
DEVICE4_FARM_OS_VERSION=16
```

A trial account is **not** limited to emulators — the one used on 2026-09-17 listed
the full pool and allocated the real devices Sauce marks `_free`
(`Samsung_Galaxy_S23_FE_free`, `iPhone_15_free`), which is what the validation run
used. Some plans do refuse the *listing* with `403 Access API is not available for
free trial accounts`; that never blocks a session, and `available_devices()` says so
rather than raising a bare 403. The emulator path (`Android GoogleAPI Emulator`) was
tried first and is the one that did **not** work on that account.

`DEVICE{i}_FARM_APP` is required, not optional: Sauce refuses a session with
"No browserName or app specified". Use a `storage:<id>` from `upload_app`.

Also apply `db/001_cloud_device_models.sql` by hand (feature migrations are not run
by any deploy script) or the UserInterface editor cannot offer the models, and no
navigation tree can be built for a farm device.

## A farm phone needs no userinterface of its own

`cloud_android_mobile` is in the **android_phone family** with `android_mobile`,
`phone_agent` and `runner_android_mobile` (`MODEL_FAMILIES` in
`shared/src/lib/config/device_capabilities.py`, mirrored in
`frontend/src/config/deviceModelFamilies.ts`). Every matcher — the
`getCompatibleInterfaces` route, the host filters, the campaign and testcase builders,
and Run Tests' `_target_rules` filter — compares families, so a farm phone is offered
the userinterfaces and scripts already written for an Android phone. There is no need
for a `cloud_farm_demo` copy of a tree that exists.

That claim is only true because the cloud side answers the same commands the adb side
does, which took three things:

| Parity | Where |
|---|---|
| `adb` verification registered alongside `appium`, both on the one lease | `backend_host/__init__.py` (`VERIFICATION_TYPES`) — an `android_mobile` tree writes its screen checks as `verification_type: 'adb'` |
| the swipe family (`swipe`, `swipe_up/down/left/right`) | core `appium_remote.py` + `appium_utils.swipe` (W3C pointer actions) |
| `waitForElementToChange` / `waitForElementToStopChanging` | core `verification/appium.py`, sharing `element_watch` with the adb and paired-phone controllers |

`tests/shared/test_device_model_families.py::TestFamiliesAreHonest` fails the build if
a family member's remote stops backing `adb`, and
`tests/backend_host/test_appium_android_parity.py` compares the two action catalogues.

## Getting an app onto a farm

A session needs an uploaded app on both vendors — there is no way to drive one that is
merely preinstalled on the device. [APPS.md](APPS.md) covers the upload commands per
vendor, how to list what is already there, pulling an APK off a device you own (including
the `--user 0` and package-name traps), and why a split-APK app cannot go up at all.

## Adding a provider

One module in `lib/providers/` implementing five methods, plus a line in
`lib/providers/__init__.py`. Nothing else changes: `endpoint_url`, `session_caps`,
`upload_app`, `available_devices`, `session_artifacts` are the only places the
farms actually differ. Sauce Labs is complete; BrowserStack and LambdaTest have
their session half written and unit-tested, and raise `UnsupportedOperation` for
the REST half until there is an account to verify it against.

## Core hooks this feature relies on

| Hook | Where | Why |
|---|---|---|
| `cloud_android_mobile` / `cloud_ios_mobile` models | `shared/src/lib/config/device_capabilities.py` | model → controllers, `appium_cloud` → `appium` + `adb` verification, and the `android_phone` / `ios_phone` entries in `MODEL_FAMILIES` |
| `CloudAppium` branch | `shared/src/lib/models/device.py` | the device reports `remote: 'appium'`, so the existing panel serves it |
| remote + per-model verification registries | `backend_host/src/controllers/controller_registry.py` | core never imports this feature |
| `redact_capabilities()` | `backend_host/src/lib/utils/appium_utils.py` | a farm authenticates *inside* the capabilities; core printed them verbatim |
| Appium panel for capability `appium` and the cloud models | `frontend/src/components/controller/remote/RemotePanel.tsx`, `config/remote/remotePanelLayout.ts`, `types/controller/*_Types.ts`, `hooks/controller/useHdmiStream.ts` | panel, layout, action and verification lists are keyed by model |

Disable with `DISABLED_FEATURES=device-farm`: the hooks above are inert (two unused
model entries and one unused branch), and every other device behaves identically.

## Tests

```bash
PYTHONPATH=. python3 -m pytest tests/backend_host/test_device_farm.py -q
```

Tier A, no network and no account: the provider seam (all three vendors), credential
redaction, slot config, and the lease (lazy open, reuse, pre-emptive expiry, host
cap, shared session) with the Appium client's `webdriver.Remote` replaced by a fake.
The controller tests run against the **real** core base classes where the host
runtime is installed, and skip where it is not.

### The tier-B smoke test (needs an account)

```bash
PYTHONPATH=. python3 features/device-farm/backend_host/smoke_test.py --device device4
```

Opens one real session, prints the farm's session page, then checks resolution,
element dump, screenshot, a frame written where ffmpeg reads it, and a key press —
PASS/FAIL per step, non-zero exit on the first failure, and the session released at
the end (a session left open is billed). The access key is never printed.

**Proven on a real farm (2026-09-17).** Every step above passed against a Sauce Labs
`Samsung Galaxy S23 FE` (Android 16, eu-central-1): session opened in 27s, session
page resolved, 1080x2340 read back, 38 elements dumped, screenshot taken, a frame
written where ffmpeg reads it, `HOME` pressed, session released. The upload path was
exercised too — a 36 MB APK to app storage, returning `storage:<id>`. So the endpoint
URLs and REST shapes in `lib/constants.py` and `lib/providers/saucelabs.py` are
verified, not docs-derived.

Two things that run **only** on the farm and therefore only showed up there:
`sauce:options.appiumVersion` is not optional (Sauce refuses Android 14+ without it),
and a farm phone has no ADB, so core's `page_source` parser is the only dump path —
see [BUG-0146](2026-09-17-appium-page-source-parsed-as-zero-elements.md).

Still open: a full navigation script on a cloud device, and the report-link half of
phase 4. Note also that CI's merge gate runs `pytest tests/backend_server` only, so
this file does not run on a PR.
