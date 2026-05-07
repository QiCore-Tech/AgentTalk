# Client Quickstart

Date: 2026-05-07

The client is the developer machine that owns tmux panes. It runs the local AgentTalk relay so the Hub can deliver messages and collect context.

## Requirements

- Python 3.12+
- `uv`
- tmux
- network access to the Hub server

Install dependencies:

```bash
uv sync --extra dev
```

## Discover tmux Panes

This is read-only:

```bash
scripts/start-client.sh --discover
```

Pick one explicit tmux target, such as:

```text
dev:0.1
```

## Start Client Relay

Use the Hub URL and token printed by `scripts/deploy-hub.sh`:

```bash
scripts/start-client.sh \
  --hub-url http://192.168.1.20:8787 \
  --token <token> \
  --short-id alice-codex-api \
  --tmux-target dev:0.1 \
  --owner alice \
  --kind codex \
  --workspace /workspace/service-api
```

The script:

1. saves local Hub config;
2. registers exactly the tmux target you passed;
3. starts `agenttalk daemon start`.

For a one-time sync:

```bash
scripts/start-client.sh \
  --hub-url http://192.168.1.20:8787 \
  --token <token> \
  --short-id alice-codex-api \
  --tmux-target dev:0.1 \
  --once
```

## Safety

`--discover` only reads tmux pane metadata.

Message delivery writes to registered tmux panes. Only pass a `--tmux-target` that is intended to receive AgentTalk input.

For tests, only use tmux sessions named:

```text
agenttalk-e2e-*
```
