# M2 Contract Checklist

Date: 2026-05-07

Design inputs:

- `docs/plans/2026-05-07-agenttalk-design-decisions.md`
- `docs/plans/2026-05-07-agenttalk-ux-architecture-design.md`
- `docs/plans/2026-05-07-agenttalk-mvp-implementation-plan.md`

## Scope

M2 implements local relay configuration, tmux pane discovery, local registration workflows, and heartbeat/upsert behavior against the M1 Hub API.

## Safety Constraint

Implementation and automated tests must not send input to existing tmux panes. M2 tests use fake tmux command output only.

Allowed tmux command in production code:

- `tmux list-panes -a -F ...`

Disallowed in M2 implementation:

- `tmux send-keys`
- `tmux paste-buffer`
- `tmux capture-pane`
- `tmux kill-pane`
- `tmux attach`

## Local Config Shape

Config path:

```text
~/.agenttalk/config.json
```

Required fields:

- `hub_url`
- `token`
- `machine_id`
- `host_name`
- `user_name`
- `agents`

Each agent binding:

- `short_id`
- `owner`
- `kind`
- `workspace`
- `tmux_target`
- `pane_id`
- `receive_mode`

## CLI Commands

| Command | Purpose | Key Checks |
|---|---|---|
| `agenttalk discover` | Print candidate tmux panes | read-only tmux list, no pane input |
| `agenttalk register` | Register selected pane binding locally and on Hub | validates short ID and receive mode |
| `agenttalk setup <hub-url>` | Save Hub config and optionally register panes | supports non-interactive options for tests |
| `agenttalk list --mine` | List agents for configured local machine | filters by `machine_id` |
| `agenttalk rename` | Rename local binding and upsert to Hub | old ID must exist locally |
| `agenttalk mode` | Update local receive mode and upsert to Hub | mode enum checked |
| `agenttalk daemon start` | Run relay heartbeat/upsert loop | no tmux input in M2 |

## Relay Behavior

- Registers relay on startup.
- Heartbeats periodically.
- Upserts all locally registered agents.
- Detects whether configured pane targets still appear in discovery output.
- If pane is missing, upserts the agent as `offline`.
- If pane is present, upserts the agent as `online`.

## M2 Acceptance Checks

- Discovery parses multiple fake tmux panes.
- Agent kind detection identifies claude, codex, gemini, and unknown.
- Local config can save and load multiple agent bindings.
- Registering multiple bindings upserts them to a test Hub.
- `agenttalk list --mine` filters by local machine ID.
- Relay one-shot sync registers relay and upserts configured agents.
- No automated test invokes real tmux.
