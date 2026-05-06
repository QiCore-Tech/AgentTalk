# M4 Contract Checklist

Date: 2026-05-07

## Scope

M4 implements watch feedback, response deltas, completion marker detection, timeout behavior, and recent context reading.

## Safety Constraint

Automated and manual tmux tests must only use dedicated `agenttalk-e2e-*` sessions. Existing panes listed in `protected-tmux-panes.md` must not receive input or control commands.

## API

| Endpoint | Method | Purpose |
|---|---:|---|
| `/api/messages/{message_id}/response` | GET | Return bounded response text for a message |
| `/api/messages/{message_id}/response` | POST | Relay appends response delta and optionally completes message |
| `/api/agents/{short_id}/context` | GET | Return recent tmux context captured by relay |
| `/api/agents/{short_id}/context` | POST | Relay updates recent context snapshot |

## CLI

| Command | Purpose |
|---|---|
| `agenttalk send --watch` | Poll status and response until completed, failed, or timeout |
| `agenttalk response <message-id>` | Print stored response text |
| `agenttalk context <agent-id> --lines <n>` | Print recent context for a registered agent |

## Acceptance

- Done marker changes status to `completed`.
- Output before marker is stored as response text.
- Timeout preserves partial output.
- `context` returns bounded recent output.
- Tests cover marker detection without touching protected panes.
