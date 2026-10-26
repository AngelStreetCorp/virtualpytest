# BUG-0235 — AI Generate on an Android phone proposed the status bar and feed tiles as screens

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0235                                                     |
| Reported  | 2026-10-02                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium — AI interface building on Android produced no usable screen |
| Area      | `backend_host/src/lib/utils/adb_utils.py` (`_parse_ui_elements`), `backend_host/src/services/ai_exploration/screen_analyzer.py` (`_extract_interactive_elements_mobile`) |
| Fixed in  | build 90145 |
| Commit    | this commit                                                  |

---

## Symptom

On a Samsung phone with Google TV open on its Home tab, AI Generate proposed 20 "screens":
`Recents`, `Back`, `Edge panels`, the clock, `Wi-Fi signal full`, `Four bars of phone signal`,
the status-bar notifications, and the feed's tiles (`Dune: Part Two`, `2024 · 2 hr 46 min`,
`FROM`). The app's real tabs (Shop, Library, Watchlist) came last or not at all.

## Root cause

The exploration did read the UI dump, not the screenshot. But the host dumps with
`uiautomator dump --windows`, which returns every window on screen: Android's navigation bar and
status bar (`com.android.systemui`) and the launcher's edge panel sit next to the app. The parser
dropped each node's window and package, so the analyzer could not tell them apart. It also kept
every label, tappable or not, inside the feed's lists as well as in the tab bar.

## Fix

- The parser records, for each element, its package, whether it sits in the **focused** window,
  inside a list (RecyclerView, ViewPager, ListView, GridView) and under a clickable ancestor.
- The analyzer keeps only tappable elements of the focused window. It proposes the app's fixed
  navigation (tab bar, toolbar) first, and falls back to list rows only when there are fewer than
  three of those (a Settings-style screen whose navigation is the list itself).
- Labels with no letter or digit (`·`, `/`) are dropped.
- A tap by label prefers the app's window when two elements match equally: the app's "Home"
  tab and Android's navigation-bar Home button tied, and the navigation bar came first in the
  dump, so `click_element("Home")` would have left the app.

## Verification

- The phone's own dump on Google TV's Home tab now gives `Search`, `4 TVs nearby`, `Shop`,
  `Library`, `Watchlist` (Home is the start node). Android Settings gives its first-level rows.
- `tests/backend_host/test_exploration_mobile_dump.py` (trimmed copy of that dump) passes.
- Deployed 2026-10-03: AI Generate on the phone (Google TV, which had reopened on its Shop tab)
  proposed `Search, 4 TVs nearby, Library, Watchlist` in 26 s; the selected tab is not tappable
  and so not proposed.
