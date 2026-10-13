# BUG-0267 — Mobile app server picker shows only one server

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0267                                                     |
| Reported  | 2026-10-03                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | mobile-app (Android shell)                                   |
| Fixed in  | Unreleased                                                   |
| Commit    | TBD                                                          |

---

## Symptom

In the APK the Server dropdown listed only the primary server, while the web app listed the
slave servers too. Installing a newer APK did not help.

## Root cause

The shell builds `/config.js` from settings stored on the phone, and the extra servers
(`slave_server_url`) were only ever stored when a config QR or server URL was applied
(`PayloadApplier.applyConfig`). A phone set up before `runtime-config.json` published
`slave_server_url` (6f4582e87b) kept an empty list for good — updating the app keeps its
settings.

## Fix

`PayloadApplier.refreshRuntimeConfig()` re-reads `<server origin>/runtime-config.json` on every
launch (`MainActivity.onCreate`, background thread); when a value changed it stores it and
reloads the WebView once. Fields the file omits keep their stored value; an unreachable file
changes nothing. APK 1.0.48.

## Verification

Android emulator, debug build: configured with a payload carrying no server list (stored prefs:
`server_url` only), relaunched normally — prefs then held `slave_server_url` with the three
published servers and the WebView reloaded onto the real sign-in page.
