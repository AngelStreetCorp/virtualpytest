# Cloud Device Farms

**Lease a phone from Sauce Labs or BrowserStack and drive it like one on your desk.**

A farm device is an ordinary VirtualPyTest device: the same remote panel, the same
navigation trees, the same scripts, the same reports. What differs is that the session
lives in a vendor's cloud and costs money by the minute — so the lease is explicit
rather than hidden.

---

## Providers

| Provider | Status | What works |
|---|---|---|
| **Sauce Labs** | Live | Everything — sessions, app upload, device listing, session artifacts. Proven against a real device on 2026-09-17. |
| **BrowserStack** | Live | Sessions and app-driven runs. Upload the build yourself (below) and point `DEVICE{i}_FARM_APP` at the returned reference. |
| **LambdaTest** | Planned | The session half is written and unit-tested behind the same seam; nothing has been run against a real account. |

Adding a fourth farm is one module in `features/device-farm/lib/providers/` implementing
five methods, plus one line in that folder's `__init__.py`. Nothing outside it changes.

---

## Configuration

One farm device is one slot in the host `.env`. The keys that matter:

| Key | Meaning |
|---|---|
| `DEVICE{i}_MODEL` | `cloud_android_mobile` or `cloud_ios_mobile` |
| `DEVICE{i}_FARM_PROVIDER` | `saucelabs` / `browserstack` / `lambdatest` |
| `DEVICE{i}_FARM_USER`, `..._FARM_KEY` | account credentials — masked in every log line |
| `DEVICE{i}_FARM_REGION` | provider datacenter |
| `DEVICE{i}_FARM_DEVICE`, `..._FARM_OS_VERSION` | which device to allocate |
| `DEVICE{i}_FARM_APP` | the build under test (`storage:` / `bs://` / `lt://`) |
| `FARM_MAX_SESSIONS` | host-wide cap on concurrent sessions, not per device |

The full list with defaults is in `backend_host/src/.env.example`. A slot missing
credentials is skipped with the exact keys named; the host's other devices are unaffected.

**The device name must exist in your account's pool.** Name one that does not and the
vendor answers with a bare internal error that says nothing useful.

---

## Getting an app onto a farm

`DEVICE{i}_FARM_APP` is **required, not optional** — a farm refuses a session with neither
a browser nor an app, and there is no way to drive an app that is merely preinstalled on
the device. Upload the build once, then reference it:

```bash
# BrowserStack — returns bs://<hash>
curl -u "<user>:<key>" \
  -X POST "https://api-cloud.browserstack.com/app-automate/upload" \
  -F "file=@/path/to/app.apk"
```

Then set `DEVICE{i}_FARM_APP` to the returned reference (`storage:<id>` on Sauce,
`bs://<hash>` on BrowserStack). Giving the upload a custom id lets the same `.env` value
keep meaning "the current build" without an edit per release.

The upload commands per vendor, how to list what is already uploaded, how to pull an APK
off a device you own, and why a split-APK app cannot be uploaded at all are covered in
`features/device-farm/APPS.md`.

---

## Before the first run

Apply `features/device-farm/db/001_cloud_device_models.sql` by hand — feature migrations
are not run by any deploy script, and without it the UserInterface editor cannot offer the
cloud models, so no navigation tree can be built for a farm device.

To turn the whole feature off, set `DISABLED_FEATURES=device-farm`. Every other device
behaves identically.

---

## Related Documentation

- **[Integrations](README.md)** — everything VirtualPyTest connects to
- **[Unified Controller](../features/unified-controller.md)** — how one panel drives every device type
- **[Mobile App](../features/mobile-app.md)** — the other way to test on a phone
