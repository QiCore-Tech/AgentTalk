# Docker Deployment Guide

Date: 2026-05-07

This guide describes the Docker deployment for AgentTalk Hub, Web UI, and the optional Feishu long-connection bot.

## Goal

Run the AgentTalk Hub as one container:

```text
AgentTalk Hub container
  ├─ FastAPI Hub
  ├─ SQLite database volume
  ├─ built Web UI
  └─ optional Feishu long-connection worker
```

Developer machines still run local relays outside the Hub container because they must access local tmux panes.

```text
Developer machine
  ├─ tmux agent panes
  └─ agenttalk daemon start
        -> AgentTalk Hub container
```

## Binding IP Or Domain

The Hub supports:

```bash
--host 0.0.0.0
--port 8787
--public-base-url https://agenttalk.company.lan
```

Container environment variables:

```dotenv
AGENTTALK_HOST=0.0.0.0
AGENTTALK_BIND=0.0.0.0
AGENTTALK_PORT=8787
AGENTTALK_PUBLIC_BASE_URL=https://agenttalk.company.lan
```

Use cases:

| Deployment | Bind | Public URL |
|---|---|---|
| Local test | `127.0.0.1:8787` | `http://127.0.0.1:8787` |
| LAN IP | `0.0.0.0:8787` | `http://192.168.1.20:8787` |
| Internal domain | `0.0.0.0:8787` behind reverse proxy | `https://agenttalk.company.lan` |

## Recommended Container Layout

```text
/app
  /src
  /web/dist
  /data
```

SQLite database path:

```text
/data/agenttalk.sqlite3
```

## Docker Files

The repository includes:

- `Dockerfile`
- `.dockerignore`
- `docker-compose.yml`
- `.env.example`
- `docker/entrypoint.sh`

The image builds `web/dist`, installs the Python package with the optional Feishu dependency, stores SQLite under `/data`, and starts `agenttalk hub serve`.

## docker-compose.yml

```yaml
services:
  agenttalk-hub:
    build: .
    container_name: agenttalk-hub
    restart: unless-stopped
    ports:
      - "${AGENTTALK_BIND:-0.0.0.0}:${AGENTTALK_PORT:-8787}:8787"
    environment:
      AGENTTALK_TOKEN: "${AGENTTALK_TOKEN}"
      AGENTTALK_PUBLIC_BASE_URL: "${AGENTTALK_PUBLIC_BASE_URL}"
      FEISHU_ENABLE: "${FEISHU_ENABLE:-0}"
      FEISHU_APP_ID: "${FEISHU_APP_ID:-}"
      FEISHU_APP_SECRET: "${FEISHU_APP_SECRET:-}"
    volumes:
      - agenttalk-data:/data

volumes:
  agenttalk-data:
```

## .env

```dotenv
AGENTTALK_TOKEN=change-me
AGENTTALK_BIND=0.0.0.0
AGENTTALK_PORT=8787
AGENTTALK_PUBLIC_BASE_URL=http://192.168.1.20:8787

FEISHU_ENABLE=0
FEISHU_APP_ID=
FEISHU_APP_SECRET=
```

For domain deployment:

```dotenv
AGENTTALK_BIND=127.0.0.1
AGENTTALK_PUBLIC_BASE_URL=https://agenttalk.company.lan
FEISHU_ENABLE=1
FEISHU_APP_ID=cli_xxx
FEISHU_APP_SECRET=xxx
```

## One-Command Startup

Recommended:

```bash
scripts/deploy-hub.sh
```

The script creates or updates `.env`, builds the Hub image, starts Docker Compose, and prints the Web URL and token.

Manual equivalent:

```bash
cp .env.example .env
docker compose up -d --build
```

Validate:

```bash
curl http://127.0.0.1:8787/health
```

Expected:

```json
{"status":"ok"}
```

## Reverse Proxy Example

Nginx-style target:

```nginx
server {
  listen 443 ssl;
  server_name agenttalk.company.lan;

  location / {
    proxy_pass http://127.0.0.1:8787;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
  }

  location /ws/ {
    proxy_pass http://127.0.0.1:8787;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
  }
}
```

## Relay Configuration From Developer Machines

Each developer machine points its local relay to the container URL:

```bash
scripts/start-client.sh \
  --hub-url http://192.168.1.20:8787 \
  --token change-me \
  --short-id alice-codex-api \
  --tmux-target dev:0.1 \
  --owner alice \
  --kind codex
```

For domain:

```bash
scripts/start-client.sh \
  --hub-url https://agenttalk.company.lan \
  --token change-me \
  --short-id alice-codex-api \
  --tmux-target dev:0.1
```

## Feishu With Docker

With long-connection mode, Feishu does not need inbound access to the Hub for event delivery. The Hub container needs outbound access to Feishu Open Platform.

Required environment:

```dotenv
FEISHU_ENABLE=1
FEISHU_APP_ID=cli_xxx
FEISHU_APP_SECRET=xxx
```

Recommended:

```dotenv
AGENTTALK_PUBLIC_BASE_URL=https://agenttalk.company.lan
```

This public base URL should be used when Feishu cards include an "Open Web" button.

If `FEISHU_ENABLE=1` but credentials are missing, the container exits with a clear startup error.

## Data Persistence

Persist:

```text
/data/agenttalk.sqlite3
```

Do not store Feishu secrets inside SQLite for the first Docker version. Use environment variables or Docker secrets.

## Security Notes

- Change `AGENTTALK_TOKEN` before team use.
- Do not expose the Hub to the public internet without authentication hardening.
- Use HTTPS for domain deployment.
- Treat Web terminal as remote control of registered tmux panes.
- Only register panes that are intended to receive AgentTalk input.

## Validation Checklist

- Build image.
- Start container.
- Call `/health`.
- Call `/api/agents` with bearer token.
- Open Web UI in a browser.
- If Feishu credentials are available, send `/help` to the bot.
