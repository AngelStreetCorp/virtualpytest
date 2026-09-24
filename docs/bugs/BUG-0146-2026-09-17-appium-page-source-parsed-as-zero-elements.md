# BUG-0143 — Every UI dump taken through Appium came back empty, and an empty screen is a legitimate answer

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                                       |
|-----------|-----------------------------------------------------------------------------|
| ID        | BUG-0143                                                                    |
| Reported  | 2026-09-17                                                                  |
| Status    | Fixed on `claude/platform-saucelabs-integration-hucpnd` (not yet merged to `main`) |
| Severity  | High (every selector and element verification on an Appium-driven device saw a blank screen; nothing errored) |
| Area      | `backend_host/src/lib/utils/appium_utils.py` `_parse_android_elements`      |
+| Fixed in  | Unreleased                                                          |
| Commit    | `f6dc609472`                                                                |

---

## Symptom

On a cloud farm device, a dump of a screen that was plainly rendered returned nothing:

```
[@lib:appiumUtils:_parse_android_elements] Parsed 0 Android elements
[@lib:appiumUtils:dump_elements] Successfully dumped 0 UI elements
```

"Successfully dumped 0" is the whole problem: an empty tree is a legitimate answer — a screen
really can have nothing selectable on it — so nothing raised, nothing retried and nothing
appeared in a report except a step that failed to find its element.

## Root cause

`_parse_android_elements` matched one XML shape only:

```python
node_pattern = r'<node[^>]*(?:\/>|>.*?<\/node>)'
```

That is ADB's `uiautomator dump` format, where every element is a `<node …>`. Appium's
`page_source` is a different shape: each element is named after its class.

```xml
<android.widget.Button index="1" class="android.widget.Button" text="Run" bounds="[10,20][300,90]" />
```

The regex matches nothing against that, so `matches` was empty and the loop never ran. The
attribute reader underneath it was fine; it was never reached.

Two smaller faults were folded into the same line. The `>.*?</node>` alternative searched a
parent's **whole subtree** for each attribute, so a container with no text of its own picked up
its first child's text. And `class="hierarchy"` on the root would have passed the "has a class
name" filter as if it were an element.

## Why it went unnoticed for so long

A locally attached Android phone is driven over ADB, and the ADB path has its own parser that
was never broken. The Appium parser only becomes load-bearing where ADB is not available —
which is exactly a cloud farm device, where there is no ADB at all. The farm was the first
consumer with no fallback, so it was the first place the emptiness had consequences rather than
a redundant second opinion.

It had no test, and the one it needed is not a farm test: it is two strings and a parser.

## Fix

Match an opening tag of any name, and nothing else:

```python
node_pattern = r'<(?!\?|/|hierarchy[\s>])[A-Za-z_][\w.]*(?:"[^"]*"|[^>"])*?/?>'
matches = re.findall(node_pattern, xml_data)
```

Matching only the opening tag also settles the other two faults at once: attributes can no
longer be read out of a child, and the `hierarchy` root is excluded by name.

## Gate

`tests/backend_host/test_appium_element_parser.py` — five tests over both XML shapes: the Appium
shape parses, the ADB shape still parses, the `hierarchy` root is not an element, a child's
attributes do not bleed into its parent, and bounds survive. Three of the five fail against the
old pattern, which is what makes them a regression test rather than a description.

Confirmed at the consumer on a live Sauce Labs `Samsung Galaxy S23 FE` (Android 16,
eu-central-1): the same screen went from **0 elements to 38**, with `android.widget.Button` and
`android.widget.TextView` nodes carrying the labels the app was showing.
