# AgentTalk MVP Implementation Plan

Date: 2026-05-07

## Inputs

- Design decisions: `docs/plans/2026-05-07-agenttalk-design-decisions.md`
- UX and architecture design: `docs/plans/2026-05-07-agenttalk-ux-architecture-design.md`

## Tier

Medium.

Rationale:

- Multiple processes: Hub, relay, CLI, Web UI.
- API and WebSocket contracts are required.
- tmux integration needs real end-to-end checks.
- The MVP is still small enough to avoid large-project ceremony.

## Confirmed Stack

- Hub: Python FastAPI
- Hub storage: SQLite
- CLI and local relay: Python
- Web UI: React + Vite
- Web terminal: xterm.js

## Milestones

## Progress

| Milestone | Status | Commit | Notes |
|---|---|---|---|
| M1: Project Skeleton and Hub Registry | Done | `4d868de` | Hub registry, SQLite store, token auth, minimal CLI, tests, and AgentTalk skill file. |
| M2: Local Relay Discovery and Registration | Done | `85e3e79` | Read-only tmux discovery, local config, relay one-shot sync, CLI setup/register/discover/list --mine/daemon start, fake-tmux tests. |
| M3: Point-to-Point Send and Injection | Pending |  |  |
| M4: Watch Feedback and Context Reading | Pending |  |  |
| M5: Web Agents Console | Pending |  |  |
| M6: Web Live Terminal and Context Overview | Pending |  |  |

### M1: Project Skeleton and Hub Registry

Goal: Run a Hub service and register/list agents through HTTP.

Tasks:

1. Create Python package skeleton for `agenttalk`.
2. Add FastAPI Hub app.
3. Add SQLite persistence for machines, relays, agents, and heartbeat timestamps.
4. Add shared LAN token middleware.
5. Add registry endpoints:
   - register relay
   - heartbeat
   - upsert agent
   - list agents
   - get agent detail
6. Add minimal CLI commands:
   - `agenttalk hub serve`
   - `agenttalk list`
7. Add unit tests for registry behavior.

Acceptance:

- Hub starts locally.
- A test client can register a relay and two agents.
- `agenttalk list` prints registered agents.
- Offline state is derived when heartbeat is stale.

### M2: Local Relay Discovery and Registration

Goal: Run `agenttalkd`, discover tmux panes, and register multiple local agents.

Tasks:

1. Add tmux command wrapper.
2. Implement tmux pane discovery using `tmux list-panes`.
3. Add basic agent kind detection from pane command/title.
4. Add local config storage for Hub URL, token, machine identity, and registered pane bindings.
5. Add CLI setup flow:
   - `agenttalk setup <hub-url>`
   - discover panes
   - multi-select panes
   - assign globally unique short IDs
   - choose receive mode
6. Add relay process:
   - connect to Hub
   - register machine/relay
   - upsert registered agents
   - heartbeat loop
7. Add CLI commands:
   - `agenttalk discover`
   - `agenttalk register`
   - `agenttalk list --mine`
   - `agenttalk rename`
   - `agenttalk mode`
8. Add tests with tmux wrapper fakes.

Acceptance:

- A user can register multiple panes in one setup flow.
- Registered agents appear in Hub list.
- Pane missing changes agent state to offline or unavailable.

### M3: Point-to-Point Send and Injection

Goal: Send a structured message to a target agent and inject it into the target tmux pane.

Tasks:

1. Add message persistence and status transitions:
   - sent
   - delivered
   - injected
   - working
   - completed
   - timeout
   - failed
2. Add Hub message endpoints:
   - create message
   - get message status
   - get message response delta
3. Add relay WebSocket control channel from relay to Hub.
4. Route outbound messages from Hub to target relay.
5. Inject structured message into target tmux pane with message ID and done marker.
6. Honor receive mode:
   - `auto_submit`
   - `paste_only`
7. Add CLI:
   - `agenttalk send --to <id> --message <text>`
   - `agenttalk status <message-id>`
