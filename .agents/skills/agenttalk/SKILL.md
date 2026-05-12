---
name: agenttalk
description: Use when an AI agent needs to communicate with another registered LAN agent through AgentTalk, inspect another agent's recent tmux context, monitor peer agent status, route a task/review request to a specific agent short ID, or explain/use the optional Feishu AgentTalk bot commands.
---

# AgentTalk

AgentTalk lets tmux-hosted agent CLIs communicate through a LAN Hub. Use it when collaboration with another registered agent would help: review requests, interface checks, status handoffs, cross-agent debugging, or asking a peer agent to inspect a specific artifact.

AgentTalk may also be exposed through a Feishu bot. The Feishu bot is for humans or agents operating through chat; the CLI remains the preferred path when this terminal can run commands.

## Core Rules

- Prefer structured AgentTalk messages over raw terminal control.
- Always target a registered agent short ID, not a person name.
- Use `--watch` when you need feedback in the current turn.
- Read recent context before sending if the target may already be busy.
- Do not use AgentTalk to send secrets or private credentials.
- Do not control tmux panes directly unless the user explicitly asks.

## Discover Peers

List registered agents:

```bash
agenttalk list
```

If available, narrow the list:

```bash
agenttalk list --owner alice
```

Pick a target by `short id`, such as `alice-codex-api`.

Feishu equivalent:

```text
/agents
/agents online
```

## Inspect Context

Before interrupting another agent, inspect recent output:

```bash
agenttalk context alice-codex-api --lines 120
```

Use this to decide whether the target is online, busy, or already working on related context.

Feishu equivalent:

```text
/context alice-codex-api
```

## Send a Request

For normal peer collaboration:

```bash
agenttalk send --to alice-codex-api --message "Please review the API contract in docs/plans/example.md."
```

For feedback you need to observe immediately:

```bash
agenttalk send --to alice-codex-api --message "Please review the API contract in docs/plans/example.md." --watch
```

`--watch` should display delivery status, output deltas, and completion when the target prints the AgentTalk marker.

Feishu equivalents:

```text
/send alice-codex-api Please review the API contract in docs/plans/example.md.
/status msg-xxx
/response msg-xxx
```

Use Feishu when the user is working in Feishu chat, asks for bot commands, or cannot run the local `agenttalk` CLI from the current environment.

## Feishu Bot Commands

Supported first-version commands:

```text
/help
/agents
/agents online
/agent <agent-id>
/context <agent-id>
/send <agent-id> <message>
/status <message-id>
/response <message-id>
```

When answering a user about Feishu setup or operation, direct them to:

```text
docs/guides/feishu-bot-setup.md
docs/guides/docker-deployment.md
```

## Message Shape

Write messages as clear tasks:

```text
Please inspect <file/path or topic>.
Focus on <specific risks>.
Return findings first, then a short summary.
```

Include exact file paths, commands, or contract names when relevant. Keep the request bounded.

## When Receiving AgentTalk Messages

If an AgentTalk message appears in this terminal:

1. Treat it as a direct task from the sender.
2. If the prompt says the full task is stored in a local file, read that file before answering.
3. If the prompt asks for an `AGENTTALK_ACK:<message-id>` line, include that line once at the start of your actual response.
4. Do not stop after the ACK line. Continue with the requested task immediately.
5. Answer in the same terminal.
6. When done, print the exact completion marker included in the message on its own line.

Do not invent a marker. Use the marker from the received message exactly.

## Failure Handling

- If `agenttalk list` cannot reach the Hub, report that AgentTalk is unavailable.
- If the target is missing or offline, report the target short ID and ask for a valid target.
- If `--watch` times out but partial output exists, summarize the partial output and state that completion was not observed.
