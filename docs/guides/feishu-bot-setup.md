# Feishu Bot Setup Guide

Date: 2026-05-07

This guide walks through the Feishu-side setup for AgentTalk's Feishu bot integration.

AgentTalk uses Feishu long-connection mode. That means the AgentTalk Hub connects outbound to Feishu Open Platform and does not need a public callback URL for receiving Feishu events.

References:

- Feishu long-connection event subscription: `https://feishu.apifox.cn/doc-7518429`
- Feishu Python SDK: `https://github.com/larksuite/oapi-sdk-python`

## Target Result

After setup, users can chat with the Feishu bot:

```text
/help
/agents
/agents online
/agent alice-codex-api
/context alice-codex-api
/send alice-codex-api 请检查接口契约
/status msg-xxx
/response msg-xxx
```

Expected deployment shape:

```text
Feishu user/chat
  <-> Feishu Open Platform long connection
  <-> AgentTalk Hub container
  <-> AgentTalk Hub API / SQLite / Web UI
```

## Prerequisites

- You have administrator access to Feishu Open Platform for your company.
- You can create or edit a self-built app.
- You have an AgentTalk Hub host that can access the internet outbound.
- You have decided the AgentTalk Hub URL, such as:

```text
http://192.168.1.20:8787
https://agenttalk.company.lan
```

Long-connection mode does not require the Hub to be accessible from Feishu over inbound HTTP.

## Step 1: Create A Self-Built App

In Feishu Open Platform:

1. Open the developer console.
2. Create a company self-built app.
3. Name it clearly, for example:

```text
AgentTalk
```

4. Open the app detail page.
5. Go to credentials/basic information.
6. Copy:

```text
App ID
App Secret
```

These map to AgentTalk environment variables:

```text
FEISHU_APP_ID=cli_xxx
FEISHU_APP_SECRET=xxx
```

## Step 2: Add Bot Capability

In the app management page:

1. Go to app capabilities.
2. Add or enable Bot.
3. Set bot name and avatar.
4. Keep the bot name short enough for users to recognize in chat.

Recommended bot name:

```text
AgentTalk
```

## Step 3: Enable Event Subscription With Long Connection

In the app management page:

1. Go to event subscription.
2. Choose long-connection mode.
3. Do not configure a public callback URL for AgentTalk's first version.
4. Add message receive events needed for bot chat.

The exact event names should be verified in the current Feishu console, but the required capability is receiving user messages sent to the bot.

Implementation target:

```text
Feishu message event
  -> AgentTalk command parser
  -> AgentTalk command handler
  -> Feishu text/card reply
```

## Step 4: Add Permissions

The exact permission names can vary in Feishu's console. Before implementation and production use, verify current names in the app permission page.

Minimum expected permission categories:

| Capability | Why AgentTalk Needs It |
|---|---|
| Receive messages/events | Parse `/agents`, `/send`, and other commands. |
| Send messages as bot | Reply with text and cards. |
| Send interactive cards | Render agent list/detail cards. |

If the bot will be used in group chats, make sure the app/bot is allowed in group chat contexts.

## Step 5: Publish Or Enable The App Internally

Depending on company Feishu policy:

1. Submit the app for internal release or admin approval.
2. Install/enable the app for the target users or groups.
3. Add the bot to a group or open a direct chat with it.

MVP access policy:

- Users/chats that can talk to the bot can use AgentTalk commands.
- AgentTalk records Feishu operator ID where available.
- No complex permission matrix is enforced in the first version.

## Step 6: Prepare AgentTalk Hub Configuration

Recommended `.env` for Docker deployment:

```dotenv
AGENTTALK_TOKEN=change-me
AGENTTALK_HOST=0.0.0.0
AGENTTALK_PORT=8787
AGENTTALK_PUBLIC_BASE_URL=https://agenttalk.company.lan

FEISHU_ENABLE=1
FEISHU_APP_ID=cli_xxx
FEISHU_APP_SECRET=xxx
```

Equivalent command flags:

```bash
agenttalk hub serve \
  --host 0.0.0.0 \
  --port 8787 \
  --token change-me \
  --feishu-enable \
  --feishu-app-id cli_xxx \
  --feishu-app-secret xxx
```

## Step 7: Validate Bot Commands

After implementation and deployment, validate in Feishu:

```text
/help
```

Expected:

- Command list is returned.

```text
/agents
```

Expected:

- Agent list card or formatted text is returned.

```text
/agent <known-agent-id>
```

Expected:

- Agent detail card is returned.

```text
/context <known-agent-id>
```

Expected:

- Recent context is returned, truncated.

```text
/send <known-agent-id> hello from Feishu
```

Expected:

- AgentTalk message is created.
- Feishu reply includes `message_id`.

```text
/status <message-id>
/response <message-id>
```

Expected:

- Message status and response are returned.

## Troubleshooting

### Bot Does Not Reply

Check:

- `FEISHU_ENABLE=1`
- App ID and App Secret are correct.
- The app has Bot capability enabled.
- Event subscription is using long-connection mode.
- Required message receive event is added.
- Hub container has outbound internet access.

### Bot Receives Commands But Cannot Send Replies

Check:

- Bot has message send permissions.
- The app has been published or enabled for the chat/user.
- The bot is present in the target group chat if testing in a group.

### `/agents` Returns Empty

Check:

- AgentTalk relay is running on developer machines.
- Agents have been registered.
- Hub token in relays matches Hub token.
- `agenttalk list` works from the Hub host or a developer machine.

### `/send` Creates Message But Agent Does Not React

Check:

- Target agent is online.
- Target relay is running.
- Target pane is still valid.
- Agent receive mode is `auto_submit` unless paste-only is intentional.

## Information To Collect During Setup

Fill this before implementation/testing:

```text
Feishu app name:
App ID:
App Secret stored in:
Bot name:
Enabled event mode: long connection
Enabled message receive event:
Enabled send-message permission:
Target Feishu test chat:
AgentTalk Hub URL:
AgentTalk Web URL:
```
