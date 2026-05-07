# AgentTalk Design Decisions

Date: 2026-05-07

## Goal

Build a lightweight LAN tool that lets developers' local AI agent CLIs communicate with each other during collaborative development.

The system should help agents discover peers, send messages to a named target agent, and inject incoming messages into the target agent's existing terminal UI. It should stay small and avoid becoming a full agent orchestration platform.

## Confirmed Decisions

1. First version supports tmux-hosted agent CLIs only.

2. The deployment uses one fixed LAN Hub. Each developer machine connects to that Hub.

3. The target machine needs a local lightweight daemon or relay. The Hub does not directly control remote tmux panes.

4. The local daemon is intentionally thin. It should:
   - connect to the Hub
   - register local agent panes
   - maintain heartbeat
   - receive routed messages
   - inject messages into local tmux panes

5. The user-facing CLI is separate from the daemon. The CLI should support operations such as listing agents, sending messages, and registering or renaming local panes.

6. Agent skills or local agent instructions can call the CLI when an agent wants to communicate with another agent.

7. Agent discovery should minimize manual setup. The local daemon may scan tmux panes and report candidate agent panes.

8. Candidate panes should not automatically become trusted communication targets without a lightweight confirmation or registration step.

9. Registered agents use user-defined short IDs, such as `alice-claude-main`.

10. Agent short IDs are globally unique in the Hub. The recommended naming style is `<person>-<agent-kind>-<purpose>`, such as `alice-codex-api`, but the format is not enforced.

11. One tmux pane maps to one registered agent. A single user can register multiple agents.

12. Registration should support selecting and registering multiple discovered panes in one flow.

13. The first version uses point-to-point messaging. A message is sent to one explicit target agent short ID.

14. Sending a message should provide observable feedback, including delivery status and a way to monitor whether the target agent has responded.

15. Reading another agent's recent terminal output is allowed by default for registered agents in the LAN deployment.

16. Context reading means recent tmux pane output only. It does not include full terminal recording, filesystem access, shell command execution, or model-internal context.

17. Feedback monitoring uses a unique completion marker plus tmux output deltas. The marker indicates completion when the target agent follows the injected instruction; output deltas provide live feedback even before completion.

18. Registered agents default to automatic submission on received messages. A user can configure an agent as paste-only during registration or later update.

19. The first version user experience is limited to three primary flows:
    - first-time setup and multi-agent registration
    - point-to-point send with delivery and response monitoring
    - recent context reading for a registered agent

20. The first version UX baseline is confirmed around CLI-first operation with Web UI support.

21. The Web UI should support:
    - monitoring registered agent status
    - opening an agent detail view
    - directly interacting with an agent from the detail view
    - viewing recent context for all registered agents
    - viewing recent message status

22. Web UI sends messages with the same receive behavior as CLI sends. Registered agents default to automatic submission unless configured as paste-only.

23. The Web UI should include a live terminal view for an agent's tmux pane and support direct keyboard input to that pane.

24. The first version does not enforce a terminal input lock. The Web UI should display the most recent Web terminal input actor for awareness.

25. AgentTalk structured messages and live terminal input are separate interaction modes. Structured messages keep message IDs, delivery status, response monitoring, and completion markers. Live terminal input is direct tmux control and does not automatically create tracked messages.

26. The Web UI home page uses a table plus side preview layout. The table is optimized for scanning many registered agents. Selecting an agent opens a side preview with recent context and quick actions; opening the detail page shows the full interactive terminal.

27. Agent status uses these first-version states:
    - `offline`: relay disconnected or pane missing
    - `online`: relay connected and pane exists
    - `active`: pane produced output recently
    - `working`: a tracked message is pending completion marker
    - `stale`: pane is online but has had no output for a long period

28. The first-version technology stack is:
    - Hub: Python FastAPI
    - Hub storage: SQLite
    - CLI and local relay: Python
    - Web UI: React + Vite
    - Web terminal: xterm.js

29. Feishu integration should use Feishu long-connection mode instead of a public callback URL.

30. Feishu integration should be started by `agenttalk hub serve`, not a separate user-facing service command.

31. Feishu bot UX should support both text commands and interactive cards.

32. First Feishu access policy is permissive for the installed bot context: users/chats that can talk to the bot can query and operate AgentTalk. The system should record the Feishu operator ID, but not enforce a complex permission model in the first version.

33. Feishu should reuse AgentTalk Hub capabilities rather than directly controlling tmux:
    - list agents
    - view agent detail
    - read recent context
    - send point-to-point messages
    - query message status
    - read message response

34. Feishu should not expose full terminal control in the first version.

35. The first version should avoid heavyweight features:
    - no full terminal recording
    - no complex permission system
    - no cross-internet access
    - no agent task orchestration
    - no complex group chat semantics unless later required

## Working Architecture

```text
Agent CLI in tmux
  <-> local agenttalkd relay
  <-> fixed LAN Hub
  <-> other local relays and Web UI
```

Agents can actively send messages through:

```text
agent skill / agent instruction
  -> agenttalk CLI
  -> Hub
  -> target machine relay
  -> target tmux pane
```

## Open Discussion Direction

Next, define the user experience flow before choosing final implementation details.

The most important flows to design are:

1. First-time setup by a developer.
2. Discovering and registering local agent panes.
3. Finding another developer's agent.
4. Sending a message from one agent to another.
5. Receiving a message inside an agent CLI.
6. Monitoring online agents from the Web UI.
