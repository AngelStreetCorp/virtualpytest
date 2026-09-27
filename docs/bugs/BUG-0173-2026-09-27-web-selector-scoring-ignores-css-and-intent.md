# BUG-0173 — analyze_screen_for_action could not pick a web field: no CSS selectors, any unique id won, and it answered with a command web lacks

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0173                                                     |
| Reported  | 2026-09-27                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Low                                                          |
| Area      | shared selector scoring / backend_server MCP / Playwright    |
| Fixed in  | Unreleased (the cut sets the build — never copy VERSION.txt)  |
| Commit    | 9384a9c4c                                                    |

---

## Symptom

This came up when re-running the BUG-0172 prompt (session `65b133df`). The model passed
YouTube's search box to `analyze_screen_for_action(intent="search field", platform="web")`:

```
{"selector":"input.ytSearchboxComponentInput.yt-searchbox-input","name":"search_query","placeholder":"Search", ...}
```

It got back `No unique selector found for 'search field'`. Before that, it had called `input_text`
twice without a `selector` and once with `selector` outside `params`, each time getting a bare
`selector parameter is required`.

## Root cause

- `find_best_selector` (`shared/src/lib/utils/selector_scoring.py`) scores web elements only on
  `id`, `xpath` and `textContent`. Web dumps carry no xpath, and a form field often has neither an
  id nor text. The search box's only usable handle, its CSS selector, was never considered.
- A web `id` scored 1000 whatever the intent, so with a whole page dump any unique id won.
- For a web id, `analyze_screen_for_action` returned `click_element_by_id`, which Playwright does
  not have. Its command and params were in side keys; the model only saw `selector:type=value`.
- Playwright's `click_element` treats a bare `tag.class` selector (the form `dump_elements`
  generates) as visible text, so a dump selector would not click.

## Fix

- The scorer has a web `css` type (priority between xpath and text) built from the dump's
  `selector`. Web `id` and `css` are judged against the intent by the element's describing words:
  placeholder, aria-label, name, title, text, and the id itself. With no word in common they score
  -1 and never win.
- `analyze_screen_for_action` on web always returns `click_element` with `element_id` set to the
  CSS selector (`[id="…"]` for ids). Its text includes the ready-to-run action, plus an
  `input_text` action for fields. `analyze_screen_for_verification` keeps to non-CSS types, since
  `waitForElementToAppear` matches text.
- The web dump hands out `css=`-prefixed selectors, and `click_element` recognises the `css=` /
  `xpath=` engine prefixes. So a dump selector works unchanged in both `click_element` and
  `input_text`.
- The `input_text` error explains where the selector goes and where it comes from.

## Verification

- `tests/backend_server/test_web_selector_scoring.py`: 4 of its 5 tests fail before the fix, and
  all pass after it.
- Re-run the prompt on prod: no `No unique selector found` and no `selector parameter is required`.
