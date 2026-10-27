# BUG-0709 — A web navigation tree built in one app language failed every node check in another

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0709                                                     |
| Reported  | 2026-10-19                                                   |
| Status    | Fixed (pending deploy of server + frontend)                  |
| Severity  | High (the whole tree fails, although every screen is there)  |
| Area      | web verification controller, Localize identity, build-tree-web skill |
| Fixed in  | build 90145 |
| Commit    | see the merge `web-lang-fingerprint`                         |

---

## Symptom

The reference web tree (21 nodes, built in English, `validation.py` 39/39) failed on every node as soon as the app showed German:
`"TV Guide, Currently selected"` is `"TV Guide, Aktuell ausgewählt"` there. Same screens, same URLs.

## Root cause

1. **Node verification on web was text only.** Every node carried `waitForElementToAppear` on a translated aria-label
   (`playwright_verifications.py`). The doc said "There is no URL verification on web".
2. **Edges were language-bound too:** `click_element 'TV Guide, Press Enter'`, `'Settings Press Enter'`, tab labels, and back
   actions that opened `https://…/en/settings` (a hard-coded language segment).
3. **Localize identity compared the URL with the language segment:** `same_place()` (web) needed `/en/home == /de/home`, so a
   screen seen in another language read "place not in the tree" and fell to pixels (a web host has no image monitor: Localize
   is off there, `localize` answers "Localize is off for host").
4. The stored pixel fingerprint of a web node is a whole-desktop frame (browser chrome included): dHash cannot tell
   the five TV Guide states or the six settings tabs apart (measured, see FINGERPRINT.md), so it cannot replace text.

The app language is a browser setting (`flutter.language`), not part of the URL: opening `/de/home` while the setting is English
redirects to `/en/home`. So the URL's language segment is noise, and the path after it is the stable identity.

## Fix

- New web verification **`waitForUrlToMatch`** `{url_pattern}`: the page path matches a glob, host, query and the language
  segment ignored (`/epg/initial`, `/watchtv/linearplayer/*`). Pure helpers `url_matches`, `url_path`, `strip_locale`,
  `current_locale`, `resolve_app_url` in `shared/src/lib/utils/localize_identity.py`; controller in
  `backend_host/src/controllers/web/playwright_verifications.py`; editor field in `VerificationControls.tsx`.
- `navigate_to_url` takes a path (`/{lang}/settings`, `/settings`): it opens it in the language the app shows now
  (`resolve_app_url`). A back action never names `en` again.
- Localize `same_place()` ignores the language segment of a web URL.
- `build-tree-web` skill: a node's first verification is `waitForUrlToMatch`; edges use sidebar position selectors
  (`css=flt-semantics > a:nth-of-type(N)`) or path navigation instead of translated labels.
- The existing the reference web tree tree was converted (`update_node` keeps position, screenshot, fingerprint): 25 nodes now verify
  by URL path (the 5 TV Guide states that share `/epg/initial` add their label check as a second step), 14 edges lost their
  English labels.
- `scripts/agent/web_lang_measure.py <ui>` measures per node: URL match, verification, dHash distance and rank.
- Tests: `tests/backend_host/test_localize_identity.py` (language segment, glob, same place across languages, `resolve_app_url`),
  `tests/backend_host/test_web_url_verification.py` (controller, fake page).

## Not fixed

Edges that click a translated label are still language-bound: profile menu → Settings, the Search button, catalogue tiles,
the TV Guide in-page controls. See the operator's internal web UI notes, §7.
