from __future__ import annotations

from dataclasses import dataclass, field

from agenttalk.config import AgentBinding, AgentTalkConfig
from agenttalk.hub.models import AgentStatus, MessageStatus, ReceiveMode
from agenttalk.relay import AgentTalkRelay, StaticTmuxClient, build_injected_message
from agenttalk.tmux import TmuxPane


@dataclass
class FakeHubClient:
    registered: bool = False
    upserts: list[tuple[str, AgentStatus]] = field(default_factory=list)
    next_payload: dict | None = None
    status_updates: list[tuple[str, MessageStatus, str]] = field(default_factory=list)

    def register_relay(self, _config: AgentTalkConfig) -> None:
        self.registered = True

    def upsert_agent(self, _config: AgentTalkConfig, binding: AgentBinding, status: AgentStatus) -> None:
        self.upserts.append((binding.short_id, status))

    def next_message(self, _machine_id: str) -> dict | None:
        payload = self.next_payload
        self.next_payload = None
        return payload

    def update_message_status(self, message_id: str, status: MessageStatus, error: str = "") -> None:
        self.status_updates.append((message_id, status, error))


class RecordingTmuxClient(StaticTmuxClient):
    def __init__(self, panes: list[TmuxPane]) -> None:
        super().__init__(panes)
        self.injections: list[tuple[str, str, bool]] = []

    def inject_text(self, target: str, text: str, *, submit: bool) -> None:
        self.injections.append((target, text, submit))


def test_relay_sync_marks_missing_pane_offline() -> None:
    config = AgentTalkConfig(
        hub_url="http://hub.local:8787",
        token="token",
        machine_id="machine-a",
        host_name="host-a",
        user_name="alice",
        agents=[
            AgentBinding(
                short_id="alice-codex-api",
                owner="alice",
                kind="codex",
                workspace="/workspace/api",
                tmux_target="dev:0.1",
                pane_id="%1",
            ),
            AgentBinding(
                short_id="alice-claude-ui",
                owner="alice",
                kind="claude",
                workspace="/workspace/ui",
                tmux_target="dev:0.2",
                pane_id="%2",
            ),
        ],
    )
    fake_hub = FakeHubClient()
    tmux = StaticTmuxClient(
        [
            TmuxPane(
                target="dev:0.1",
                pane_id="%1",
                command="codex",
                current_path="/workspace/api",
                title="codex",
                kind="codex",
            )
        ]
    )

    result = AgentTalkRelay(config, hub_client=fake_hub, tmux_client=tmux).sync_once()

    assert fake_hub.registered is True
    assert fake_hub.upserts == [
        ("alice-codex-api", AgentStatus.ONLINE),
        ("alice-claude-ui", AgentStatus.OFFLINE),
    ]
    assert result.upserted == 2
    assert result.online == 1
    assert result.offline == 1


def test_build_injected_message_contains_marker() -> None:
    payload = build_injected_message(
        message_id="msg-1",
        sender="alice",
        target="bob",
        body="Please review.",
        done_marker="<<<AGENTTALK_DONE:msg-1>>>",
    )

    assert "[AgentTalk Message]" in payload
    assert "message_id: msg-1" in payload
    assert "from: alice" in payload
    assert "to: bob" in payload
    assert "Please review." in payload
    assert "<<<AGENTTALK_DONE:msg-1>>>" in payload


def test_relay_process_next_message_injects_auto_submit() -> None:
    config = AgentTalkConfig(
        hub_url="http://hub.local:8787",
        token="token",
        machine_id="machine-a",
        host_name="host-a",
        user_name="alice",
        agents=[
            AgentBinding(
                short_id="alice-codex-api",
                owner="alice",
                kind="codex",
                workspace="/workspace/api",
                tmux_target="dev:0.1",
                pane_id="%1",
                receive_mode=ReceiveMode.AUTO_SUBMIT,
            )
        ],
    )
    fake_hub = FakeHubClient(
        next_payload={
            "message_id": "msg-1",
            "sender": "bob",
            "target": "alice-codex-api",
            "body": "Please review.",
            "done_marker": "<<<AGENTTALK_DONE:msg-1>>>",
        }
    )
    tmux = RecordingTmuxClient([])

    processed = AgentTalkRelay(config, hub_client=fake_hub, tmux_client=tmux).process_next_message_once()

    assert processed is True
    assert tmux.injections[0][0] == "dev:0.1"
    assert tmux.injections[0][2] is True
    assert fake_hub.status_updates == [("msg-1", MessageStatus.INJECTED, "")]


def test_relay_process_next_message_respects_paste_only() -> None:
    config = AgentTalkConfig(
        hub_url="http://hub.local:8787",
        token="token",
        machine_id="machine-a",
        host_name="host-a",
        user_name="alice",
        agents=[
            AgentBinding(
                short_id="alice-codex-api",
                owner="alice",
                kind="codex",
                workspace="/workspace/api",
                tmux_target="dev:0.1",
                pane_id="%1",
                receive_mode=ReceiveMode.PASTE_ONLY,
            )
        ],
    )
    fake_hub = FakeHubClient(
        next_payload={
            "message_id": "msg-1",
            "sender": "bob",
            "target": "alice-codex-api",
            "body": "Please review.",
            "done_marker": "<<<AGENTTALK_DONE:msg-1>>>",
        }
    )
    tmux = RecordingTmuxClient([])

    AgentTalkRelay(config, hub_client=fake_hub, tmux_client=tmux).process_next_message_once()

    assert tmux.injections[0][2] is False
