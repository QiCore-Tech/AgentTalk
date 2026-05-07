from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
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
                "AgentTalk 飞书机器人使用指南：",
                "",
                "【查看 Agent 列表】",
                "/agents              # 列出所有已注册的 agent",
                "/agents online       # 仅列出在线的 agent",
                "",
                "【查看 Agent 详情】",
                "/agent <agent-id>    # 查看指定 agent 的详细信息",
                "/context <agent-id>  # 查看指定 agent 的最近上下文",
                "",
                "【向 Agent 发送消息】",
                "/send <agent-id> <消息内容>",
                "  例如：/send demo-agent-001 请检查接口契约",
                "  说明：消息会投递到 agent 所在的 tmux pane",
                "",
                "【查看消息状态】",
                "/status <message-id>  # 查看消息投递状态",
                "/response <message-id> # 查看 agent 的回复内容",
                "",
                "【Web 控制台】",
                "访问 Web UI 获取更完整的 agent 管理功能",
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


def alert_card(short_id: str, alert_type: str, message: str, *, web_base_url: str = "", owner: str = "") -> FeishuReply:
    color = "red" if alert_type in ("crashed", "error") else "orange"
    owner_line = f"\n**创建者:** {owner}" if owner else ""
    elements: list[dict[str, Any]] = [
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": f"**Agent:** `{short_id}`{owner_line}\n**类型:** {alert_type}\n**时间:** {datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S UTC')}",
            },
        },
        {
            "tag": "div",
            "text": {
                "tag": "lark_md",
                "content": f"**详情:**\n```\n{truncate(message, 800)}\n```",
            },
        },
    ]
    actions: list[dict[str, Any]] = []
    if web_base_url:
        actions.append(
            {
                "tag": "button",
                "text": {"tag": "plain_text", "content": "查看 Web 控制台"},
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
            "header": {
                "title": {"tag": "plain_text", "content": f"AgentTalk 告警: {short_id}"},
                "template": color,
            },
            "elements": elements,
        },
    )
