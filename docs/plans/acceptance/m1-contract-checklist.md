# M1 Contract Checklist

Date: 2026-05-07

Design inputs:

- `docs/plans/2026-05-07-agenttalk-design-decisions.md`
- `docs/plans/2026-05-07-agenttalk-ux-architecture-design.md`
- `docs/plans/2026-05-07-agenttalk-mvp-implementation-plan.md`

## Scope

M1 implements the Hub registry foundation and minimal CLI list behavior.

## HTTP API

| Endpoint | Method | Purpose | Key Checks |
|---|---:|---|---|
| `/health` | GET | Health probe | no token required, returns `{"status":"ok"}` |
| `/api/relays/register` | POST | Register or update relay identity | token required, validates `machine_id`, `host_name`, `user_name` |
| `/api/relays/heartbeat` | POST | Refresh relay heartbeat | token required, unknown relay returns 404 |
| `/api/agents` | PUT | Upsert agent registration | token required, `short_id` globally unique, receive mode enum checked |
| `/api/agents` | GET | List agents | token required, supports optional `owner`, `mine`, `status` filters when provided |
| `/api/agents/{short_id}` | GET | Agent detail | token required, missing agent returns 404 |

## Error Format

All API errors should use this shape:

```json
{
  "error": {
    "code": "string",
    "message": "string"
  }
}
```

## Token Rules

- `GET /health` does not require token.
- All `/api/*` routes require `Authorization: Bearer <token>`.
- Missing or invalid token returns 401.
- The token comes from Hub settings.

## SQLite Tables

| Table | Purpose | Required Constraints |
|---|---|---|
| `relays` | machine relay presence | `machine_id` primary key |
| `agents` | registered agent panes | `short_id` primary key, `machine_id` references relay |

## Enums

Agent status:

- `offline`
- `online`
- `active`
- `working`
- `stale`

Receive mode:

- `auto_submit`
- `paste_only`

## M1 Acceptance Checks

- Hub starts locally.
- Test client registers one relay and two agents.
- `GET /api/agents` returns both agents.
- `GET /api/agents/{short_id}` returns detail.
- Stale relay heartbeat derives `offline` for its agents.
- Missing token fails with 401.
- Minimal `agenttalk list` prints registered agents.
