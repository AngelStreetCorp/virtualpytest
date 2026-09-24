# BUG-0138 — A click on an Appium device searched a cache nothing had filled, and said the button was not there

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                                       |
|-----------|-----------------------------------------------------------------------------|
| ID        | BUG-0138                                                                    |
| Reported  | 2026-09-17                                                                  |
| Status    | Fixed on `claude/platform-saucelabs-integration-hucpnd` (not yet merged to `main`) |
| Severity  | High (every `click_element` in a navigation tree failed on an Appium-driven device) |
| Area      | `backend_host/src/controllers/remote/appium_remote.py` `click_element`       |
+| Fixed in  | build 9151                                                          |
| Commit    | `5fb30719b7`                                                                |

---

## Symptom

Clicking a button that was plainly on screen:

```
Remote[APPIUM]: Direct click on element: 'Settings'
Remote[APPIUM]: All terms failed. Last error: Element not found: 'Settings'
```

In the same session, seconds apart, the verification controller found it without trouble:

```
[@controller:AppiumVerification:waitForElementToAppear] SUCCESS: Found element using term 'Settings'
  1. Element element_35: exact match in text: 'Settings'
```

Two controllers, one screen, opposite answers — which is the tell.

## Root cause

`click_element` resolves a label through three helpers:

```python
def find_element_by_text(self, text):
    for element in self.last_ui_elements:      # ← only dump_elements ever fills this
        if text.lower() in element.text.lower():
            return element
    return None
```

`self.last_ui_elements` starts as `[]` and is assigned in exactly one place: `dump_elements`.
Nothing in `click_element` calls it. So on a freshly built controller the three helpers all
iterate an empty list and the click reports "not found".

The verification controller disagreed because it takes its own dump before searching.

## Why it survived

The adb remote does not have this bug. Its `click_element` takes a fresh dump first and says so
in a comment — *"Plain text detected, using dump-first approach"*. A locally attached Android
phone is driven over adb, so the path people actually used was the correct one, and the Appium
remote was left as the odd one out.

It only becomes load-bearing where there is no adb — a cloud farm device. There, a navigation
tree's `click_element` action never dumps first, so **every click in a tree failed**. This is
the second defect of exactly that shape found the same day; the first was
[BUG-0143](BUG-0143-2026-09-17-appium-page-source-parsed-as-zero-elements.md), and it is worth
noticing the pattern: the Appium path quietly carries assumptions the adb path satisfies for it.

## Fix

Dump once at the top of `click_element`, before the term loop, exactly as the adb remote does.
One dump per call rather than per term, because pipe-separated terms are fallbacks against a
single screen. A dump that fails is a warning, not an abort — the previous list is still a
better bet than refusing to try.

## Gate

`tests/backend_host/test_appium_click_dumps_first.py` — five tests: a click on a fresh
controller finds what is on screen, the click dumps before searching, a **stale** cache does not
decide the click, one dump serves every fallback term, and a failed dump is not fatal. Four of
the five fail against the old code.

Confirmed at the consumer on a live Sauce Labs `Samsung Galaxy S23 FE`: the same
`click_element('Settings')` went from `False` / "Element not found" to
`Successfully clicked element: 'Settings'`.

## One thing this uncovered that is not ours

With the click working, tapping the VirtualPyTest mobile app's bottom-nav entries on that device
lands on Android's own navigation bar — the app draws its nav row underneath the system one, so
"Device" opens Recents and "Settings" goes Home. That is the mobile app's layout, not the farm's
doing, and it is why the TASK-20 demo tree verifies on a body element (`Hosts`) rather than a
bottom-nav label.
