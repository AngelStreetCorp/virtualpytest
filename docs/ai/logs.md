# AI logs and review runbook

This page explains where VirtualPyTest records AI activity and how to review
what visitors asked the public website assistant.

## Which log answers which question?

| Question | Source | What it contains |
| --- | --- | --- |
| Did visitors reach the website? | Vercel project logs/Analytics | Requests to the static website, status codes, and configured web analytics. |
| Did visitors use “Ask the AI”? | Public ask JSONL log | Timestamp, question, outcome, answer time, and source docs. |
| What did an authenticated internal agent do? | `backend_server/logs/agent_conversations.log` | Internal agent conversation events and debugging context. |
| What questions are most common? | `GET /server/public/stats` | Admin-only aggregates derived from the public ask log. |

The website is static and does not create a traffic log in this repository.
Traffic must be reviewed in the Vercel project connected to the deployment. A
page request does not prove that someone opened the AI panel or submitted a
question.

## Public website AI questions

The website sends questions to `POST /server/public/ask` on the API deployment.
The backend writes one JSON object per answered, cached, off-topic, or failed
question. The default path is `/tmp/vpt_public_ask_log.jsonl`.

Set `PUBLIC_ASK_LOG_FILE` to move it to persistent storage. The default
temporary path can be lost when a container or managed service restarts.
Entries include `ts`, `q`, normalized `key`, `outcome`, `seconds`, `sources`,
and a shortened IP hash. Outcomes are `answered`, `cached`, `off_topic`, and
`error`.

### Review through the admin endpoint

The server provides an admin-only summary endpoint:

```text
GET /server/public/stats?days=30&limit=50
```

It returns totals, cache ratio, off-topic/error counts, model time, and the most
frequent questions. It requires the normal authenticated admin session. Never
make it public or put an admin token in a website, prompt, or shell history.

```bash
set -euo pipefail
: "${VPT_API_BASE_URL:?Set VPT_API_BASE_URL}"
: "${VPT_ADMIN_TOKEN:?Set VPT_ADMIN_TOKEN in a secure session}"
curl --fail-with-body --silent --show-error \
  "$VPT_API_BASE_URL/server/public/stats?days=30&limit=50" \
  --header "Authorization: Bearer $VPT_ADMIN_TOKEN" | jq .
```

### Review the raw log on the server

When `PUBLIC_ASK_LOG_FILE` points to persistent storage:

```bash
set -euo pipefail
: "${PUBLIC_ASK_LOG_FILE:?Set PUBLIC_ASK_LOG_FILE to the known log path}"
tail -n 100 "$PUBLIC_ASK_LOG_FILE" | jq -s '{entries: length, outcomes: (group_by(.outcome) | map({outcome: .[0].outcome, count: length})), recent: .[-20:]}'
```

For Docker, use the mounted volume or service container. For a managed
platform, inspect its persistent volume/application logs rather than assuming
`/tmp` survives a restart.

## Internal agent conversations

Authenticated agent events are written to:
`backend_server/logs/agent_conversations.log`.
The location may be overridden by deployment configuration. Review it only on
the backend host or through the protected log viewer. These logs may contain
screen observations, tool arguments, device names, and user data. Redact
credentials, tokens, and customer information before sharing them.

For live deployments, use the service's normal log viewer, for example:

```bash
docker compose logs --since 1h vpt-server
```

## Website traffic review

Use the Vercel project dashboard for the deployment serving `virtualpytest.com`:

1. Check deployment access logs for requests and status codes.
2. Check Vercel Web Analytics if enabled.
3. Compare traffic timestamps with the public ask log's `ts` values.
4. Remember that traffic and submitted AI questions are different measures.

Enable persistent analytics or log export before relying on historical traffic.

## Safe credential check

The local `.env` is expected to hold deployment credentials. Check only whether
variables exist; never print their values:

```bash
for name in MCP_SECRET_KEY API_KEY SUPABASE_SERVICE_ROLE_KEY SUPABASE_JWT_SECRET MINIMAX_API_KEY; do
  if grep -q "^${name}=" .env 2>/dev/null; then echo "$name: configured"; else echo "$name: missing"; fi
done
```

Rotate any credential that has been printed, committed, pasted into chat, or
included in an untrusted log. Keep `.env` ignored by Git and use `.env.example`
for documentation.
