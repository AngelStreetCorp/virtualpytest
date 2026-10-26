# BUG-0724 — A new AI endpoint logged its calls with no cost

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0724                                                     |
| Reported  | 2026-10-20                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | ai / backend / db                                            |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

The second Anthropic key was wired in as its own endpoint (`anthropic-individual`). Every call it answered was
written to the AI call log with its tokens, but with `cost = NULL` and `cost_source = "none"`: the usage page showed
the tokens of that key and no price for them, so the AI spend of the Individual key was not counted anywhere.

## Root cause

The cost of a call is taken from `ai_prices`, one row per (endpoint, model). A new endpoint has no row until somebody
types one or the daily price sync writes one, and `shared/src/lib/ai/prices.py:price_for` looked at that endpoint
only: no row meant no price, and `shared/src/lib/ai/call_log.py:build_row` then stored NULL — "no price", never 0.

The rows for the second key existed only because they had been copied by hand from the first key. The next Anthropic
endpoint would have had the same hole, and a copy is exactly the kind of step that gets forgotten.

## Fix

`prices.price_for` falls back to the price of **another endpoint with the same preset** when the endpoint itself has
no row for that model: a second Anthropic key prices like the first one, so a new endpoint never logs cost NULL.

- The endpoint's own row always wins; another preset's price is never used.
- Only an endpoint that bills per token takes a borrowed price: a local endpoint is free and a flat plan is included
  in its subscription, so neither needs one.
- The endpoint list is cached like the price rows, so the fallback costs one query a minute at most, and only when a
  price is missing.
- The stale test `test_origin_defaults_to_unknown_and_eval_test_labels_win` expected the old `origin = "unknown"`
  default; the code has written `background` (with a warning) since that change and the live log shows `background`.
  The test now expects `background`.

## Verification

- `pytest tests/shared/test_ai_prices.py tests/shared/test_ai_call_log.py tests/shared/test_ai_cost_pipeline.py`
- New tests: a same-preset sibling prices an endpoint with no row of its own; another preset's price is never used;
  a local endpoint and a flat plan never borrow a price; a call on a second Anthropic endpoint is priced end to end.
- Live: one call on the Individual key lands in `ai_calls` with `cost_source = price_table` and a cost.
