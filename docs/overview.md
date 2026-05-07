# AgentTalk Overview

Date: 2026-05-07

AgentTalk is a lightweight LAN communication console for tmux-hosted AI agent CLIs.

## Architecture

```text
tmux agent pane
  <-> local AgentTalk client relay
  <-> AgentTalk Hub server
  <-> CLI / Web UI / Feishu bot / other relays
```

## Components

- Hub server: FastAPI, SQLite, Web UI, optional Feishu long-connection worker.
- Client relay: local process that owns tmux access for a developer machine.
- CLI: setup, registration, list, send, status, response, context.
- Web UI: agent monitor, detail pages, context view, structured messages, terminal view.
- Agent skill: repo-local instructions for AI agents.

## Implemented Milestones

- M1: Hub registry, SQLite storage, token auth, CLI list.
- M2: local config, read-only tmux discovery, relay sync, registration CLI.
- M3: point-to-point messages and tmux injection.
- M4: response watch, marker completion, context capture.
- M5: React/Vite Web console.
- M6: xterm.js terminal view and Hub WebSocket bridge.
- Feishu bot: long-connection command entry point.
- Docker Hub deployment.

## Current Limitations

- Web terminal currently assumes the Hub process can access the registered tmux target locally. True multi-machine terminal streaming should be routed through the target relay.
- Web token handling is MVP-level. `VITE_AGENTTALK_TOKEN` or `dev-token` is suitable for local testing only.
- There is no terminal input lock. Multiple Web clients can type if they can reach the endpoint.
- xterm.js is bundled in the initial Web chunk. Lazy loading should be added later if bundle size matters.

Tracked in:

- [Assumption register](plans/assumption-register.md)
