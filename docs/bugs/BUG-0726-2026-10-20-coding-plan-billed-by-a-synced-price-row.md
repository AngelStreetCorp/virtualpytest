# BUG-0726 — The coding plan was billed by a synced price row, and its tokenless calls showed "no price"

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0726                                                     |
| Reported  | 2026-10-20                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | ai / backend / db                                            |
| Fixed in  | build 90145 |
| Commit    | TBD                                                          |

---

## Symptom

Two wrong numbers on the AI usage page and in Grafana, both on the MiniMax endpoints.

1. **The coding plan was billed.** The `minimax` endpoint is the MiniMax **coding plan**: a flat subscription
   (`ProviderPreset.flat_plan`), so every call on it is included in the plan and costs 0. But `minimax-m2.7-highspeed`
   was charged 0.25 / 1.00 USD per million tokens, while its siblings on the same endpoint (`minimax-m3`,
   `MiniMax-M3.1-Flash-Preview`) were free. In the 30 days to 2026-10-20 that was 1 110 calls billed $2.97 for a
   subscription that already covers them.
2. **The VLM calls showed "no price".** The `minimax-vlm` endpoint (the coding-plan VLM) reports no token usage — its
   API answers `content` and `base_resp` only — so its calls were logged with 0 tokens, and because the pricing step
   was skipped for a call without tokens, they were logged with `cost = NULL`, `cost_source = "none"`. 14 866 such
   calls in 30 days, a third of all AI calls (`vision.alert_triage`): the page read "no price" where the plan says
   "included in plan".

## Root cause

`shared/src/lib/ai/prices.py:cost_for` looked the price row up **first** and only fell back to the flat-plan rule when
no row existed. A row synced from Langfuse (`note = "source:langfuse"`, written on 2026-10-13) therefore billed a
plan endpoint, although the module's own contract says the opposite: *"A typed price (any note that is not a `source:`
tag) always wins over all of these"* — a synced price was not supposed to beat the plan.

`shared/src/lib/ai/call_log.py:build_row` only priced a call when the provider had reported tokens
(`if outcome == "served" and (tokens_in or tokens_out)`). The VLM endpoint reports none, so those calls were never
priced at all and kept `cost = NULL`.

## Fix

- `prices.cost_for` ignores a **synced** price row on a flat-plan endpoint (a typed one still wins), and treats "the
  provider reported no tokens" as an unknown cost on a metered endpoint — never as 0.
- `call_log.build_row` prices **every** served call: a call without tokens is 0 when the endpoint is free (the coding
  plan, a local machine) and keeps "no price" on a metered endpoint, so a missing token count can never invent a
  $0.00 spend.
- The alert triage does not go through the gateway: it calls the VLM itself and reports the call
  (`call_log.reported_row`, the `/server/ai/stats` path). That path priced a call only when it had tokens, so the
  tokenless VLM calls were never priced either. It now prices through the same rules
  (`prices.cost_for_endpoint`, which resolves the endpoint by name so its preset is known).

History is not rewritten: the calls already billed keep the cost they were written with.

## Verification

- `pytest tests/shared/test_ai_cost_pipeline.py tests/shared/test_ai_call_log.py tests/shared/test_ai_prices.py
  tests/shared/test_ai_price_sync.py` — 41 passed.
- New tests: a synced price never bills the coding plan, a typed one still does; a call without tokens is free on the
  plan and unknown on a metered endpoint; a served tokenless call on the plan is logged with `cost = 0.0` and
  `cost_source = price_table`, and a metered one keeps `cost_source = none`; a **reported** tokenless call on the plan
  is priced 0 too, and a metered one keeps `cost_source = none`.
- Live (30 days before the fix): `minimax|minimax-m2.7-highspeed` 1 110 calls / $2.97 billed, its siblings on the same
  endpoint $0; `minimax-vlm|minimax-vlm` 14 866 calls with `cost = NULL` — half of them written by the server's
  triage worker, half by the host's.
- Live after the deploy (build 89444): a new `minimax-m2.7-highspeed` call lands with `cost = 0.0` /
  `cost_source = price_table`, and so do the tokenless VLM calls of the alert triage — the ones the server's triage
  worker writes and the ones the host writes. The row of a call a rule saved (outcome `avoided`) keeps its empty
  price: no call, no cost.