8. Add tests for routing and status transitions.

Acceptance:

- Message to an online registered agent reaches target relay.
- Target relay writes the message into the correct tmux pane.
- Status reaches `injected`.
- Missing target agent produces a clear failed status.

### M4: Watch Feedback and Context Reading

Goal: Monitor output deltas and completion markers, and read recent context.

Tasks:

1. Capture tmux pane output before injection.
2. Stream or poll post-injection output deltas.
3. Detect `<<<AGENTTALK_DONE:<message-id>>>`.
4. Update message status to `working`, `completed`, or `timeout`.
5. Store bounded response delta snippets.
6. Add CLI:
   - `agenttalk send --watch`
   - `agenttalk response <message-id>`
   - `agenttalk context <agent-id> --lines <n>`
7. Add Hub endpoints for recent context.
8. Add tests for marker detection and timeout behavior.

Acceptance:

- `send --watch` displays status changes and response deltas.
- Done marker completes the message.
- Timeout preserves captured output.
- `context` returns recent tmux output for a registered agent.

### M5: Web Agents Console

Goal: Provide the Web UI home page and agent detail structured messaging.

Tasks:

1. Create React + Vite frontend.
2. Add API client for agents, context, and messages.
3. Build Agents home:
   - table
   - search/filter
   - side preview
   - recent context excerpt
   - quick message box
4. Build Agent detail metadata panel.
5. Add structured AgentTalk message box:
   - Send
   - Send & Watch
   - status stream
6. Add recent messages panel.
7. Add basic visual states for offline, online, active, working, stale.
8. Add frontend tests for core state rendering where practical.

Acceptance:

- Web UI lists registered agents.
- Selecting an agent shows preview and context.
- Web can send a structured message with the same behavior as CLI.
- Message status is visible in the UI.

### M6: Web Live Terminal and Context Overview

Goal: Add full interactive tmux terminal access and global context overview.

Tasks:

1. Add terminal stream WebSocket:
   - browser to Hub
   - Hub to target relay
   - relay to tmux pane
2. Add xterm.js terminal component.
3. Stream tmux pane output into the terminal view.
4. Forward browser keyboard input to target tmux pane.
5. Display most recent Web terminal input actor.
6. Add Context overview page:
   - all registered agents
   - recent output snippets
   - owner/kind/status filters
7. Add end-to-end manual test script for live terminal.

Acceptance:

- Agent detail shows an interactive terminal for the target pane.
- Typing in the Web terminal writes to tmux.
- Terminal output updates in the browser.
- Recent input actor is visible.
- Context overview shows recent output for all registered agents.

## Cross-Cutting Contracts

These contracts must be specified before implementation:

1. HTTP API schemas.
2. Relay WebSocket control messages.
3. Web terminal WebSocket messages.
4. Message status state machine.
5. Agent status derivation rules.
6. Local config file shape.

## Suggested Execution Order

1. Write API and WebSocket contract notes.
2. Implement M1.
3. Implement M2.
4. Run a local two-pane tmux smoke test.
5. Implement M3.
6. Implement M4.
7. Build M5.
8. Build M6.
9. Run full LAN-style smoke test on one machine with multiple tmux panes.

## Manual Smoke Tests

### Two-Agent Local Test

1. Start Hub.
2. Open two tmux panes.
3. Start two different agent CLIs or shell placeholders.
4. Register both panes.
5. Send a message from one registered ID to another.
6. Confirm injection.
7. Confirm `--watch` receives output and marker.

### Web Terminal Test

1. Open Agent detail page.
2. Confirm terminal output appears.
3. Type into Web terminal.
4. Confirm tmux pane receives input.
5. Confirm recent input actor updates.

## Out of Scope for MVP

- Multi-user permission model beyond shared LAN token.
- Channels, rooms, or group chat.
- Full historical terminal recording.
- Remote shell command execution APIs.
- Non-tmux terminal support.
- Cross-internet deployment.
