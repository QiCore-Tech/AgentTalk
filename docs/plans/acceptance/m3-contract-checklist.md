# M3 Contract Checklist

Date: 2026-05-07

## Scope

M3 implements point-to-point message creation, status tracking, relay polling delivery, and tmux injection primitives.

## Safety Constraint

Automated tests must not inject into real tmux panes. M3 tests use fake tmux injection clients only.

Production code may introduce injection commands, but no manual smoke test may call them against existing panes without explicit user approval.

## Message Status Enum

- `sent`
- `delivered`
- `injected`
- `working`
- `completed`
- `timeout`
- `failed`

## HTTP API

| Endpoint | Method | Purpose | Key Checks |
|---|---:|---|---|
| `/api/messages` | POST | Create point-to-point message | token required, target must exist and be online |
| `/api/messages/{message_id}` | GET | Get message status | token required, 404 if missing |
| `/api/relays/{machine_id}/messages/next` | GET | Relay polls next pending message | token required, only returns messages for that machine |
| `/api/messages/{message_id}/status` | POST | Relay updates delivery/injection status | token required, status enum checked |

## CLI

| Command | Purpose |
|---|---|
| `agenttalk send --to <id> --message <text>` | Create message and print status |
| `agenttalk status <message-id>` | Print current message status |

## Injected Message Format

Injected payload must include:

- `[AgentTalk Message]`
- `message_id`
- `from`
- `to`
- task text
- exact completion marker: `<<<AGENTTALK_DONE:<message-id>>>`

## Receive Mode

- `auto_submit`: write payload and submit with Enter.
- `paste_only`: write payload without Enter.

## M3 Acceptance Checks

- Creating a message to an online agent returns `sent`.
- Creating a message to a missing/offline agent returns a clear failure.
- Relay polling returns only messages for that relay's machine.
- Fake relay injection updates status to `injected`.
- `paste_only` does not request submit.
- `auto_submit` requests submit.
- No automated test invokes real tmux injection.
