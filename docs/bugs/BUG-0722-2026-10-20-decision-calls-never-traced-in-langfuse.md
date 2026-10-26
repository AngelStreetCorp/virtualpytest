# BUG-0722 — Decision-model AI calls were counted but never traced in Langfuse

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0722                                                     |
| Reported  | 2026-10-20                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | ai / backend                                                 |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

Every call to a **decision model** (Jev, `typesafe/jev-1.13` on OpenRouter) appeared in the AI call log
(`ai_calls`) but left **no trace in Langfuse**. The Langfuse list showed the chat and vision calls of the
platform and was missing the decision ones entirely.

The 15 usage keys that call a decision model were invisible in Langfuse:

`text.decision`, `text.decision.testprompt_on_failure`, `text.decision.sherlock`, `text.decision.manager`,
`text.decision.wake`, `text.decision.route`, `text.decision.atlas.routing`, `text.decision.retry`,
`text.decision.model`, `text.decision.screen_review`, `text.decision.localize`, `text.decision.verification`,
`text.decision.freeze_triage`, `text.decision.companion`, `text.decision.companion.gate`.

In the 30 days to 2026-10-20 that was **4 782 real calls** in the lab (and more on the other servers):
`text.decision.localize` 2 612, `text.decision.atlas.routing` 992, `text.decision.freeze_triage` 795,
`text.decision.sherlock` 524, `text.decision.verification` 55, plus the two external-tool keys behind the
`eval:` labels (`text.decision.manager` 2 185, `text.decision.wake` 1 534).

## Root cause

The decision API is **not** called through the chat gateway. `shared/src/lib/ai/decisions.py` posts to
`{openrouter}/api/alpha/decisions` itself (`_decide`, the `requests.post` at the `decisions_url(hop)` call) and
then reports the call with `router.record(...)`, which is what fills the `ai_calls` row.

The Langfuse trace, on the other hand, is written by the **gateway**: `shared/src/lib/ai/gateway.py` calls
`tracing.trace_call(name=f"AI {resolution.stats_label}", …)` after `_execute_hops` returns. A decision call
never goes through `gateway.execute`, so no trace was ever sent. `decisions.py` did not import `tracing` at
all — the module had no way to trace.

The chat fallback was not affected: when a decision usage is routed to an ordinary chat profile, `_decide_chat`
calls `gateway.execute`, which traces the call by itself.

## Fix

`shared/src/lib/ai/decisions.py`:

* the module now imports `tracing`;
* `_decide` collects a `tracing.Attempt` per attempted hop — the same object the gateway uses — and finishes
  it with the outcome, the tokens and the provider cost;
* the new `_trace_decision()` sends **one** trace for the call, with one generation per attempted hop, the
  same shape the gateway produces: name `AI <stats_label>`, the trace id = the request id (so a case or a
  call-log row links to its trace), the state and the questions as the input, the answers as the output, and
  the routing metadata (profile, endpoint, preset, model, team, split arm);
* the chat fallback is **not** traced twice — `_decide_chat` still goes through `gateway.execute`, which
  traces it.

The trace label is the **call-log label** (`resolution.stats_label`), so a trace and its `ai_calls` row always
agree — a pinned profile is a scoring call and reads `eval:<usage key>` on both sides.

## Verification

`tests/shared/test_ai_decisions.py` (28 tests, all green) adds three:

* `test_a_decision_call_is_traced_to_langfuse` — the trace is sent, with the right name, label, input,
  output and one successful attempt with the tokens the fake API returned;
* `test_a_failed_decision_call_is_traced_too` — an HTTP error still produces a trace, `ok=False`, with the
  error and the failed attempt;
* `test_a_chat_profile_decision_is_traced_once_by_the_gateway` — the chat path sends no trace of its own
  (the gateway owns that one).

End to end: run a decision call on the lab and the trace appears in Langfuse under the `usage:text.decision.*`
tag, next to its `ai_calls` row.
