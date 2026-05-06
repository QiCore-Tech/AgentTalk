# M5-M6 Contract Checklist

Date: 2026-05-07

## Scope

M5 and M6 implement Web Agents Console, Agent detail, Context overview, structured Web messaging, and live terminal.

## Web UI

Required pages:

- Agents home: table plus side preview.
- Agent detail: metadata, structured message box, recent messages, live terminal.
- Context overview: recent output for registered agents.

Required UX:

- Dense table suitable for many agents.
- Status badges for `offline`, `online`, `active`, `working`, `stale`.
- Clear separation between structured AgentTalk messages and direct live terminal input.
- Good responsive behavior for desktop and narrower screens.

## API/WebSocket

- Web terminal connects through a Hub WebSocket.
- Relay can poll terminal sessions and proxy output/input.
- Playwright tests may use mocked API responses for UI rendering.
- Real tmux terminal e2e may only use `agenttalk-e2e-*` sessions.

## Acceptance

- Web UI renders Agents table and preview.
- Web UI sends a structured message through API.
- Agent detail renders live terminal area.
- Context overview renders multiple agent context blocks.
- Playwright covers core navigation and UI behavior.
