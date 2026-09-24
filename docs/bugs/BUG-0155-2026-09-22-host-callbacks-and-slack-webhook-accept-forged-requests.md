# BUG-0155 — Host callbacks and the Slack webhook accept anything that reaches them

> Bugs index: [README.md](README.md) · Release notes: [../release_note/README.md](../release_note/README.md)

| Field     | Value                                                        |
|-----------|--------------------------------------------------------------|
| ID        | BUG-0155                                                     |
| Reported  | 2026-09-22                                                   |
| Status    | Fixed (pending deploy)                                       |
| Severity  | High                                                         |
| Area      | backend / security                                           |
| Fixed in  | Unreleased                                                   |
| Commit    | TBD                                                          |

---

## Symptom

`/server/*` is closed by default, with an allowlist of paths the global guard lets through
without a principal. Five of those entries checked **nothing at all**:

- `POST /server/script/taskComplete`
- `POST /server/web/taskComplete`
- `POST /server/campaigns/executionComplete`
- `POST /server/deployment/executionComplete`
- `POST /server/integrations/slack/events`

Anything that could reach the server could therefore, with no credential:

- **mark any task complete** — `task_id` is the only required field, so a forged completion
  releases the device lock, ends the run early from the UI's point of view, and writes a
  result the page then displays;
- **inject a report URL** into that result, which the server converts to a signed URL and
  renders as the run's report;
- **make the server call an arbitrary URL** — the campaign callback takes
  `external_callback_url` straight from the request body and fans out to it;
- **inject a message into an agent chat session** through the Slack webhook, which parsed
  and acted on any JSON shaped like a Slack event.

## Root cause

The allowlist is the server's entire public attack surface, and it had drifted from its own
rule. Every other entry either returns no data (health probes, the pre-login `/auth/check`)
or authenticates itself inside the route — `/server/mcp` checks an `MCP_SECRET_KEY` bearer,
`/server/cicd/ingest` a `CICD_INGEST_TOKEN`, `/server/host-session/authorize` its own
short-lived cookie, `/server/public/ask` an Origin allowlist and per-IP rate limit.

The four host callbacks were exempted because hosts had no way to authenticate when the
allowlist was written. They have had one since: `server_auth_headers()` attaches the shared
`X-API-Key`, and register / ping / unregister / execution-events / the deployment scheduler's
own calls all use it. The callbacks were simply never migrated —
`docs/agent/platform/SERVER_AUTH.md` §8 still carried it as an open checklist item.

The Slack entry is worse: the same checklist recorded it as "signature-verified; keep
allowlisted", and the verification did not exist. The route read `request.json` and acted on
it. A documented control that was never implemented reads, in review, exactly like one that
works.

## Fix

**Host callbacks now carry the service key.** All seven host-side call sites pass
`headers=server_auth_headers()`:

- `backend_host/src/routes/host_script_routes.py` — success, error and the `finally`
  recovery callback
- `backend_host/src/routes/host_campaign_routes.py`
- `backend_host/src/routes/host_web_routes.py` — success and error
- `backend_host/src/services/deployment_scheduler.py` — the one call that lacked it while its
  two siblings in the same file already had it

The four prefixes are out of the allowlist in `backend_server/src/app.py`, so an
uncredentialed completion is a 401. `X-API-Key` resolves to the `service` principal, which
passes the viewer floor and is exempt from team scoping, so the handlers are reached exactly
as before.

**The Slack webhook verifies Slack's signature.** `verify_slack_signature()` in
`backend_server/src/integrations/slack_sync.py` implements the documented scheme — HMAC-SHA256
over `v0:<timestamp>:<raw body>`, compared with `hmac.compare_digest`, plus Slack's five-minute
replay window. It runs before the body is parsed, and **fails closed**: no `signing_secret` in
`slack_config.json` means every inbound event is refused, because an unconfigured secret must
mean "refuse", not "skip the check". The rejection reason goes to the log, never the response.

**The allowlist is now pinned.** It moved to the module-level
`UNAUTHENTICATED_SERVER_PREFIXES` with a comment stating the rule, and
`tests/backend_server/test_unauthenticated_surface.py` asserts its exact contents against a
table that names the credential each entry checks. Adding an entry fails the test until
someone writes down what authenticates it.

## Verification

```bash
python3 -m pytest tests/backend_server/test_unauthenticated_surface.py -q   # 16 passed
python3 -m pytest tests/backend_server -q -m unit                           # 127 passed
```

Both new tests were checked against a deliberately reintroduced regression and fail: removing
`headers=` from one callback fails the credential test, and the surface test fails on any
allowlist change.

Not verified against a running deployment. The live suites (`test_web.py`,
`test_campaign_execution.py`) POST to these callbacks and will need the API key in their
headers; they drive `:5109` and were not run.

## Upgrade

**Deploy the server and every host together.** This is one change at two hops. A host on
older code sends no key, so its completion callbacks 401 — and a 401 is a response, not an
exception, so the host logs nothing and the page waits out its full 120s socket timeout before
falling back to polling. That is BUG-0151's symptom exactly.

```
ssh proxmox "bash update_core.sh"          # server + hosts
```

Every host needs `API_KEY` set and matching the server's. A host without one sends no header
and its callbacks are refused.

**Inbound Slack stops until its secret is configured.** Add `signing_secret` (Slack app →
Basic Information → Signing Secret) to `backend_server/config/integrations/slack_config.json`.
Outbound messages are unaffected — only replies coming back from Slack are gated.
