# AgentTalk Feishu Integration Design

Date: 2026-05-07

## Goal

Add a Feishu bot entry point so users can chat with AgentTalk from Feishu. The bot should query registered agent status, inspect recent context, send point-to-point messages, query message status, and read responses.

The bot should support text commands and interactive cards while keeping full terminal control in the Web UI.

## Confirmed Decisions

1. Use Feishu long-connection mode.
2. Start the Feishu bot from `agenttalk hub serve`.
3. Support text commands and interactive cards.
4. First access policy is permissive for users/chats that can talk to the installed bot.
5. Record Feishu operator IDs for traceability.
6. Do not expose full terminal control in Feishu.
7. Reuse AgentTalk Hub service capabilities; Feishu does not directly control tmux.

## Architecture

```text
agenttalk hub serve
  ├─ FastAPI Hub API
  ├─ SQLite store
  ├─ Web UI
  └─ Feishu long-connection bot worker
        <-> Feishu Open Platform
        <-> AgentTalk internal service layer
```

The Feishu worker runs inside the Hub process and uses Feishu's long-connection SDK to receive events. Command handlers call AgentTalk service functions or internal Hub APIs.

## Startup

CLI flags:

```bash
agenttalk hub serve \
  --host 0.0.0.0 \
  --port 8787 \
  --token dev-token \
  --feishu-enable \
  --feishu-app-id cli_xxx \
  --feishu-app-secret xxx
```

Environment variables:

```text
FEISHU_ENABLE=1
FEISHU_APP_ID=cli_xxx
FEISHU_APP_SECRET=xxx
```

CLI flags take precedence over environment variables.

## Text Commands

```text
/help
/agents
/agents online
/agent <agent-id>
/context <agent-id>
/send <agent-id> <message>
/status <message-id>
/response <message-id>
```

Command behavior:

- `/help`: command summary.
- `/agents`: list registered agents with status.
- `/agents online`: list non-offline agents.
- `/agent <agent-id>`: show metadata and recent context summary.
- `/context <agent-id>`: show recent context, truncated.
- `/send <agent-id> <message>`: create AgentTalk message; sender should identify Feishu operator.
- `/status <message-id>`: show message lifecycle status.
- `/response <message-id>`: show stored response text, truncated.

## Interactive Cards

Cards should be used for high-signal summaries:

### Agents Card

Triggered by:

```text
/agents
```

Content:

- short id
- owner
- kind
- workspace
- status badge

Actions:

- Detail
- Context
- Open Web

### Agent Detail Card

Triggered by:

```text
/agent <agent-id>
```

Content:

- short id
- owner
- kind
- machine
- workspace
- receive mode
- status
- recent context excerpt

Actions:

- Context
- Open Web
- Send instructions

## Response Limits

Feishu messages should be bounded to avoid flooding chats.

Recommended defaults:

- agent list: 20 agents per response
- context: last 80 lines or 4,000 characters
- response text: 4,000 characters
- card field values: truncate long workspace/context strings

## Error Handling

Return clear user-facing messages:

- unknown command
- missing argument
- target agent not found
- target agent offline
- message not found
- Feishu API send failure
- Hub internal error

Do not expose stack traces in Feishu chat.

## Security

First version is intentionally permissive:

- If a user or chat can talk to the installed bot, it can use AgentTalk commands.
- Record Feishu operator ID and chat ID in logs or message sender metadata.
- Do not add a complex permission matrix in this version.

Future hardening can add:

- allowed `open_id` list
- allowed `chat_id` list
- command-level restrictions
- `/send` approval rules

## Non-Goals

- Feishu terminal control
- full tmux streaming inside Feishu
- complex multi-step forms
- cross-chat task routing policy
- rich permission system

## External References To Verify Before Implementation

Implementation must verify current official Feishu docs for:

- long-connection SDK setup
- message receive event payload
- sending text messages
- sending interactive cards
- card action event payload
- app credentials and token handling

Known starting references:

- Feishu long-connection mode: `https://feishu.apifox.cn/doc-7518429`
- Python SDK package: `https://pypi.org/project/lark-oapi/`
