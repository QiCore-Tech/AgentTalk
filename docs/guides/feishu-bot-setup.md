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
/trace msg-xxx
/guide reliability
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

Runtime flow:

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

## Step 7: Start AgentTalk Hub

Docker:

```bash
cp .env.example .env
docker compose up -d --build
```

Local process:

```bash
AGENTTALK_TOKEN=change-me FEISHU_ENABLE=1 FEISHU_APP_ID=cli_xxx FEISHU_APP_SECRET=xxx \
  uv run agenttalk hub serve \
    --host 0.0.0.0 \
    --port 8787 \
    --token change-me \
    --web-dist web/dist
```

Validate Hub health:

```bash
curl http://127.0.0.1:8787/health
```

Expected:

```json
{"status":"ok"}
```

## Step 8: Validate Bot Commands

Validate in Feishu:

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

```text
/trace <message-id>
```

Expected:

- Message delivery trace is returned, including sender, target, target machine, status, timestamps, done marker, error if present, and response preview.

```text
/guide reliability
```

Expected:

- Reliability guide is returned, including the delivery status chain and local relay commands.

## Reliable Delivery Notes

AgentTalk's local relay records a stronger delivery chain than the original MVP:

```text
sent -> delivered -> submitted -> acked -> completed
```

Status meanings:

| Status | Meaning |
|---|---|
| `sent` | Hub accepted the message. |
| `delivered` | Target relay claimed the message. |
| `submitted` | Local relay confirmed that the tmux submit key took effect. |
| `acked` | Target agent printed `AGENTTALK_ACK:<message-id>`. ACK is not a final answer; the target must continue the task until the done marker. |
| `completed` | Target agent printed the done marker and a response was captured. |
| `submit_unconfirmed` | Local relay suspects the text is still in the input box. Check the target machine's DLQ. |

Feishu can inspect Hub-visible message evidence with `/status`, `/response`, and `/trace`.
It cannot directly run local machine commands such as `agenttalk daemon restart` or `agenttalk dlq retry`.
Run those on the target developer machine:

```bash
agenttalk doctor
agenttalk daemon status
agenttalk daemon restart
agenttalk dlq list
agenttalk dlq retry <message-id>
agenttalk dlq fail <message-id> --reason "manual close"
```

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

## Setup Record

Fill this during setup and testing:

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
