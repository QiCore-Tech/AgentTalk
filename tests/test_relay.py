from __future__ import annotations

from dataclasses import dataclass, field

from agenttalk.config import AgentBinding, AgentTalkConfig
from agenttalk.hub.models import AgentStatus, MessageStatus, ReceiveMode
from agenttalk.relay import (
    AgentTalkRelay,
    StaticTmuxClient,
    WatchState,
    build_injected_message,
    detect_errors,
    strip_injected_message_echo,
)
from agenttalk.tmux import TmuxPane


@dataclass
class FakeHubClient:
    registered: bool = False
    upserts: list[tuple[str, AgentStatus]] = field(default_factory=list)
    next_payload: dict | None = None
    status_updates: list[tuple[str, MessageStatus, str]] = field(default_factory=list)
    response_updates: list[tuple[str, str, bool]] = field(default_factory=list)
    context_updates: list[tuple[str, str]] = field(default_factory=list)

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

    def update_message_response(self, message_id: str, response_text: str, *, completed: bool) -> None:
        self.response_updates.append((message_id, response_text, completed))

    def update_agent_context(self, short_id: str, context: str) -> None:
        self.context_updates.append((short_id, context))

    def report_health(self, report) -> None:
        pass

    def heartbeat(self, machine_id: str) -> None:
        pass


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
                pane_pid=None,
            )
        ]
    )

    result = AgentTalkRelay(config, hub_client=fake_hub, tmux_client=tmux).sync_once()

    assert fake_hub.registered is True
    assert fake_hub.upserts == [
        ("alice-codex-api", AgentStatus.IDLE),
        ("alice-claude-ui", AgentStatus.OFFLINE),
    ]
    assert result.upserted == 2
    assert result.online == 1
    assert result.offline == 1


def test_detect_errors_ignores_terminal_ui_failure_text() -> None:
    output = """
● ACK agenttalk watch fixed
<<<AGENTTALK_DONE:msg-1>>>
✗ Auto-update failed · Try claude doctor or npm i -g @anthropic-ai/claude-code
› Run /review on my current changes
"""

    assert detect_errors(output) == []


def test_detect_errors_keeps_actionable_diagnostics() -> None:
    output = """
Traceback (most recent call last):
Error: connection refused
npm ERR! command failed
"""

    assert detect_errors(output) == ["command_error", "error", "network_error", "traceback"]


def test_relay_sync_does_not_mark_agent_error_for_terminal_ui_failure_text() -> None:
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
            )
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
                pane_pid=None,
            )
        ]
    )
    tmux.captures["dev:0.1"] = "✗ Auto-update failed · Try claude doctor\n› Run /review on my current changes\n"

    AgentTalkRelay(config, hub_client=fake_hub, tmux_client=tmux).sync_once()

    assert fake_hub.upserts == [("alice-codex-api", AgentStatus.IDLE)]


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


def test_relay_watch_detects_done_marker() -> None:
    config = AgentTalkConfig(
        hub_url="http://hub.local:8787",
        token="token",
        machine_id="machine-a",
        host_name="host-a",
        user_name="alice",
        agents=[],
    )
    fake_hub = FakeHubClient()
    tmux = RecordingTmuxClient([])
    tmux.captures["dev:0.1"] = "before\nanswer\n<<<AGENTTALK_DONE:msg-1>>>\n"
    relay = AgentTalkRelay(config, hub_client=fake_hub, tmux_client=tmux)
    relay.watch_states["msg-1"] = WatchState(
        target="dev:0.1",
        baseline="before\n",
        done_marker="<<<AGENTTALK_DONE:msg-1>>>",
    )

    updates = relay.update_watches_once()

    assert updates == 1
    assert fake_hub.response_updates == [("msg-1", "answer", True)]
    assert "msg-1" not in relay.watch_states


def test_relay_watch_ignores_echoed_injected_done_marker() -> None:
    config = AgentTalkConfig(
        hub_url="http://hub.local:8787",
        token="token",
        machine_id="machine-a",
        host_name="host-a",
        user_name="alice",
        agents=[],
    )
    fake_hub = FakeHubClient()
    tmux = RecordingTmuxClient([])
    injected = build_injected_message(
        message_id="msg-1",
        sender="bob",
        target="alice-codex-api",
        body="Please reply.",
        done_marker="<<<AGENTTALK_DONE:msg-1>>>",
    )
    tmux.captures["dev:0.1"] = f"before\n{injected}\n"
    relay = AgentTalkRelay(config, hub_client=fake_hub, tmux_client=tmux)
    relay.watch_states["msg-1"] = WatchState(
        target="dev:0.1",
        baseline="before\n",
        done_marker="<<<AGENTTALK_DONE:msg-1>>>",
    )

    updates = relay.update_watches_once()

    assert updates == 1
    assert fake_hub.response_updates == [("msg-1", "", False)]
    assert fake_hub.status_updates == [("msg-1", MessageStatus.WORKING, "")]
    assert "msg-1" in relay.watch_states


def test_relay_watch_completes_after_echoed_prompt_and_agent_marker() -> None:
    config = AgentTalkConfig(
        hub_url="http://hub.local:8787",
        token="token",
        machine_id="machine-a",
        host_name="host-a",
        user_name="alice",
        agents=[],
    )
    fake_hub = FakeHubClient()
    tmux = RecordingTmuxClient([])
    injected = build_injected_message(
        message_id="msg-1",
        sender="bob",
        target="alice-codex-api",
        body="Please reply.",
        done_marker="<<<AGENTTALK_DONE:msg-1>>>",
    )
    tmux.captures["dev:0.1"] = (
        f"before\n{injected}\nACK agenttalk reachable\n<<<AGENTTALK_DONE:msg-1>>>\n"
    )
    relay = AgentTalkRelay(config, hub_client=fake_hub, tmux_client=tmux)
    relay.watch_states["msg-1"] = WatchState(
        target="dev:0.1",
        baseline="before\n",
        done_marker="<<<AGENTTALK_DONE:msg-1>>>",
    )

    updates = relay.update_watches_once()

    assert updates == 1
    assert fake_hub.response_updates == [("msg-1", "ACK agenttalk reachable", True)]
    assert "msg-1" not in relay.watch_states


def test_strip_injected_message_echo_leaves_normal_response_delta() -> None:
    delta = "answer\n<<<AGENTTALK_DONE:msg-1>>>\n"

    stripped = strip_injected_message_echo(delta, "<<<AGENTTALK_DONE:msg-1>>>")

    assert stripped == delta


def test_relay_sync_context_once() -> None:
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
            )
        ],
    )
    fake_hub = FakeHubClient()
    tmux = RecordingTmuxClient([])
    tmux.captures["dev:0.1"] = "recent output"

    count = AgentTalkRelay(config, hub_client=fake_hub, tmux_client=tmux).sync_context_once()

    assert count == 1
    assert fake_hub.context_updates == [("alice-codex-api", "recent output")]
