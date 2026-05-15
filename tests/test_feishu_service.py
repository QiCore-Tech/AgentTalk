from __future__ import annotations

from pathlib import Path

from agenttalk.feishu.commands import parse_command
from agenttalk.feishu.service import FeishuAgentTalkService, FeishuOperator
from agenttalk.hub.models import (
    AgentContextUpdateRequest,
    AgentStatus,
    AgentUpsertRequest,
    MessageResponseUpdateRequest,
    ReceiveMode,
    RelayRegisterRequest,
)
from agenttalk.hub.store import HubStore


def make_store(tmp_path: Path) -> HubStore:
    store = HubStore(tmp_path / "hub.sqlite3")
    store.register_relay(RelayRegisterRequest(machine_id="machine-a", host_name="host-a", user_name="alice"))
    agent = store.upsert_agent(
        AgentUpsertRequest(
            short_id="alice-codex-api",
            machine_id="machine-a",
            owner="alice",
            kind="codex",
            workspace="/workspace/service-api",
            tmux_target="dev:0.1",
            receive_mode=ReceiveMode.AUTO_SUBMIT,
            status=AgentStatus.IDLE,
        )
    )
    assert agent is not None
    context = store.update_agent_context("alice-codex-api", AgentContextUpdateRequest(context="recent context"))
    assert context is not None
    return store


def handle(tmp_path: Path, text: str):
    service = FeishuAgentTalkService(make_store(tmp_path), web_base_url="https://agenttalk.company.lan")
    return service.handle(parse_command(text), FeishuOperator(open_id="ou_123", chat_id="oc_123"))


def test_agents_command_returns_card(tmp_path: Path) -> None:
    reply = handle(tmp_path, "/agents")

    assert reply.msg_type == "interactive"
    assert "alice-codex-api" in str(reply.content)


def test_agents_online_command_returns_non_offline_agents(tmp_path: Path) -> None:
    reply = handle(tmp_path, "/agents online")

    assert reply.msg_type == "interactive"
    assert "alice-codex-api" in str(reply.content)


def test_context_command_returns_recent_context(tmp_path: Path) -> None:
    reply = handle(tmp_path, "/context alice-codex-api")

    assert reply.msg_type == "text"
    assert reply.content == "recent context"


def test_send_command_creates_message_with_feishu_sender(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    service = FeishuAgentTalkService(store)

    reply = service.handle(parse_command("/send alice-codex-api please check"), FeishuOperator(open_id="ou_123"))

    assert reply.msg_type == "text"
    assert "Message created." in str(reply.content)
    message_id = str(reply.content).splitlines()[1].removeprefix("message: ")
    message = store.get_message(message_id)
    assert message is not None
    assert message.sender == "feishu:ou_123"
    assert message.body == "please check"


def test_response_command_returns_captured_response(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    service = FeishuAgentTalkService(store)
    created = service.handle(parse_command("/send alice-codex-api body"), FeishuOperator(open_id="ou_123"))
    message_id = str(created.content).splitlines()[1].removeprefix("message: ")
    response = store.update_message_response(message_id, MessageResponseUpdateRequest(response_text="done", completed=True))
    assert response is not None

    reply = service.handle(parse_command(f"/response {message_id}"), FeishuOperator(open_id="ou_123"))

    assert reply.content == "done"


def test_trace_command_returns_message_trace(tmp_path: Path) -> None:
    store = make_store(tmp_path)
    service = FeishuAgentTalkService(store)
    created = service.handle(parse_command("/send alice-codex-api body"), FeishuOperator(open_id="ou_123"))
    message_id = str(created.content).splitlines()[1].removeprefix("message: ")
    response = store.update_message_response(message_id, MessageResponseUpdateRequest(response_text="done", completed=True))
    assert response is not None

    reply = service.handle(parse_command(f"/trace {message_id}"), FeishuOperator(open_id="ou_123"))

    assert "AgentTalk message trace:" in str(reply.content)
    assert f"message: {message_id}" in str(reply.content)
    assert "response preview:" in str(reply.content)


def test_guide_reliability_command_returns_local_relay_guidance(tmp_path: Path) -> None:
    reply = handle(tmp_path, "/guide reliability")

    assert "AgentTalk 可靠投递说明" in str(reply.content)
    assert "agenttalk doctor" in str(reply.content)
    assert "agenttalk dlq list" in str(reply.content)


def test_send_alert_uses_alert_card_and_chat_id(tmp_path: Path) -> None:
    service = FeishuAgentTalkService(make_store(tmp_path), web_base_url="https://agenttalk.company.lan")

    class FakeMessenger:
        def __init__(self) -> None:
            self.calls: list[tuple[str, object]] = []

        def send_to_chat(self, chat_id: str, reply) -> None:
            self.calls.append((chat_id, reply))

    messenger = FakeMessenger()

    service.send_alert(
        messenger,
        "alice-codex-api",
        "warning",
        "Need human review.",
        owner="alice",
        chat_id="oc_123",
    )

    assert len(messenger.calls) == 1
    chat_id, reply = messenger.calls[0]
    assert chat_id == "oc_123"
    assert reply.msg_type == "interactive"
    assert "alice-codex-api" in str(reply.content)
    assert "Need human review." in str(reply.content)
