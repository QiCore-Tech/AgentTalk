# Server Quickstart

Date: 2026-05-07

The Hub is the AgentTalk server. It stores agent registrations, messages, context, Web UI assets, and the optional Feishu bot worker.

## One-Command Docker Deploy

From the repo root:

```bash
scripts/deploy-hub.sh
```

The script creates `.env` on first run, generates a token if needed, builds the image, starts Docker Compose, and prints the Web URL and token.

Common options:

```bash
scripts/deploy-hub.sh \
  --bind 0.0.0.0 \
  --port 8787 \
  --public-base-url http://192.168.1.20:8787
```

For an internal domain behind a reverse proxy:

```bash
scripts/deploy-hub.sh \
  --bind 127.0.0.1 \
  --port 8787 \
  --public-base-url https://agenttalk.company.lan
```

## Enable Feishu Bot

```bash
scripts/deploy-hub.sh \
  --feishu \
  --feishu-app-id cli_xxx \
  --feishu-app-secret xxx
```

If `.env` already exists, edit these values there:

```dotenv
FEISHU_ENABLE=1
FEISHU_APP_ID=cli_xxx
FEISHU_APP_SECRET=xxx
```

Then restart:

```bash
docker compose up -d --build
```

## Validate

```bash
curl http://127.0.0.1:8787/health
```

Expected:

```json
{"status":"ok"}
```

With token:

```bash
curl -H "Authorization: Bearer <token>" http://127.0.0.1:8787/api/agents
```

## Operations

View logs:

```bash
docker compose logs -f agenttalk-hub
```

Stop:

```bash
docker compose down
```

Upgrade after pulling new code:

```bash
scripts/deploy-hub.sh
```

SQLite data persists in the Docker volume `agenttalk-data`.
