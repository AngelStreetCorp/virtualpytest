# Slack Integration Setup Guide

## Overview

The Slack integration allows you to sync AI Agent conversations from VirtualPyTest to your Slack workspace. Each conversation becomes a separate thread in a designated Slack channel, allowing your team to follow along with agent activities in real-time.

## Features

- ✅ **One-way sync** (VirtualPyTest → Slack)
- ✅ **Thread per conversation** (organized and searchable)
- ✅ **Agent nicknames** displayed in messages
- ✅ **Clean message format** (no tool calls/thinking by default)
- ✅ **No changes to AgentChat UI** (silent background sync)

## Prerequisites

⚠️ **Important**: You must create a Slack app to get authentication credentials. There is no way to integrate without this step (similar to how JIRA requires an API token).

## Setup Steps

### 1. Create Slack App

1. Go to [https://api.slack.com/apps](https://api.slack.com/apps)
2. Click **"Create New App"** → **"From scratch"**
3. Name your app: `VirtualPyTest AI` (or any name)
4. Select your workspace
5. Click **"Create App"**

### 2. Configure Bot Permissions

1. In your app settings, click **"OAuth & Permissions"** in the left sidebar
   - ⚠️ **Common mistake**: Don't use "Basic Information" - that shows App ID/Client ID which are NOT what we need!
2. Scroll down to **"Scopes"** section
3. Under **"Bot Token Scopes"**, click **"Add an OAuth Scope"** and add:
   - `chat:write` - Post messages to channels
   - `channels:read` - View channel list
   - `channels:history` - Read channel history (optional)

### 3. Install App to Workspace

1. After adding scopes, scroll back to the top of **"OAuth & Permissions"** page
2. Click **"Install to Workspace"** button
3. Review permissions and click **"Allow"**
4. You'll be redirected back to the OAuth & Permissions page

### 4. Copy Bot Token

1. On the **"OAuth & Permissions"** page, look for **"OAuth Tokens for Your Workspace"** section at the top
2. Copy the **Bot User OAuth Token** (starts with `xoxb-...`)
   - ⚠️ **This is what you need** - NOT the App ID or Client Secret!
   - ⚠️ Keep this token secret!

**What you're looking for:**
```
OAuth Tokens for Your Workspace

Bot User OAuth Token
xoxb-YOUR-BOT-TOKEN-WILL-BE-HERE
[Show] [Copy]
```

**What NOT to use:**
- ❌ App ID (found in "Basic Information")
- ❌ Client ID (found in "Basic Information")
- ❌ Client Secret (found in "Basic Information")
- ✅ Bot User OAuth Token (found in "OAuth & Permissions")

### 5. Create/Select Channel

1. In Slack, create a new channel: `#virtualpytest-ai`
2. Open channel details (click channel name)
3. Scroll down and copy the **Channel ID** (e.g., `C1234567890`)
   - Look for "Channel ID" in the "About" section

### 6. Invite Bot to Channel

In your Slack channel, type:
```
/invite @VirtualPyTest AI
```

### 7. Configure in VirtualPyTest

1. Navigate to **Plugins → Slack** in VirtualPyTest UI
2. Enter your **Bot Token** (the `xoxb-...` token from step 4)
3. Enter your **Channel ID** (from step 5)
4. Click **"Test Connection"** to verify credentials
5. Toggle **"Enable Integration"** to ON
6. Click **"Save Configuration"**
   - This creates `backend_server/config/integrations/slack_config.json` (gitignored)
7. Click **"Send Test Message"** to verify it works

**Authentication Flow:**
```
You create Slack app → Get bot token → Paste in VirtualPyTest UI
→ Saved to slack_config.json → Backend uses token for API calls
```

This is the same pattern as JIRA integration - credentials stored in JSON config file.

## Configuration Storage

Configuration is stored in `backend_server/config/integrations/slack_config.json`:

```json
{
  "enabled": true,
  "bot_token": "xoxb-XXXX-XXXX-XXXX",
  "channel_id": "C1234567890",
  "sync_tool_calls": false,
  "sync_thinking": false
}
```

- ✅ File is **gitignored** for security (like `jira_instances.json`)
- ✅ Created automatically when you save configuration through UI
- ✅ No environment variables needed
- ❌ **Never commit this file** - contains sensitive credentials

## Configuration Options

### Basic Settings

| Setting | Description | Where to Get It |
|---------|-------------|-----------------|
| **Bot Token** | Slack bot OAuth token | OAuth & Permissions page (starts with `xoxb-`) |
| **Channel ID** | Slack channel where messages post | Channel details in Slack (e.g., `C1234567890`) |
| **Enable Integration** | Toggle to enable/disable sync | Toggle in UI after saving credentials |

### Advanced Settings (Recommended: Keep disabled)

| Setting | Description | Recommended |
|---------|-------------|-------------|
| **Sync Tool Calls** | Include technical tool execution details | ❌ Disabled (too verbose) |
| **Sync Thinking** | Include AI reasoning/thinking process | ❌ Disabled (too verbose) |

## What Gets Synced?

### ✅ Synced to Slack:
- User questions
- Agent responses (final text only)
- Agent nicknames (Atlas, Sherlock, Scout, etc.)
- Conversation titles

### ❌ Not Synced (keeps Slack clean):
- Tool calls and technical details
- AI thinking/reasoning process
- Error messages (kept internal)
- Token/timing metrics

## Message Format

Conversations appear in Slack like this:

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

## Troubleshooting

### "I don't see a Bot Token"
**Problem**: You're looking at "Basic Information" which shows App ID/Client ID/Client Secret.

**Solution**: 
1. Go to **"OAuth & Permissions"** in the left sidebar
2. Add Bot Token Scopes if you haven't already
3. Click "Install to Workspace"
4. Look for "OAuth Tokens for Your Workspace" section at the top
5. Copy the token that starts with `xoxb-`

### "Channel not found"
- Verify the Channel ID is correct (should be like `C1234567890`)
- Check that it's a public channel or bot has been invited
- Copy Channel ID from Slack channel details, not channel name

### "Bot not in channel"
- Invite the bot: `/invite @YourBotName` in the Slack channel
- Bot must be a member of the channel to post messages

### "Authentication failed" or "invalid_auth"
- Verify the bot token starts with `xoxb-` (not App ID or Client Secret)
- Check token hasn't been revoked in Slack app settings
- Regenerate token if needed: OAuth & Permissions → Regenerate Token

### "not_authed" error
- Make sure you copied the entire token (they can be long)
- No extra spaces before/after the token
- Token should be from "Bot User OAuth Token", not other tokens

### No messages appearing in Slack
- Check "Enable Integration" is toggled ON in VirtualPyTest UI
- Verify configuration is saved (check status shows "Configured")
- Send a test message first to verify connection works
- Start a conversation in AgentChat to trigger sync
- Check backend logs: `journalctl -u backend_server -f | grep slack`

### Config file doesn't exist
- The file `slack_config.json` is created when you save configuration through UI
- If it doesn't exist, you haven't saved credentials yet
- Go to Plugins → Slack and configure

## Why Do We Need Credentials?

**Q: Can we integrate without API tokens?**

**A: No.** Slack requires OAuth-based authentication. There is no way to:
- ❌ Use email/password (Slack doesn't support this)
- ❌ Use personal tokens (not how Slack API works)
- ❌ Connect without credentials

This is Slack's security model - same as how JIRA requires an API token.

**Comparison with JIRA:**
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

Both require you to create credentials in the third-party platform first.

## Files Created

```
backend_server/
├── config/integrations/
│   ├── slack_config.json          # Configuration (created on save)
│   ├── slack_config.json.example  # Example template
│   └── slack_threads.json         # Thread mapping (auto-created)
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

## API Endpoints

All endpoints are at `/server/integrations/slack/`:

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/config` | Get current configuration |
| POST | `/config` | Update configuration |
| POST | `/test` | Test connection |
| GET | `/status` | Get sync status & stats |
| POST | `/send-test` | Send test message to channel |

## Future Enhancements (Phase 2)

- 🔄 **Bi-directional sync** (Slack → AI responses)
- 💬 **Slash commands** (`/ai ask "..."`)
- 👥 **Team collaboration** (mentions, approvals)
- 📊 **Report sharing** directly to threads
- 🔔 **Custom notifications** (test failures, alerts)

## Security Notes

- ✅ Bot token stored server-side only (never exposed to frontend)
- ✅ Config file excluded from git (add to .gitignore)
- ✅ Permissions follow principle of least privilege
- ✅ API endpoints protected by authentication

## Testing the Integration

### Test with curl:

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

If step 3 succeeds, you should see a message in your Slack channel!

### Connect to AgentChat (Manual - Phase 1)

Currently, the sync service is created but **not yet connected to AgentChat websocket events**.

To connect it, add this to `backend_server/src/routes/server_agent_routes.py`:

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

This will be automated in Phase 2.

## Support

For issues or questions:
1. Check backend logs: `journalctl -u backend_server | grep slack`
2. Review Slack app settings at [https://api.slack.com/apps](https://api.slack.com/apps)
3. Test connection in VirtualPyTest UI
4. Use curl commands above to test API endpoints

