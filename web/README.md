# AgentTalk Web Console

The Web console shows registered agents, recent terminal context, message status, settings, and a built-in Guide page.

## Guide Content

The in-app Guide documents:

- Hub setup and agent registration.
- `agenttalk daemon install/status/restart/stop`.
- Reliable delivery states: `sent -> delivered -> submitted -> acked -> completed`.
- `AGENTTALK_ACK:<message-id>` acknowledgement.
- Local dead-letter handling: `agenttalk dlq list/retry/fail`.
- Feishu inspection commands: `/status`, `/response`, `/trace`, `/guide reliability`.

Local relay commands must be run on the target developer machine. The Web console and Feishu bot inspect Hub-visible state; they do not directly control another machine's local daemon.
