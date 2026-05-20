from __future__ import annotations

from dataclasses import dataclass

from agenttalk.feishu.commands import FeishuCommand, FeishuCommandKind
from agenttalk.feishu.render import (
    FeishuReply,
    agent_detail_card,
    agents_card,
    help_reply,
    machines_card,
    message_trace_text,
    message_status_text,
    reliability_guide_text,
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
        
        # Determine if this is a group chat (群机器人) or personal chat (个人机器人)
        is_group_chat = bool(operator.chat_id and not operator.open_id)
        
        match command.kind:
            case FeishuCommandKind.HELP:
                return help_reply()
            case FeishuCommandKind.AGENTS:
                agents = self.store.list_agents(AgentFilters())
                if command.args and command.args[0].lower() == "online":
                    agents = [agent for agent in agents if agent.status != AgentStatus.OFFLINE]
                return agents_card(agents, web_base_url=self.web_base_url)
            case FeishuCommandKind.MACHINES:
                machines = self.store.list_machines()
                if is_group_chat:
                    # Group bot can only see public machines
                    machines = [m for m in machines if m.get("visibility") == "public"]
                return machines_card(machines, web_base_url=self.web_base_url)
            case FeishuCommandKind.REGISTER:
                if is_group_chat:
                    return text_reply("❌ 群机器人不支持注册 agent。请使用个人机器人或在 Web UI 中注册。")
                
                args = command.args
                short_id = args[0]
                machine_id = args[1]
                kind = args[2]
                workspace = args[3] if len(args) > 3 else ""
                tmux_target = args[4] if len(args) > 4 else machine_id
                receive_mode = args[5] if len(args) > 5 else "auto_submit"
                
                # Validate machine exists
                machine = self.store.get_relay(machine_id)
                if not machine:
                    return text_reply(f"❌ Machine not found: {machine_id}")
                
                # Check if agent already exists
                existing = self.store.get_agent(short_id)
                if existing:
                    return text_reply(f"❌ Agent already exists: {short_id}")
                
                # Create instruction for relay to register agent
                instruction = self.store.create_instruction(
                    machine_id=machine_id,
                    type="register_agent",
                    payload={
                        "short_id": short_id,
                        "kind": kind,
                        "workspace": workspace,
                        "tmux_target": tmux_target,
                        "receive_mode": receive_mode,
                    },
                )
                return text_reply(
                    f"✅ Agent 注册指令已下发\n"
                    f"Short ID: {short_id}\n"
                    f"Machine: {machine_id}\n"
                    f"Kind: {kind}\n"
                    f"Instruction ID: {instruction['id']}\n"
                    f"\nRelay 将在下次同步时处理该指令。"
                )
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
                context = self.store.get_agent_context(target)
                context_preview = truncate(context.context or "No terminal context captured.", 2000) if context else "No terminal context captured."
                return text_reply(
                    "\n".join(
                        [
                            "Message created.",
                            f"message: {message.message_id}",
                            f"target: {message.target}",
                            f"status: {message.status}",
                            "",
                            "Terminal context preview:",
                            "```",
                            context_preview,
                            "```",
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
            case FeishuCommandKind.TRACE:
                message_id = command.args[0]
                message = self.store.get_message(message_id)
                if message is None:
                    return text_reply(f"Message not found: {message_id}")
                response = self.store.get_message_response(message_id)
                return message_trace_text(message, response.response_text if response else "")
            case FeishuCommandKind.GUIDE:
                topic = command.args[0].lower() if command.args else ""
                if topic in {"", "reliability", "delivery"}:
                    return reliability_guide_text()
                return help_reply()
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
