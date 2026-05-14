# Agent Skill Usage

Date: 2026-05-07

AgentTalk includes a repository-local skill so AI agents can learn how to use the tool from the repo itself.

## Location

```text
.agents/skills/agenttalk/SKILL.md
```

## Repository Entry Point

`AGENTS.md` points agents to the skill when they enter the repository.

Agents that support repository instructions should read `AGENTS.md` automatically or when prompted. Agents that support skills can load the skill directly from `.agents/skills/agenttalk/SKILL.md`.

## Optional Local Install

If your agent CLI only discovers skills from a user-level directory, copy or symlink the repository skill into that directory.

Example for Codex-style local skills:

```bash
mkdir -p ~/.codex/skills
ln -s "$(pwd)/.agents/skills/agenttalk" ~/.codex/skills/agenttalk
```

Example for `.agents`-style local skills:

```bash
mkdir -p ~/.agents/skills
ln -s "$(pwd)/.agents/skills/agenttalk" ~/.agents/skills/agenttalk
```

Use a copy instead of a symlink if your environment does not allow symlinks.

## Receiving Messages

When an AgentTalk message arrives, the agent should:

- read the inbox file first when the prompt says `Full task is stored at ...`
- print `AGENTTALK_ACK:<message-id>` once when requested
- continue the task immediately after ACK
- print the exact done marker only after the task is complete

Agents should not edit `~/.agenttalk/delivery/` or run separate ACK scripts
unless a specific task explicitly asks for that. Delivery tickets are owned by
the local relay daemon; they are used to recover messages that remain in the
terminal input box.

If status becomes `submit_unconfirmed`, inspect:

```bash
agenttalk context <agent-id> --lines 120
agenttalk dlq list
```

## Agent Quick Check

After loading the skill, an agent should be able to explain these commands:

```bash
agenttalk list
agenttalk context <agent-id> --lines 120
agenttalk send --to <agent-id> --message "<task>" --watch
agenttalk status <message-id>
agenttalk response <message-id>
```

Feishu equivalents:

```text
/agents
/context <agent-id>
/send <agent-id> <message>
/status <message-id>
/response <message-id>
```
