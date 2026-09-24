# Getting an app onto a farm

Every command here was run against live accounts on 2026-09-17. Nothing below is
docs-derived.

---

## 1. The upload is not optional

A farm session needs an app artifact. There is no "just drive the app already on the
phone" mode on either vendor — both refuse the session:

| Vendor | What it says when you omit the app |
|---|---|
| Sauce Labs | `No browserName or app specified in session request` |
| BrowserStack | `[BROWSERSTACK_INVALID_APP_CAP] The app_url/custom_id/shareable_id specified in the 'app' capability is invalid` |

BrowserStack says that **even when you pass `appium:appPackage` + `appium:appActivity`
for an app that is preinstalled on the device**. So: upload first, then put the returned
reference in `DEVICE{i}_FARM_APP`.

## 2. Upload

Credentials are the same pair already in the host `.env` (`DEVICE{i}_FARM_USER` /
`DEVICE{i}_FARM_KEY`). Export them rather than pasting them into a shell you keep.

```bash
export FARM_USER=... FARM_KEY=...
APK=/path/to/app.apk
```

### Sauce Labs

```bash
curl -s -u "$FARM_USER:$FARM_KEY" \
  -X POST "https://api.eu-central-1.saucelabs.com/v1/storage/upload" \
  -F "payload=@$APK" -F "name=$(basename "$APK")" \
| python3 -c "import json,sys; print('storage:'+json.load(sys.stdin)['item']['id'])"
# -> storage:<uuid>
```

That is `DEVICE{i}_FARM_APP` verbatim. Match the region to `DEVICE{i}_FARM_REGION`
(`api.us-west-1...` / `api.eu-central-1...`) — an app uploaded to one region is not
visible in the other.

The feature does this in code too, and it is exercised:

```python
provider.upload_app(cfg, '/path/to/app.apk')   # -> 'storage:<id>'
```

### BrowserStack

```bash
curl -s -u "$FARM_USER:$FARM_KEY" \
  -X POST "https://api-cloud.browserstack.com/app-automate/upload" \
  -F "file=@$APK" -F "custom_id=my-app" \
| python3 -c "import json,sys; print(json.load(sys.stdin)['app_url'])"
# -> bs://<hash>
```

`custom_id` is worth setting: re-uploading with the same one replaces the build, and
`DEVICE{i}_FARM_APP=my-app` then always means "the current one" without editing the
`.env` each time. `provider.upload_app()` for BrowserStack is not implemented yet
([TASK-21](../../docs/tasks/TASK-21-browserstack-provider.md)) — use the curl above.

## 3. See what is already up there

```bash
# Sauce
curl -s -u "$FARM_USER:$FARM_KEY" \
  "https://api.eu-central-1.saucelabs.com/v1/storage/files?per_page=20" \
| python3 -c "import json,sys; [print(i['id'], i['name']) for i in json.load(sys.stdin)['items']]"

# BrowserStack
curl -s -u "$FARM_USER:$FARM_KEY" https://api-cloud.browserstack.com/app-automate/recent_apps \
| python3 -c "import json,sys; [print(a['app_url'], a.get('custom_id'), a['app_name']) for a in json.load(sys.stdin)]"
```

An empty BrowserStack account answers `{"message":"No results found"}`, not `[]`.

## 4. Getting the APK in the first place

### Your own app

Build it. For the VirtualPyTest mobile app that is `features/mobile-app/app/scripts/apk.sh`;
for another project, whatever that project's build produces. Prefer a flavour that does not
point at a LAN address — a farm device cannot reach `192.168.x.x`, so a "demo"/standalone
build is usually the right one and a "server" build will sit there looking broken.

### An app installed on a device you own

```bash
adb connect 192.168.1.31:5555
adb -s 192.168.1.31:5555 shell pm list packages --user 0 | grep -i <name>
adb -s 192.168.1.31:5555 shell pm path --user 0 <package>
adb -s 192.168.1.31:5555 pull <path-from-above> ./app.apk
```

