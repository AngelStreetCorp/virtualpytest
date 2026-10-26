# BUG-0383 — Atlas post-deploy suite lost two checks and could not catch the 404 link or a new-chat crash

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0383                                                       |
| Reported  | 2026-10-05                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | Medium                                                           |
| Area      | tests                                                   |
| Fixed in  | build 90145 |
| Commit    | `TBD`                                                        |

---

## Symptom

The last live run recorded neither "canvas has an Open in Grafana draft link" nor "DASHBOARD JSON shows the template variables"; the DASHBOARD check failed a correct run because the grafana-dashboard skill was not loaded; the link check shrugged at a cross-origin fetch; "BUG-0340 send during outage (new chat)" crashed on main waiting 90 s for the landing placeholder.

## Root cause

(a) The aggregation loop did `if (r.status === 'NA') continue`, so every check whose result was NA vanished from results.json and the summary. (b) The check demanded the skill, not the outcome. (c) The link was fetched with `fetch()` from the page: a link on another host is cross-origin and became NA instead of a failure. (d) A fresh browser context on main opens on the user's last conversation (input placeholder "Message..."), and `loadChat` only accepted the empty landing placeholder ("How can I help you?"); not a product bug.

## Fix

NA rows are recorded; a self-check row fails the run when the recorded (check, server) rows differ from the ones defined (`expectedRows`). The dashboard checks judge the outcome (one `create_grafana_draft` with 2+ panels, a link that returns HTTP 200, nothing narrowed to a device nobody named) and report whether the skill loaded; a second prompt without the word "grafana" must reach the same outcome. Links are fetched from Node with the session cookies (redirects followed) and FAIL on 404 or an unreachable host. `loadChat` accepts either placeholder (and screenshots on failure), `newChat` always opens the empty landing.

## Verification

Live run against the deployed build: every defined row present, the self-check row passes, the link checks fail on 404 until BUG-0378 is deployed.
