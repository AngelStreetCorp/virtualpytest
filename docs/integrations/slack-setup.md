# Slack Integration Setup Guide

## Overview

This copies your AI agent conversations into a Slack channel, one thread per conversation. It is one way only: nothing comes back from Slack.

<div data-technical>

AgentChat is unchanged; the copy runs in the background. One thread per conversation, agent names in each message. Tool calls and the agent's thinking are left out by default.

</div>

<div data-technical>

- One thread per conversation, so threads are easy to find and search.
- Agent names appear in each message.
- Short messages: tool calls and the agent's thinking are left out by default.

</div>

## Before you start

You need a Slack app first. Slack only lets you in with a credential you create there.

## Setup Steps

### 1. Create a Slack app

1. Go to [https://api.slack.com/apps](https://api.slack.com/apps) and click **"Create New App"**, then **"From scratch"**.
2. Name it `VirtualPyTest AI` and choose your workspace.

<div data-technical>

Use the "From scratch" option. Any name works.

</div>

### 2. Set the bot permissions

1. Open **"OAuth & Permissions"** in the left sidebar. Do not use "Basic Information".
2. Under **"Bot Token Scopes"**, add the three permissions below.

<div data-technical>

- `chat:write`: post messages to channels
- `channels:read`: see the channel list
- `channels:history`: read channel history (optional)

</div>

### 3. Install the app to your workspace

Click **"Install to Workspace"** at the top of the page, then **"Allow"**.

### 4. Copy the bot token

Copy the **Bot User OAuth Token** under **"OAuth Tokens for Your Workspace"**. It starts with `xoxb-`. Keep it secret. The App ID and Client ID are not the token.

<div data-technical>

Do not copy the App ID, Client ID or Client Secret from "Basic Information". Use the token from "Bot User OAuth Token" only; other tokens will not work.

</div>

<div data-technical>

You will see a section like this on the page:

```
OAuth Tokens for Your Workspace

Bot User OAuth Token
xoxb-YOUR-BOT-TOKEN-WILL-BE-HERE
[Show] [Copy]
```

</div>

### 5. Create or choose a channel

Create a channel, for example `#virtualpytest-ai`. Open its details and copy the **Channel ID** from the "About" section.

<div data-technical>

Channel ID format: `C1234567890`. Channel name example: `#virtualpytest-ai`.

</div>

### 6. Invite the bot to the channel

In the channel, type this so the bot can post:

<div data-technical>

```
/invite @VirtualPyTest AI
```

</div>

### 7. Set it up in VirtualPyTest

1. Open **Plugins → Slack** in VirtualPyTest.
2. Paste the bot token and the Channel ID.
3. Click **"Test Connection"**, turn **"Enable Integration"** on, then click **"Save Configuration"**.
4. Click **"Send Test Message"** to check it works.

The settings are saved on the server, so a deploy does not erase them.

<div data-technical>

No environment variables are needed for Slack. The Enable Integration toggle appears after you save the credentials.

</div>

<div data-technical>

Saving creates `~/.config/virtualpytest/slack_config.json`, outside the project tree.

The token goes from Slack, into VirtualPyTest, and then to the server, which uses it for every Slack call:

```
You create Slack app → Get bot token → Paste in VirtualPyTest UI
→ Saved to slack_config.json → Backend uses token for API calls
```

This is the same pattern as the JIRA integration: credentials are stored in a JSON config file. The file is `slack_config.json` under `~/.config/virtualpytest/` of the user the server runs as (`vpt_user`), or in `$VPT_CONFIG_DIR`:

```json
{
  "enabled": true,
  "bot_token": "xoxb-XXXX-XXXX-XXXX",
  "channel_id": "C1234567890",
  "sync_tool_calls": false,
  "sync_thinking": false
}
```

It is created automatically when you save the configuration in the UI. The file is kept outside the project folder, like `jira_instances.json`. Add it to `.gitignore`. It holds your credentials and must never be committed to git.

</div>

## Configuration Options

| Setting | What it does |
|---------|--------------|
| **Bot Token** | The Slack bot's password (starts with `xoxb-`) |
| **Channel ID** | The channel where messages are posted |
| **Enable Integration** | Turns the copying on or off |

<div data-technical>

Advanced settings, keep these off:

| Setting | What it does | Recommended |
|---------|--------------|-------------|
| **Sync Tool Calls** | Adds the technical tool details | Off (too long) |
| **Sync Thinking** | Adds the agent's reasoning | Off (too long) |

</div>

## What Gets Synced

**Copied:** user questions, final agent answers, agent names and conversation titles.

**Not copied:** tool calls, the agent's thinking, errors, and token and timing numbers.

## Message Format

Each conversation starts one thread. Its layout is in the technical details.

<div data-technical>

```
🤖 New AI Conversation: "Automate web app testing"
Conversation ID: abc12345... • 2025-01-15 14:30

  User: Automate web app testing for login page
  
  Atlas: I'll help you create automated tests for the login page...
  
  Sherlock: Web interface analyzed. Creating test cases for:
  - Login form validation
  - Successful login flow
  - Error handling
  
  Atlas: ✅ Created 3 test cases covering login functionality
```

</div>

## Troubleshooting

### "I don't see a Bot Token"

You are probably on "Basic Information". Open **"OAuth & Permissions"** instead.

### "Channel not found"

- Copy the Channel ID from the channel details, not the channel name.

<div data-technical>

The channel must be public, or the bot must have been invited to it.

</div>

### "Bot not in channel"

Invite the bot with `/invite @YourBotName`. It must be a member before it can post.

### "Authentication failed" or "invalid_auth"

- The token must start with `xoxb-`. Create a new one under OAuth & Permissions if needed.

<div data-technical>

If the token was revoked, click Regenerate Token under OAuth & Permissions. An App ID or Client Secret will not work.

</div>

<div data-technical>

Error codes: `invalid_auth` and `not_authed`.

</div>

### "not_authed" error

- Copy the whole token, with no spaces around it.

### No messages appear in Slack

- Check that "Enable Integration" is on and the status says "Configured".
- Start a conversation in AgentChat to trigger a copy.

<div data-technical>

Check the backend logs:

```bash
journalctl -u backend_server -f | grep slack
```

</div>

### The configuration file does not exist

Go to **Plugins → Slack** and save your credentials.

## Why do we need credentials?

Slack only allows access with credentials you create in your Slack app first. The same is true for JIRA.

<div data-technical>

Email and password do not work with Slack, and personal tokens are not how the Slack API works. Without credentials, nothing connects.

</div>

<div data-technical>

Comparison of the two configs:

```json
// JIRA config (you created API token in Atlassian)
{
  "apiToken": "ATATT3xFfGF...",
  "domain": "your-team.atlassian.net"
}

// Slack config (you create Slack app, get bot token)
{
  "bot_token": "xoxb-...",
  "channel_id": "C1234567890"
}
```

This is Slack's security model, the same as the JIRA API token.

</div>

## Security Notes

- The bot token stays on the server and is never shown in the web page.
- Keep the config file private. The API endpoints require sign-in.

<div data-technical>

Permissions are the three scopes listed in step 2.

</div>

## Testing the Integration

Use **"Send Test Message"**. A message should appear in your channel.

<div data-technical>

If the third call works, a test message appears in your Slack channel.

</div>

<div data-technical>

```bash
# 1. Check status
curl http://localhost:5109/server/integrations/slack/status

# 2. Test connection
curl -X POST http://localhost:5109/server/integrations/slack/test \
  -H "Content-Type: application/json"

# 3. Send test message to Slack
curl -X POST http://localhost:5109/server/integrations/slack/send-test \
  -H "Content-Type: application/json"
```

</div>

## Connecting to AgentChat

AgentChat is not yet connected to the copy. The technical details show the manual hook.

<div data-technical>

To connect it by hand, add this to `backend_server/src/routes/server_agent_routes.py`:

```python
# At the top, after other imports
try:
    from integrations.agent_slack_hook import on_agent_message_websocket, on_user_message_websocket
    SLACK_HOOK_AVAILABLE = True
except ImportError:
    SLACK_HOOK_AVAILABLE = False

# In handle_message function, after logging user message (around line 331):
if SLACK_HOOK_AVAILABLE:
    on_user_message_websocket(session_id, 'User', message)

# In the event streaming loop, when emitting agent_event (around line 428):
if SLACK_HOOK_AVAILABLE and event.type in ['message', 'result']:
    on_agent_message_websocket(session_id, event.agent, event.content, event.type)
```

</div>

## Future Enhancements

Planned: two-way sync, slash commands, team features, report sharing and custom alerts.

<div data-technical>

Slash commands, for example `/ai ask "..."`, and team features such as mentions and approvals.

</div>

## Support

If something goes wrong, check your Slack app at [https://api.slack.com/apps](https://api.slack.com/apps) and test the connection in VirtualPyTest.

<div data-technical>

Use the curl commands above to test the API endpoints. Log search:

```bash
journalctl -u backend_server | grep slack
```

</div>

<div data-technical>

**Files created**

```
backend_server/
├── config/integrations/
│   └── slack_config.json.example  # Example template
├── src/
│   ├── integrations/
│   │   ├── __init__.py
│   │   └── slack_sync.py          # Sync service
│   └── routes/
│       └── server_integrations_routes.py  # API routes (extended)

frontend/
└── src/pages/
    └── SlackIntegration.tsx       # UI configuration page
```

**API endpoints.** All are at `/server/integrations/slack/`:

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/config` | Get current configuration |
| POST | `/config` | Update configuration |
| POST | `/test` | Test connection |
| GET | `/status` | Get sync status & stats |
| POST | `/send-test` | Send test message to channel |

</div>
