# Agent Instructions

This repository ships an AgentTalk skill for AI agents.

Before using AgentTalk from this repo, read:

```text
.agents/skills/agenttalk/SKILL.md
```

Use that skill when you need to:

- list registered LAN agents;
- inspect a peer agent's recent tmux context;
- send a tracked point-to-point AgentTalk message;
- watch delivery, output deltas, and completion markers;
- explain or use the Feishu AgentTalk bot commands.

Do not send input to arbitrary tmux panes. Only use AgentTalk commands or registered panes that are explicitly intended to receive AgentTalk input.

For tmux tests, only use sessions named:

```text
agenttalk-e2e-*
```

Do not touch existing development panes.
