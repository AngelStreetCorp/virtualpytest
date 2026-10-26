# Cloud Device Farms

**Rent a phone from Sauce Labs or BrowserStack and control it from your desk.**

A farm phone works like any other VirtualPyTest device. You use the same remote panel, the same navigation trees, the same scripts and the same reports. The difference is cost. The phone runs in the vendor's cloud and you pay by the minute, so you always choose to start a session.

---

## Providers

| Provider | Status | What works |
|---|---|---|
| **Sauce Labs** | Live | Everything: sessions, app upload, device list, session files. Tested on a real device on 2026-09-17. |
| **BrowserStack** | Live | Sessions and app runs. You upload the build yourself (see below). |
| **LambdaTest** | Planned | Not yet tested on a real account. |

<div data-technical>

Adding a fourth provider means one module in `features/device-farm/lib/providers/` that implements five methods, plus one line in that folder's `__init__.py`. Nothing outside that folder changes.

For BrowserStack and Sauce, point `DEVICE{i}_FARM_APP` at the reference returned by the upload (see below).

</div>

---

## Configuration

<div data-technical>

Each farm phone is one slot in the host `.env`. The keys that matter:

| Key | Meaning |
|---|---|
| `DEVICE{i}_MODEL` | `cloud_android_mobile` or `cloud_ios_mobile` |
| `DEVICE{i}_FARM_PROVIDER` | `saucelabs` / `browserstack` / `lambdatest` |
| `DEVICE{i}_FARM_USER`, `..._FARM_KEY` | account credentials, masked in every log line |
| `DEVICE{i}_FARM_REGION` | provider datacenter |
| `DEVICE{i}_FARM_DEVICE`, `..._FARM_OS_VERSION` | which device to allocate |
| `DEVICE{i}_FARM_APP` | the build under test (`storage:` / `bs://` / `lt://`) |
| `FARM_MAX_SESSIONS` | host-wide cap on concurrent sessions, not per device |

The full list with defaults is in `backend_host/src/.env.example`. A slot with missing credentials is skipped, and the log names the missing keys. The host's other devices keep working.

</div>

Each farm phone has its own settings on the host: your account, the phone you want, and the app to test.

**The device name must exist in your account's pool.** If it does not, the vendor returns a generic internal error that does not say what went wrong.

---

## Getting an app onto a farm

A farm needs an app or a browser to run. It cannot just use an app that is already on the phone. So you upload your build once, and then point VirtualPyTest at it.

<div data-technical>

The BrowserStack upload command returns `bs://<hash>`:

```bash
# BrowserStack — returns bs://<hash>
curl -u "<user>:<key>" \
  -X POST "https://api-cloud.browserstack.com/app-automate/upload" \
  -F "file=@/path/to/app.apk"
```

Then set `DEVICE{i}_FARM_APP` to the returned reference (`storage:<id>` on Sauce, `bs://<hash>` on BrowserStack). If you give the upload a custom ID, the same `.env` value keeps pointing at the current build, so you do not edit it for every release.

`DEVICE{i}_FARM_APP` is required. A farm refuses a session that has neither a browser nor an app.

</div>

The upload commands for each vendor, how to list what is already uploaded, how to pull an APK off a phone you own, and why a split-APK app cannot be uploaded are covered in `features/device-farm/APPS.md`.

---

## Before the first run

An admin must run one database setup step by hand. The deploy scripts do not run it for you. Without it, the editor cannot offer cloud phones, so no navigation tree can be built for them.

<div data-technical>

Apply `features/device-farm/db/001_cloud_device_models.sql` by hand. Feature migrations are not run by any deploy script.

To turn the whole feature off, set `DISABLED_FEATURES=device-farm`. Every other device behaves the same.

</div>

An admin can switch the whole farm feature off for a deployment. Your other devices are not affected.

---

## Related Documentation

- **[Integrations](README.md)**: everything VirtualPyTest connects to
- **[Unified Controller](../features/unified-controller.md)**: how one panel drives every device type
- **[Mobile App](../features/mobile-app.md)**: the other way to test on a phone
