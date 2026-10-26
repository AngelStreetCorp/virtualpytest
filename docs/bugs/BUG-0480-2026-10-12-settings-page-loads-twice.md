# BUG-0480 — Settings page loads twice on every open

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0480                                                     |
| Reported  | 2026-10-12                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Low                                                          |
| Area      | frontend · configuration · Settings                          |
| Fixed in  | build 90145 |
| Commit    | a294f0c34                                                    |

---

## Symptom

Opening `/configuration/settings` always showed the full-page spinner, then the page, then the
spinner again, then the page — it visibly loaded two times in a row.

## Root cause

`Settings` replaces the whole page with a spinner while `useSettings().loading` is true. On mount
it runs `loadConfig()` (spinner #1), then fetches the registered hosts and selects the first one,
which triggers `loadHostConfig()`. `loadHostConfig` also set the same page-level `loading` flag,
so the page went back to the spinner (#2) while the host's config loaded.

## Fix

`loadHostConfig` no longer touches the page-level `loading` flag. Host readiness is already tracked
by the page's `hostConfigReady` state, which keeps Save disabled on the Host tab until the host's
config has arrived.
