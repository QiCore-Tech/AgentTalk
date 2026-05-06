---
name: agenttalk
description: Use when an AI agent needs to communicate with another registered LAN agent through AgentTalk, inspect another agent's recent tmux context, monitor peer agent status, or route a task/review request to a specific agent short ID.
---

# AgentTalk

AgentTalk lets tmux-hosted agent CLIs communicate through a LAN Hub. Use it when collaboration with another registered agent would help: review requests, interface checks, status handoffs, cross-agent debugging, or asking a peer agent to inspect a specific artifact.

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

## Inspect Context

Before interrupting another agent, inspect recent output:

```bash
agenttalk context alice-codex-api --lines 120
```

Use this to decide whether the target is online, busy, or already working on related context.

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
2. Answer in the same terminal.
3. When done, print the exact completion marker included in the message on its own line.

Do not invent a marker. Use the marker from the received message exactly.

## Failure Handling

- If `agenttalk list` cannot reach the Hub, report that AgentTalk is unavailable.
- If the target is missing or offline, report the target short ID and ask for a valid target.
- If `--watch` times out but partial output exists, summarize the partial output and state that completion was not observed.
