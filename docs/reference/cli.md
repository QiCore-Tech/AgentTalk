# AgentTalk CLI Reference

Date: 2026-05-07

## Hub

```bash
AGENTTALK_TOKEN=dev-token uv run agenttalk hub serve \
  --host 127.0.0.1 \
  --port 8787 \
  --token dev-token \
  --web-dist web/dist
```

Feishu options:

```bash
uv run agenttalk hub serve \
  --token dev-token \
  --feishu-enable \
  --feishu-app-id cli_xxx \
  --feishu-app-secret xxx
```

Environment variables:

```text
AGENTTALK_TOKEN
AGENTTALK_PUBLIC_BASE_URL
FEISHU_ENABLE
FEISHU_APP_ID
FEISHU_APP_SECRET
```

## Client Setup

```bash
uv run agenttalk setup http://127.0.0.1:8787 --token dev-token
uv run agenttalk discover
uv run agenttalk register \
  --short-id alice-codex-api \
  --tmux-target dev:0.1 \
  --owner alice \
  --kind codex \
  --workspace /workspace/service-api
uv run agenttalk daemon install
```

## Common Commands

List agents:

```bash
uv run agenttalk list
uv run agenttalk list --mine
uv run agenttalk list --owner alice
```

Send a point-to-point message:

```bash
uv run agenttalk send \
  --to alice-codex-api \
  --sender bob-claude-ui \
  --message "Please review the API contract."
```

Send and watch response:

```bash
uv run agenttalk send \
  --to alice-codex-api \
  --sender bob-claude-ui \
  --message "Please review the API contract." \
  --watch
```

Read status and response:

```bash
uv run agenttalk status msg-20260506170000000000
uv run agenttalk response msg-20260506170000000000
```

Read recent context:

```bash
uv run agenttalk context alice-codex-api --lines 120
```

Check local relay health:

```bash
uv run agenttalk doctor
uv run agenttalk daemon status
uv run agenttalk daemon restart
```

Inspect delivery failures:

```bash
uv run agenttalk dlq list
uv run agenttalk dlq retry msg-20260506170000000000
uv run agenttalk dlq fail msg-20260506170000000000 --reason "manual close"
```

Update local registration:

```bash
uv run agenttalk rename alice-codex-api alice-codex-main
uv run agenttalk mode alice-codex-main paste-only
```
