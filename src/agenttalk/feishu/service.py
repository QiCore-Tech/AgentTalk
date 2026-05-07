from __future__ import annotations

from dataclasses import dataclass

from agenttalk.feishu.commands import FeishuCommand, FeishuCommandKind
from agenttalk.feishu.render import (
    FeishuReply,
    agent_detail_card,
    agents_card,
    help_reply,
    message_status_text,
    text_reply,
    truncate,
)
from agenttalk.hub.models import AgentStatus, MessageCreateRequest
from agenttalk.hub.store import AgentFilters, HubStore


@dataclass(frozen=True)
class FeishuOperator:
    open_id: str = ""
    chat_id: str = ""


class FeishuAgentTalkService:
    def __init__(self, store: HubStore, *, web_base_url: str = "") -> None:
        self.store = store
        self.web_base_url = web_base_url

    def handle(self, command: FeishuCommand, operator: FeishuOperator) -> FeishuReply:
        if command.error:
            return text_reply(command.error)
        match command.kind:
            case FeishuCommandKind.HELP:
                return help_reply()
            case FeishuCommandKind.AGENTS:
                status = AgentStatus.ONLINE if command.args and command.args[0].lower() == "online" else None
                return agents_card(self.store.list_agents(AgentFilters(status=status)), web_base_url=self.web_base_url)
            case FeishuCommandKind.AGENT:
                agent_id = command.args[0]
                agent = self.store.get_agent(agent_id)
                if agent is None:
                    return text_reply(f"Agent not found: {agent_id}")
                context = self.store.get_agent_context(agent_id)
                return agent_detail_card(agent, context=context.context if context else "", web_base_url=self.web_base_url)
            case FeishuCommandKind.CONTEXT:
                agent_id = command.args[0]
                context = self.store.get_agent_context(agent_id)
                if context is None:
                    return text_reply(f"Agent not found: {agent_id}")
                return text_reply(truncate(context.context or "No context captured.", 4000))
            case FeishuCommandKind.SEND:
                target, body = command.args
                sender = f"feishu:{operator.open_id or operator.chat_id or 'unknown'}"
                message, error = self.store.create_message(MessageCreateRequest(to=target, body=body, sender=sender))
                if error == "target_not_found":
                    return text_reply(f"Target agent not found: {target}")
                if error == "target_offline":
                    return text_reply(f"Target agent is offline: {target}")
                assert message is not None
                return text_reply(
                    "\n".join(
                        [
                            "Message created.",
                            f"message: {message.message_id}",
                            f"target: {message.target}",
                            f"status: {message.status}",
                        ]
                    )
                )
            case FeishuCommandKind.STATUS:
                message_id = command.args[0]
                message = self.store.get_message(message_id)
                if message is None:
                    return text_reply(f"Message not found: {message_id}")
                return message_status_text(message)
            case FeishuCommandKind.RESPONSE:
                message_id = command.args[0]
                response = self.store.get_message_response(message_id)
                if response is None:
                    return text_reply(f"Message not found: {message_id}")
                return text_reply(truncate(response.response_text or "No response captured.", 4000))
            case FeishuCommandKind.UNKNOWN:
                return help_reply()
            case _:
                return help_reply()

    def send_alert(self, messenger, short_id: str, alert_type: str, message: str, owner: str = "", chat_id: str = "") -> None:
        from agenttalk.feishu.render import alert_card
        reply = alert_card(short_id, alert_type, message, web_base_url=self.web_base_url, owner=owner)
        if chat_id:
            messenger.send_to_chat(chat_id, reply)
        else:
            # Fallback: try to send without specific chat (may fail silently)
            try:
                messenger.send_reply("", reply, receive_id_type="chat_id")
            except Exception:
                pass