Two things that will waste your afternoon otherwise:

- **`--user 0` is required** on a phone with a Secure Folder or work profile. Without it
  `pm list packages` fails with `SecurityException: Shell does not have permission to
  access user 150` and you conclude the app is not installed.
- **Search by package, not by brand.** An app's package name often has nothing to do with
  the name on the icon: operator TV apps are routinely published under the parent group's
  or a white-label vendor's prefix, so grepping for the brand returns nothing and you
  conclude it is not installed. Two commands beat guessing —
  `pm list packages -3 --user 0` lists only user-installed apps and is short enough to
  read, and `aapt2 dump badging <apk> | grep application-label` tells you what a given
  package actually is.

## 5. The trap: split APKs

Most Play Store apps install as an **app bundle** — a `base.apk` plus per-ABI, per-density
and per-language splits. Check before you pull:

```bash
adb -s <device> shell pm path --user 0 <package> | wc -l   # 1 = single APK, >1 = split
```

Measured on one phone:

| App | Package | Files |
|---|---|---|
| labox | `io.labox.mobile` | **1** ✅ |
| An operator TV app (white-labelled) | — | **1** ✅ |
| Another operator TV app | — | 3 ❌ |
| A third operator TV app | — | 3 ❌ |
| YouTube | `com.google.android.youtube` | 4 ❌ |
| Netflix | `com.netflix.mediaclient` | 18 ❌ |

A farm takes **one** artifact for `appium:app`. `base.apk` on its own is missing the
native libraries (`split_config.arm64_v8a.apk`) and the resources. This was measured, not
assumed: uploading the `base.apk` of a 4-way-split TV app and opening a session against it
fails at launch —

```
Could not start a session. Something went wrong with app launch.
```

`aapt2 dump badging` on that base shows no `native-code` line at all, because every
library lives in the ABI split. Merging splits back together means re-signing, which breaks signature checks
and DRM — precisely what a TV app does.

A **universal APK of the same app works**, and the contrast is the proof: the same app,
same version, as a publisher-built universal `.apk` (`native-code: 'arm64-v8a'
'armeabi-v7a' 'x86_64'`) uploads, installs and opens a session where its split `base.apk`
died at launch. So the fix is the artifact, not the farm.

So for a split app, get a **universal `.apk` or an `.aab` from whoever publishes it**
(both vendors accept `.aab`). For an app whose publisher you already work with that is a
reasonable ask; for YouTube or Netflix it is not obtainable, and APK mirror sites are not
an answer — the binary is unverifiable and redistribution is not yours to do.

Two more things worth knowing before you plan a test around them: YouTube tends to hit a
bot wall on cloud runners, and Netflix will not play DRM content on a farm device.

## 6. First launch often lands on a permission dialog

A farm device is a clean device: an app that asks for runtime permissions shows Android's
dialog instead of its own first screen, and a tree that expects the app will not find it.

```
current_package  = com.google.android.permissioncontroller
current_activity = ...permission.ui.GrantPermissionsActivity
```

Appium's `appium:autoGrantPermissions` handles it — with it set, the same session lands on
the app's own activity instead. Both vendors accept it. Worth setting for any slot whose
app is not trivially permissionless.

## 7. Point a slot at it

```
DEVICE4_FARM_APP=storage:<uuid-from-the-upload>                  # Sauce
DEVICE4_FARM_APP=bs://<hash-from-the-upload>                     # BrowserStack
DEVICE4_FARM_APP=labox-mobile-demo                              # BrowserStack custom_id
```

Then restart **both** services — `vpt-host` picks up the slot, `vpt-stream` starts its
grabber and only reads its device list at startup:

```bash
sudo systemctl restart vpt-host && sudo systemctl restart vpt-stream
```

A quick check that the artifact is usable, before building a tree around it:

```bash
PYTHONPATH=. python3 features/device-farm/backend_host/smoke_test.py --device device4
```
