# BUG-0384 — Atlas invented a host for a relative Grafana link

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0384                                                     |
| Reported  | 2026-10-05                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                       |
| Area      | ai-agent                                                     |
| Fixed in  | Unreleased                                                   |

## What happened
Asked through `scripts/atlas_chat.py` to "create a Grafana dashboard with pass rate by device, failing test cases and incidents over time", Atlas built the draft correctly but answered with `https://analitics.ai/grafana/d/atlas-draft-4ea3e0f4cce0dbd3b76e` — a host that does not exist.

## Cause
Since BUG-0381 the server returns only the dashboard path; the web app sends its Grafana base (`grafana_base_url`) so the answer carries a full link. Clients that send no base (atlas_chat.py, external MCP clients) got the bare path `/grafana/d/<uid>`, and the model "completed" it with a guessed host.

## Fix
`grafana_push.link_for_reply`: with a base, the full URL as before; without one, the path plus "a path on the VirtualPyTest web app: give it to the user exactly as written, never add or guess a host". Used by `render_analytics_artifact` and `create_grafana_draft` replies. Test: `test_relative_link_tells_the_model_not_to_invent_a_host`.
