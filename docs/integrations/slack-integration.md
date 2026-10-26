# Slack Integration

## Overview

The Slack integration copies your AI Agent conversations from VirtualPyTest into a Slack channel. Each conversation becomes its own thread. Your team can read the threads in Slack. They cannot reply from there.

<div data-technical>

Built the same way as the JIRA integration:
- **Configuration**: a JSON file (`~/.config/virtualpytest/slack_config.json`, outside the deploy tree)
- **Routes**: extended `server_integrations_routes.py`
- **UI**: React page at `/integrations/slack`
- **No environment variables needed**

</div>

## Quick Start

1. Create a Slack app at https://api.slack.com/apps
2. Add the bot permissions (scopes): `chat:write` and `channels:read`
3. Install the app to your workspace and copy the bot token (`xoxb-...`)
4. Copy the channel ID from the Slack channel details
5. In VirtualPyTest, open `Plugins → Slack`
6. Test the connection, then turn the integration on

## Configuration Format

<div data-technical>

```json
{
  "enabled": true,
  "bot_token": "xoxb-...",
  "channel_id": "C1234567890",
  "sync_tool_calls": false,
  "sync_thinking": false
}
```

Stored in `slack_config.json` under `~/.config/virtualpytest/` of the user the server runs as (`vpt_user`), or in `$VPT_CONFIG_DIR`. Thread mapping goes to `slack_threads.json` in the same folder.

</div>

## Message Flow

A message you write in AgentChat is copied to the server in the background. The server posts it to the thread in your Slack channel. Your team reads it there.

<div data-technical>

```
User message in AgentChat
    ↓
Backend (silent sync)
    ↓
Slack Service → Posts to channel thread
    ↓
Team views in Slack (read-only)
```

</div>

## What Gets Synced

**Copied to Slack:**
- Your questions
- The agent's final answers
- Agent names (Atlas, Sherlock, Scout and so on)
- Conversation titles

**Not copied** (to keep Slack short):
- Tool calls
- The agent's reasoning
- Error messages (internal only)
- Metrics (tokens, timing)

## API Endpoints

<div data-technical>

All at `/server/integrations/slack/`:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/config` | GET | Get configuration |
| `/config` | POST | Update configuration |
| `/test` | POST | Test connection |
| `/status` | GET | Get sync status |
| `/send-test` | POST | Send test message |

</div>

## Files

<div data-technical>

```
backend_server/
├── config/integrations/
│   ├── slack_config.json.example   # Template (live config: ~/.config/virtualpytest/)
│   └── slack-setup.md              # Detailed setup guide
├── src/
│   ├── integrations/
│   │   └── slack_sync.py           # Background sync service
│   └── routes/
│       └── server_integrations_routes.py  # API routes

frontend/src/pages/
└── SlackIntegration.tsx            # Configuration UI
```

</div>

## Example Slack Thread

A thread in Slack looks like a short chat. Each agent reply is listed under the question.

<div data-technical>

```
🤖 Automate web app testing
Conversation ID: abc12345... • 2025-01-15 14:30

User: Automate web app testing for login page

Atlas: I'll help you create automated tests...

Sherlock: Web interface analyzed. Creating test cases...

Atlas: ✅ Created 3 test cases for login functionality
```

</div>

## Troubleshooting

| Problem | What to do |
|-------|----------|
| Channel not found | Check the channel ID |
| Bot not in channel | Invite the bot: `/invite @BotName` |
| Authentication failed | Check the bot token. It starts with `xoxb-`. |
| No messages | Turn the integration on in the UI |

## Future Enhancements

- Two-way sync (Phase 2)
- Slack slash commands
- Team collaboration features
- Report sharing

## Security

- Your Slack credentials are stored in a JSON config file that git ignores.
- The bot token is never shown in the web page.
- Same security approach as the JIRA integration.
- The API endpoints require sign-in.
