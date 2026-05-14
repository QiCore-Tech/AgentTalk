# Agent Instructions

This repository ships an AgentTalk skill for AI agents.

Before using AgentTalk from this repo, read:

```text
.agents/skills/agenttalk/SKILL.md
```

Use that skill when you need to:

- list registered LAN agents;
- inspect a peer agent's recent tmux context;
- send a tracked point-to-point AgentTalk message;
- watch delivery, output deltas, and completion markers;
- explain or use the Feishu AgentTalk bot commands.

Do not send input to arbitrary tmux panes. Only use AgentTalk commands or registered panes that are explicitly intended to receive AgentTalk input.

For tmux tests, only use sessions named:

```text
agenttalk-e2e-*
```

Do not touch existing development panes.

---

## Repo Structure

- `src/agenttalk/` — Python package. Hub (`hub/`), relay (`relay.py`), CLI (`cli.py`), Feishu bot (`feishu/`).
- `web/` — React + Vite frontend. Built into `web/dist` and served by the Hub.
- `tests/` — pytest suite. Uses `pythonpath = ["src"]`.
- `scripts/` — Shell helpers for deploy, setup, and E2E tests.
- `docs/` — Markdown docs and planning artifacts.

## Key Commands

### Python
```bash
# Run all tests
uv run pytest

# Run a single test file
uv run pytest tests/test_relay.py -v

# Run the Hub locally
uv run agenttalk hub serve --port 8787 --token <token>

# Start the local relay (one-shot sync)
uv run agenttalk daemon start --once
```

### Web
```bash
cd web
npm install
npm run build     # outputs to web/dist
npm run lint
npm run test:e2e  # requires Playwright
```

### Docker / Deploy
```bash
# First deploy (creates .env)
scripts/deploy-hub.sh --token <token>

# Rebuild and restart
uv run agenttalk hub serve --token <token> --database /data/agenttalk.sqlite3
docker compose up --build -d
```

## Architecture Notes

- **Hub** is a FastAPI app (`src/agenttalk/hub/app.py::create_app`). It serves REST APIs, WebSockets (`/ws/terminal/`, `/ws/pty/`), and the static web build.
- **Store** is SQLite (`hub/store.py`). Tests create isolated DBs via `tmp_path`.
- **Relay** (`relay.py`) runs on each dev machine. It polls the Hub for messages, injects them into local tmux panes, and reports health/status back.
- **CLI** (`cli.py`) wraps both Hub and relay operations. Entry point: `agenttalk`.
- **Feishu bot** is optional. Enabled via `--feishu-enable` and configured with app ID/secret.
- **PTY terminal** in the Web UI requires the Hub process to access the tmux socket (mounted in Docker via `/tmp/tmux-1000`).

## Testing Conventions

- Tests use `pytest` with `pytest-asyncio`.
- Feishu worker tests may need the Feishu env vars and can be slow; skip with `--ignore=tests/test_feishu_worker.py` if needed.
- E2E suite (`scripts/test-all.sh`) requires a running Hub, a tmux session, and the CLI to be installed.
- The autouse fixture `isolate_watch_state` in `test_relay.py` redirects relay watch-state files to `tmp_path` so tests do not pollute `~/.agenttalk/`.

## Operational Gotchas

- `AGENTTALK_TOKEN` is required for the Hub and must match on relay clients.
- The Docker entrypoint (`docker/entrypoint.sh`) links host tmux socket paths (`/tmp/tmux-1000/default` → `/tmp/tmux-0/default`) so the Hub can access tmux for PTY/WebSocket terminals.
- Windows agents do not use tmux; `--tmux-target` is just an identifier string.
- Generated code: `web/dist` is produced by `npm run build` and copied into the Docker image. Do not commit it.

## Git Remotes

Use SSH for pulls/pushes to avoid TLS issues:
```bash
git remote set-url origin ssh://git@git.qicore.tech:29418/QiCore/soha_agentTalk.git
```

## Relevant Instruction Sources

- `.agents/skills/agenttalk/SKILL.md` — Agent skill for peer-to-peer communication
- `docs/reference/cli.md` — Full CLI reference
- `docs/guides/server-quickstart.md` — Hub setup guide
- `docs/guides/client-quickstart.md` — Relay setup guide
