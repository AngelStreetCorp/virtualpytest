# BUG-0175 — Web input_text failed unless the field came as params.selector, and ignored press_enter

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0175                                                     |
| Reported  | 2026-09-27                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Low                                                          |
| Area      | backend_host Playwright controller                           |
| Fixed in  | Unreleased (the cut sets the build — never copy VERSION.txt)  |
| Commit    | 7b3a2fb2b                                                    |

---

## Symptom

Every AI-agent run of *Open YouTube in the browser, search for "Raspberry Pi"…* on `host-clone-1`
showed at least one red **Tool Execution Failed** card on `input_text`, which kept it out of the
promo video. The model named the field in three different ways, and only one was accepted:

- `{"text": "Raspberry Pi", "xpath": "//input[@name='search_query']"}` (session `e03f61d1`)
- `{"text": "Raspberry Pi"}` right after clicking the search box (sessions `3a3c98ee`, `65b133df`)
- `{"selector": "css=input[name='search_query']", "text": …}`: the only form that worked

It also passed `press_enter: true`, which was ignored. The query was typed but never submitted, so
the model had to navigate to the results URL by hand.

## Root cause

`PlaywrightWebController.execute_command('input_text')` read the field only from
`selector`/`element_id` and failed without one. `input_text` only called `page.fill`, and never
pressed Enter.

## Fix

- The field may come as `selector`, `element_id` or `xpath`. `page.fill` already reads `//…` as
  XPath.
- With no field, text goes into the focused element when it is an input, a textarea or
  contenteditable (`*:focus`), for example the search box a click just focused. If nothing
  editable has focus, it still fails with a message that says what to pass.
- `press_enter: true` presses Enter after typing.
- The `list_actions` entry and the `execute_device_action` description document both.

## Verification

- A local Playwright check confirms that `fill("//input[...]")` and `locator('*:focus').fill()`
  work, that Enter submits the form, and that focus on a button is not treated as editable.
- Re-run the prompt on prod through the AI Agent page: no failed tool card.
