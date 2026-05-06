# AgentTalk UX and Architecture Design

Date: 2026-05-07

## Purpose

AgentTalk is a lightweight LAN tool for AI agent CLI collaboration. Developers continue running Claude, Codex, Gemini, or other agent CLIs in tmux. AgentTalk provides discovery, registration, point-to-point messaging, response monitoring, recent context viewing, and Web-based terminal access.

The first version optimizes for team development inside a trusted LAN. It should remain small and avoid becoming a general agent orchestration platform.

## Core Architecture

```text
Agent CLI in tmux
  <-> local agenttalkd relay
  <-> fixed LAN Hub
  <-> CLI / Web UI / other relays
```

### Hub

The Hub is a fixed LAN service. It stores registered agents, tracks relay presence, routes messages, exposes APIs, and serves the Web UI.

### Local Relay

Each developer machine runs a lightweight `agenttalkd` process. It connects to the Hub and performs local tmux operations:

- discover candidate agent panes
- register and update local agent panes
- maintain heartbeat
- inject messages into tmux panes
- capture recent pane output
- stream terminal output for the Web UI
- forward Web terminal input into tmux

### CLI

The `agenttalk` CLI is the primary operational interface for setup, registration, listing agents, sending messages, watching feedback, and reading context.

Agent skills or local agent instructions can call the CLI when an agent wants to communicate with another registered agent.

## Registration Model

The first version supports tmux-hosted agents only.

One tmux pane maps to one registered agent. A single user can register multiple agents.

Agent IDs are user-defined short IDs and globally unique in the Hub. Recommended style:

```text
<person>-<agent-kind>-<purpose>
```

Examples:

```text
alice-claude-soha
alice-codex-agenttalk
bob-codex-api
```

The local relay may automatically discover candidate panes, but candidate panes do not become trusted communication targets until registration.

## CLI UX

### First-Time Setup

Primary entry:

```bash
agenttalk setup http://hub.local:8787
```

Expected flow:

```text
Connected to Hub: http://hub.local:8787
Machine: alice-mbp

Found possible agent panes:

[1] claude   dev:0.1   /workspace/soha_pilot-v2
[2] codex    dev:0.2   /workspace/soha_agentTalk
[3] gemini   api:1.0   /workspace/service-api

Select panes to register: 1,2
```

Then each selected pane receives a short ID and receive mode:

```text
Pane [1] claude /workspace/soha_pilot-v2
Short id: alice-claude-soha
Receive mode: auto_submit

Pane [2] codex /workspace/soha_agentTalk
Short id: alice-codex-agenttalk
Receive mode: auto_submit
```

Completion:

```text
Registered:
- alice-claude-soha        online
- alice-codex-agenttalk    online

agenttalkd is running.
```

Supporting commands:

```bash
agenttalk discover
agenttalk register
agenttalk rename alice-claude-soha alice-claude-main
agenttalk mode alice-claude-main paste-only
agenttalk list --mine
```

### Listing Agents

```bash
agenttalk list
```

Example:

```text
short id                 kind     owner   workspace                 status
alice-claude-soha        claude   alice   /workspace/soha_pilot-v2  online
alice-codex-agenttalk    codex    alice   /workspace/soha_agentTalk active
bob-codex-api            codex    bob     /workspace/service-api    working
```

### Point-to-Point Messaging

Messages are sent to one explicit target agent short ID.

```bash
agenttalk send --to bob-codex-api --message "请检查接口契约"
```

Send and watch:

```bash
agenttalk send --to bob-codex-api --message "请检查接口契约" --watch
```

Expected status output:

```text
message: msg-0018
to: bob-codex-api

[sent]       Hub accepted
[delivered]  target relay accepted
[injected]   written to tmux pane
[working]    target pane produced output

--- response delta ---
发现两个问题：
1. ...
2. ...

[completed] marker detected
```

### Injected Message Format

Target panes receive a structured prompt:

```text
[AgentTalk Message]
message_id: msg-0018
from: alice-claude-soha
to: bob-codex-api

Task:
请检查接口契约。

When done, print this exact marker on its own line:
<<<AGENTTALK_DONE:msg-0018>>>
```

Registered agents default to `auto_submit`, so the relay injects and submits the message. A user may configure an agent as `paste_only`.

### Response Monitoring

Feedback monitoring uses:

- a unique completion marker
- tmux output deltas after injection

The marker is the completion signal when the target agent follows instructions. Output deltas provide live feedback before completion.

### Recent Context Reading

```bash
agenttalk context bob-codex-api --lines 120
```

This reads recent tmux pane output only. It does not include full terminal recording, filesystem access, shell command execution, or model-internal context.

Recent context reading is allowed by default for registered agents in the LAN deployment.

## Web UI UX

The Web UI is an Agent Console. It supports monitoring, direct structured messaging, recent context viewing, and live tmux terminal access.

### Agents Home

The home page uses a table plus side preview layout.

```text
---------------------------------------------------------
Agents                                      Filters/Search
---------------------------------------------------------
short id          owner   kind   workspace     status
alice-claude-api  alice   claude api           online
bob-codex-ui      bob     codex  frontend      working
carol-gemini-db   carol   gemini database      offline
---------------------------------------------------------
Right Preview
- selected agent metadata
- recent context excerpt
- quick AgentTalk message box
- View Terminal button
---------------------------------------------------------
```

The table is optimized for scanning many agents. It should support search and filters for owner, kind, status, and workspace.

### Agent Detail

The detail page is an operation console for one agent.

```text
Agent Detail: bob-codex-api
------------------------------------------------
Status: online / working
Owner: bob
Kind: codex
Workspace: /workspace/service-api
Receive mode: auto_submit
Last web input: alice at 14:32

AgentTalk Message
[ message textarea                          ]
[ Send ] [ Send & Watch ]

Live Terminal
[ full interactive tmux terminal             ]

Recent Messages
msg-0018  completed
msg-0019  timeout
```

The page has two separate interaction modes:

1. AgentTalk structured messages
2. Live Terminal direct input

Structured messages create message IDs, delivery status, response monitoring, and completion markers.

Live Terminal input directly controls the tmux pane and does not automatically create tracked messages.

### Live Terminal

The Web UI should support a full interactive tmux terminal.

```text
browser terminal
  <-> Hub WebSocket
  <-> target relay
  <-> tmux pane
```

The first version does not enforce a terminal input lock. If multiple browsers can input to the same terminal, the UI should display the most recent Web terminal input actor.

### Context Overview

The Context page shows recent output for all registered agents.

```text
alice-claude-api
recent tmux output...

bob-codex-ui
recent tmux output...
```

It should support filters for owner, kind, and online status.

## Agent Status

First-version states:

- `offline`: relay disconnected or pane missing
- `online`: relay connected and pane exists
- `active`: pane produced output recently
- `working`: a tracked message is pending completion marker
- `stale`: pane is online but has had no output for a long period

## First-Version Non-Goals

The first version should avoid:

- full terminal recording
- complex permission systems
- cross-internet access
- agent task orchestration
- channel or group chat semantics

## Open Implementation Details

These should be decided during implementation planning:

- Hub framework and storage
- relay transport protocol
- tmux discovery heuristics
- terminal stream implementation details
- message timeout defaults
- status timing thresholds
- shared LAN token handling

## Confirmed Technology Stack

- Hub: Python FastAPI
- Hub storage: SQLite
- CLI and local relay: Python
- Web UI: React + Vite
- Web terminal: xterm.js
