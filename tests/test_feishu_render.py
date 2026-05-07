from __future__ import annotations

from agenttalk.feishu.render import agent_detail_card, agents_card, text_reply, truncate
from agenttalk.hub.models import AgentResponse, AgentStatus, ReceiveMode


def make_agent(short_id: str = "alice-codex-api", *, status: AgentStatus = AgentStatus.IDLE) -> AgentResponse:
    return AgentResponse(
        short_id=short_id,
        machine_id="machine-a",
        owner="alice",
        kind="codex",
        workspace="/workspace/service-api",
        tmux_target="dev:0.1",
        receive_mode=ReceiveMode.AUTO_SUBMIT,
        status=status,
        updated_at="2026-05-07T00:00:00Z",
        relay_last_seen_at="2026-05-07T00:00:00Z",
    )


def test_truncate_bounds_text() -> None:
    value = truncate("x" * 50, limit=20)

    assert len(value) <= 32
    assert value.endswith("...(truncated)")


def test_text_reply_wraps_plain_text() -> None:
    reply = text_reply("hello")

    assert reply.msg_type == "text"
    assert reply.content == "hello"


def test_agents_card_payload_shape() -> None:
    reply = agents_card([make_agent()], web_base_url="https://agenttalk.company.lan")

    assert reply.msg_type == "interactive"
    assert isinstance(reply.content, dict)
    assert reply.content["header"]["title"]["content"] == "AgentTalk Agents"
    assert reply.content["elements"][0]["tag"] == "div"
    assert reply.content["elements"][-1]["tag"] == "action"


def test_agent_detail_card_includes_context_and_web_action() -> None:
    reply = agent_detail_card(make_agent(), context="recent output", web_base_url="https://agenttalk.company.lan")

    assert reply.msg_type == "interactive"
    assert isinstance(reply.content, dict)
    assert reply.content["header"]["title"]["content"] == "alice-codex-api"
    rendered = str(reply.content)
    assert "recent output" in rendered
    assert "Open Web" in rendered
