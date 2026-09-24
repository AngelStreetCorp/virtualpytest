# BUG-0136 — An adb verification silently drops leading and trailing spaces from its search term

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                                       |
|-----------|-----------------------------------------------------------------------------|
| ID        | BUG-0136                                                                    |
| Reported  | 2026-09-17                                                                  |
| Status    | Open                                                                        |
| Severity  | Low (the search still runs; it is wider than the author asked for, and the failure message quotes a term that was never searched) |
| Area      | `backend_host/src/controllers/verification/adb.py`, `backend_host/src/lib/utils/adb_utils.py` |
| Fixed in  | —                                                                           |
| Commit    | —                                                                           |

---

## Symptom

A node verification authored as `search_term: " seconds"` — a leading space, to mean "the word
`seconds`, not any string containing it" — is searched as `seconds`. The distinction the author
wrote is not honoured, and nothing says so.

The failure message quotes the term as written while the artefacts show the term as searched,
which sends you looking for the wrong thing:

```
❌ Error: Navigation failed at step 1 (Entry → home): verification failed
   - Element ' seconds' did not appear after 32.5s
```

```
=== dump 5 | 2026-09-17 09:25:39 | device2 | appear 'seconds' | 35 labelled of 102 nodes ===
```

Found while debugging a `goto video_player` failure on `youtube-android-mobile`. The stripping
was not the cause of that failure, but it hid the fact that the leading space had never done
anything, so the term had always been a plain substring match.

## Root cause

Both search entry points strip unconditionally, and neither warns.

`smart_element_search` lowercases and strips before comparing:

```python
search_lower = search_term.strip().lower()
```

`ADBVerification.getElementListsWithSmartSearch` strips first:

```python
search_term_clean = search_term.strip()
```

and `waitForElementToAppear` strips each component when the term uses the `|` fallback form:

```python
terms = [term.strip() for term in search_term.split('|') if term.strip()]
```

So there is no spelling of a term that matches a leading or trailing space. That is a reasonable
default for terms typed with accidental whitespace — which is presumably why it was written —
but it makes deliberate whitespace unexpressible, and the two behaviours are indistinguishable
to the author.

The matcher searches `text`, `content_desc`, `resource_id` and `class_name` by
case-insensitive substring, so with the space gone `seconds` also matches inside longer strings.

## Suggested fix

Not fixed. Two options, in preference order:

1. **Keep stripping, report it.** Log once when `search_term != search_term.strip()`, and quote
   the stripped term in the failure message so the message and the dump agree. Smallest change,
   removes the misdirection, does not alter any existing tree's behaviour.
2. **Make word-boundary matching expressible** — a distinct syntax rather than whitespace, since
   whitespace in a UI text field is invisible and easy to introduce by accident.

Option 1 alone would have saved the debugging time here; option 2 is only worth it if
word-boundary matching is actually wanted.

## Verification

A verification authored with `" seconds"` should either match only a true word-boundary
occurrence, or state in its log line and failure message that it searched `seconds`.
