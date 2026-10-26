# BUG-0216 — Test Prompt: opening a saved prompt put the device's first interface in place of the prompt's

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0216                                                     |
| Reported  | 2026-10-01                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium — the Interface picker is locked while a prompt is open, so the user cannot correct it; Take Control loads the wrong tree and Target list |
| Area      | `features/ai-test/frontend/hooks/useTestPromptPage.ts` |
| Fixed in  | build 90145 |
| Commit    | this commit                                                  |

---

## Symptom

On `/test-prompt` with no device selected, clicking the saved prompt *TASK-36 check: sauce-demo
products* (interface `sauce-demo`) selected host-clone-1 as expected. The Interface picker
showed `web_tv` instead, and stayed on it for every sample over 8 s. `sauce-demo` is in that
device's compatible list; picking the device by hand offers it. Found in the TASK-36 browser
check, after the same prompt passed both ways over the API.

## Root cause

Loading a prompt sets `userinterfaceName` to the prompt's interface and queues the device
selection. The compatible-interfaces effect reruns on that change while no device is selected
yet, and its no-device branch cleared `userinterfaceName`. When the device then landed, the
effect found no current interface and fell back to the device's first compatible one
(`web_tv`). The effect's async result was also never discarded when a newer run replaced it.

## Fix

The no-device branch keeps `userinterfaceName` and only clears the compatible list. A device
that cannot use the interface still falls back to its first compatible one. A superseded
effect run is cancelled after `getAllUserInterfaces()` returns.

## Verification

- `tsc --noEmit` passes.
- After a frontend deploy, in a browser (Playwright): click the prompt, and the Interface shows
  `sauce-demo`.
