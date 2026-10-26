# BUG-0687 — The web hosts' Chrome filled a saved login into the app under test

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0687                                                     |
| Reported  | 2026-10-19                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | backend_host Chrome profile |
| Fixed in  | build 90145 |
| Commit    | `8e7e681c5`                                                  |

---

## Symptom

On host-clone-1 the SSO login page of the app under test came up prefilled with another saved account. In TASK-135 Sonnet run 1 the agent
could not clear it and built the whole tree logged in as that account.

## Root cause

The Chrome launch passes `--disable-autofill`, which is not a Chrome switch. Saved-login autofill is governed by profile prefs
(`credentials_enable_service`, `profile.password_manager_enabled`, `autofill.*`), which stayed on.

## Fix

`backend_host/src/lib/utils/playwright_utils.py`: `ChromeManager._fix_preferences` (runs before every Chrome launch) parses Preferences as
JSON and sets the password manager, auto sign-in and autofill prefs off, besides the old `exit_type` reset. The saved logins stay in the profile
but are no longer filled. It takes effect at the next Chrome launch on each host.

## Verification

`tests/backend_host/test_chrome_no_autofill_prefs.py`. Live: after Chrome restarts on a host, the SSO page opens with empty fields.
