# BUG-0828 — A dismissed notification comes back and its toast loops

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                |
|-----------|--------------------------------------|
| ID        | BUG-0828                             |
| Reported  | 2026-10-22                           |
| Status    | Fixed (pending deploy)               |
| Severity  | Medium                               |
| Area      | frontend (notificationStore, ToastContext) |
| Fixed in  | build 90145 |
| Commit    | TBD                                  |

---

## Symptom

Clicking the × on a bell entry removes it, then the same entry (e.g. "78 of 240 runs failed") reappears. The same
problem toasts repeatedly, and the toast sat over the top bar.

## Root cause

`notificationStore.dismiss()` only dropped the row; the dashboard producers call `notify()` with the same episode id on
every poll, which re-added it and re-toasted it. Nothing remembered the dismissal or how often a toast had shown.

## Fix

`notificationStore` keeps a persistent dismissed-id set and a per-id toast counter (localStorage). `notify()` is silent
for a dismissed id and toasts an id at most twice. The toast button is **Skip** (dismisses for good); the toaster is
offset below the top bar.
