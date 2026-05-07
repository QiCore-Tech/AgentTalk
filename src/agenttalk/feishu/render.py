from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from agenttalk.hub.models import AgentResponse, MessageResponse


def truncate(value: str, limit: int = 4000) -> str:
    if len(value) <= limit:
        return value
    return value[: max(limit - 20, 0)].rstrip() + "\n...(truncated)"


@dataclass(frozen=True)
class FeishuReply:
    msg_type: str
    content: str | dict[str, Any]


def text_reply(text: str) -> FeishuReply:
    return FeishuReply("text", truncate(text))


def help_reply() -> FeishuReply:
    return text_reply(
        "\n".join(
            [
                "AgentTalk commands:",
                "/agents",
                "/agents online",
                "/agent <agent-id>",
                "/context <agent-id>",
                "/send <agent-id> <message>",
                "/status <message-id>",
                "/response <message-id>",
            ]
        )
    )


def agents_card(agents: list[AgentResponse], *, web_base_url: str = "") -> FeishuReply:
    rows = []
    for agent in agents[:20]:
        rows.append(
            {
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": (
                        f"**{agent.short_id}** · `{agent.status}`\n"
                        f"{agent.kind} · {agent.owner} · {truncate(agent.workspace, 120)}"
                    ),
                },
            }
        )
    if not rows:
        rows.append({"tag": "div", "text": {"tag": "plain_text", "content": "No agents registered."}})
    actions: list[dict[str, Any]] = []
    if web_base_url:
        actions.append(
            {
                "tag": "button",
                "text": {"tag": "plain_text", "content": "Open Web"},
                "type": "primary",
                "url": web_base_url,
            }
        )
    elements = rows
    if actions:
        elements.append({"tag": "action", "actions": actions})
    return FeishuReply(
        "interactive",
        {
            "config": {"wide_screen_mode": True},
            "header": {"title": {"tag": "plain_text", "content": "AgentTalk Agents"}},
            "elements": elements,
        },
    )


def agent_detail_card(agent: AgentResponse, *, context: str = "", web_base_url: str = "") -> FeishuReply:
    fields = [
        f"**Status:** `{agent.status}`",
        f"**Owner:** {agent.owner}",
        f"**Kind:** {agent.kind}",
        f"**Machine:** {agent.machine_id}",
        f"**Workspace:** `{truncate(agent.workspace, 160)}`",
        f"**Receive:** `{agent.receive_mode}`",
    ]
    elements: list[dict[str, Any]] = [
        {"tag": "div", "text": {"tag": "lark_md", "content": "\n".join(fields)}},
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": f"**Recent context:**\n```text\n{truncate(context or 'No context captured.', 1200)}\n```",
            },
        },
    ]
    actions: list[dict[str, Any]] = []
    if web_base_url:
        actions.append(
            {
                "tag": "button",
                "text": {"tag": "plain_text", "content": "Open Web"},
                "type": "primary",
                "url": f"{web_base_url.rstrip('/')}/",
            }
        )
    if actions:
        elements.append({"tag": "action", "actions": actions})
    return FeishuReply(
        "interactive",
        {
            "config": {"wide_screen_mode": True},
            "header": {"title": {"tag": "plain_text", "content": agent.short_id}},
            "elements": elements,
        },
    )


def message_status_text(message: MessageResponse) -> FeishuReply:
    lines = [
        f"message: {message.message_id}",
        f"target: {message.target}",
        f"status: {message.status}",
    ]
    if message.error:
        lines.append(f"error: {message.error}")
    return text_reply("\n".join(lines))
