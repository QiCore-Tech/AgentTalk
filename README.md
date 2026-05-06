# AgentTalk

AgentTalk is a lightweight LAN tool for communication between tmux-hosted AI agent CLIs.

Current implementation status: M1 Hub registry foundation.

## Development

```bash
uv sync --extra dev
uv run pytest
```

Run the Hub:

```bash
uv run agenttalk hub serve --token dev-token
```

List agents:

```bash
AGENTTALK_TOKEN=dev-token uv run agenttalk list --hub-url http://127.0.0.1:8787
```

## Agent Skill

Agents can use the bundled skill at `.agents/skills/agenttalk/SKILL.md` to learn when and how to call AgentTalk commands.

The skill covers:

- listing registered peer agents
- reading recent peer context
- sending point-to-point requests
- using `--watch` for feedback
- responding with the required completion marker
