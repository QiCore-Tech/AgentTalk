from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from agenttalk.config import AgentBinding, AgentTalkConfig, save_config
from agenttalk.hub.models import AgentStatus, MessageStatus, ReceiveMode
from agenttalk.process_manager import InjectionResult
from agenttalk.relay import (
    AgentTalkRelay,
    StaticTmuxClient,
    WatchState,
    build_injected_message,
    classify_delivery_evidence,
    detect_errors,
    prepare_injected_message,
    strip_agenttalk_ack,
    strip_injected_message_echo,
    tail_shows_live_agent_ui,
)
from agenttalk.tmux import TmuxPane


@pytest.fixture(autouse=True)
def isolate_watch_state(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("AGENTTALK_WATCH_STATE_PATH", str(tmp_path / "agenttalk-state" / "watch_states.json"))
    monkeypatch.setenv("AGENTTALK_DELIVERY_TICKET_DIR", str(tmp_path / "agenttalk-state" / "delivery"))


@dataclass
class FakeHubClient:
    registered: bool = False
    upserts: list[tuple[str, AgentStatus]] = field(default_factory=list)
    next_payload: dict | None = None
    status_updates: list[tuple[str, MessageStatus, str]] = field(default_factory=list)
    response_updates: list[tuple[str, str, bool]] = field(default_factory=list)
    context_updates: list[tuple[str, str]] = field(default_factory=list)
    heartbeats: list[str] = field(default_factory=list)
    messages: dict[str, dict] = field(default_factory=dict)

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
        self.messages[message_id] = {
            "message_id": message_id,
            "status": MessageStatus.COMPLETED.value if completed else MessageStatus.WORKING.value,
        }

    def get_message(self, message_id: str) -> dict:
        return self.messages.get(message_id, {"message_id": message_id, "status": MessageStatus.WORKING.value})

    def update_agent_context(self, short_id: str, context: str) -> None:
        self.context_updates.append((short_id, context))

    def report_health(self, report) -> None:
        pass

    def heartbeat(self, machine_id: str) -> None:
        self.heartbeats.append(machine_id)


class FailingStatusHubClient(FakeHubClient):
    def update_message_status(self, message_id: str, status: MessageStatus, error: str = "") -> None:
        super().update_message_status(message_id, status, error)
        raise RuntimeError("hub status endpoint down")


class FlakyRegisterHubClient(FakeHubClient):
    def __init__(self) -> None:
        super().__init__()
        self.attempts = 0
        self.failures_remaining = 1

    def register_relay(self, _config: AgentTalkConfig) -> None:
        self.attempts += 1
        if self.failures_remaining:
            self.failures_remaining -= 1
            raise RuntimeError("hub temporarily unavailable")
        self.registered = True


class RecordingTmuxClient(StaticTmuxClient):
    def __init__(self, panes: list[TmuxPane]) -> None:
        super().__init__(panes)
        self.injections: list[tuple[str, str, bool]] = []
        self.sent_keys: list[tuple[str, str]] = []
        self.injection_result = InjectionResult(
            pasted=True,
            submit_requested=True,
            submit_confirmed=True,
            pending_input_detected=False,
            attempts=1,
        )

    def inject_text(self, target: str, text: str, *, submit: bool) -> InjectionResult:
        self.injections.append((target, text, submit))
        return self.injection_result

    def send_key(self, target: str, key: str) -> None:
        self.sent_keys.append((target, key))


class FailingCaptureTmuxClient(RecordingTmuxClient):
    def capture_output(self, target: str, *, lines: int = 300) -> str:
        raise RuntimeError(f"can't find session: {target}")


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


def test_relay_run_forever_retries_after_transient_hub_failure() -> None:
    config = AgentTalkConfig(
        hub_url="http://hub.local:8787",
        token="token",
        machine_id="machine-a",
        host_name="host-a",
        user_name="alice",
        agents=[],
    )
    fake_hub = FlakyRegisterHubClient()
    relay = AgentTalkRelay(config, hub_client=fake_hub, tmux_client=StaticTmuxClient([]))

    relay.run_forever(interval_seconds=0, max_iterations=2)

    assert fake_hub.attempts == 2
    assert fake_hub.registered is True
    # Heartbeat must fire on every iteration (even the one whose register_relay
    # raised), otherwise a single transient hub error stalls the relay's
    # last_seen_at long enough for the Hub to derive every agent as OFFLINE.
    assert fake_hub.heartbeats.count("machine-a") >= 2


class HeartbeatOnlyHubClient(FakeHubClient):
    """HubClient stand-in whose sync_once-time call (register_relay) always fails.

    Used to prove that run_once still heartbeats the relay even when the
    sync_once leg of the loop is broken end-to-end.
    """

    def register_relay(self, _config: AgentTalkConfig) -> None:
        raise RuntimeError("hub register endpoint is down")


def test_run_once_heartbeats_even_when_sync_step_fails() -> None:
    config = AgentTalkConfig(
        hub_url="http://hub.local:8787",
        token="token",
        machine_id="machine-a",
        host_name="host-a",
        user_name="alice",
        agents=[],
    )
    fake_hub = HeartbeatOnlyHubClient()
    relay = AgentTalkRelay(config, hub_client=fake_hub, tmux_client=StaticTmuxClient([]))

    # sync_once will raise inside; run_once must catch and still heartbeat so
    # the Hub does not flip every agent on this machine to OFFLINE after the
    # heartbeat TTL expires.
    relay.run_once()

    assert fake_hub.heartbeats, "heartbeat must fire even when sync_once raised"
    assert fake_hub.heartbeats[0] == "machine-a"


def test_detect_errors_ignores_terminal_ui_failure_text() -> None:
    output = """
● ACK agenttalk watch fixed
<<<AGENTTALK_DONE:msg-1>>>
✗ Auto-update failed · Try claude doctor or npm i -g @anthropic-ai/claude-code
› Run /review on my current changes
"""

    assert detect_errors(output) == []


def test_detect_errors_ignores_diagnostic_command_text() -> None:
    output = """
codex-worker             codex      coder        error      /workspace/app
Are forbidden surfaces untouched?
https://developer.mozilla.org/en-US/docs/Web/HTTP/Status/502
│ -i 'error|failed|fatal|panic|traceback|500|502|503|504|connection|rate limit|quota|oom|killed'
│ python -c 'from agenttalk.relay import detect_errors'
"""

    assert detect_errors(output) == []


def test_detect_errors_keeps_actionable_diagnostics() -> None:
    output = """
Traceback (most recent call last):
Error: connection refused
npm ERR! command failed
HTTPStatusError: Server error '502 Bad Gateway'
Killed
"""

    assert detect_errors(output) == [
        "command_error",
        "error",
        "http_error",
        "network_error",
        "process_error",
        "traceback",
    ]


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


def test_relay_sync_does_not_mark_live_agent_error_for_scrollback_diagnostics() -> None:
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
    tmux.captures["dev:0.1"] = "\n".join(
        [
            "error: aborted during AgentTalk repair",
            "Traceback: diagnostic text from a command output",
            "› Implement {feature}",
            "  gpt-5.5 xhigh · /workspace/api",
        ]
    )

    AgentTalkRelay(config, hub_client=fake_hub, tmux_client=tmux).sync_once()

    assert detect_errors(tmux.captures["dev:0.1"])
    assert tail_shows_live_agent_ui(tmux.captures["dev:0.1"])
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
    assert "AGENTTALK_ACK:msg-1" in payload
    assert "Do not stop after the ACK line" in payload
    assert "continue with the task immediately" in payload
    assert "First print this exact acknowledgement" not in payload
    assert "<<<AGENTTALK_DONE:msg-1>>>" in payload


def test_prepare_injected_message_keeps_short_message_inline(tmp_path) -> None:
    payload = prepare_injected_message(
        message_id="msg-1",
        sender="alice",
        target="bob",
        body="Please review.\nFocus on errors.",
        done_marker="<<<AGENTTALK_DONE:msg-1>>>",
        spool_dir=tmp_path,
    )

    assert "\n" not in payload
    assert "Please review. Focus on errors." in payload
    assert "AGENTTALK_ACK:msg-1" in payload
    assert "Do not stop after the ACK line" in payload
    assert "continue with the task immediately" in payload
    assert "First print this exact acknowledgement" not in payload
    assert "Full task is stored" not in payload
    assert "<<<AGENTTALK_DONE:msg-1>>>" in payload
    assert list(tmp_path.iterdir()) == []


def test_prepare_injected_message_spools_long_multiline_message(tmp_path) -> None:
    body = "\n".join(f"line {index}: please review this detail" for index in range(40))

    payload = prepare_injected_message(
        message_id="msg-long/1",
        sender="alice",
        target="bob",
        body=body,
        done_marker="<<<AGENTTALK_DONE:msg-long-1>>>",
        spool_dir=tmp_path,
    )

    spool_files = list(tmp_path.glob("*.md"))
    assert len(spool_files) == 1
    spooled = spool_files[0].read_text(encoding="utf-8")
    assert body in spooled
    assert "AGENTTALK_ACK:msg-long/1" in spooled
    assert "Do not stop after the ACK line" in spooled
    assert "continue with the task immediately" in spooled
    assert "First print this exact acknowledgement" not in spooled
    assert "<<<AGENTTALK_DONE:msg-long-1>>>" in spooled
    assert "\n" not in payload
    assert "Full task is stored at" in payload
    assert "Do not stop after the ACK line" in payload
    assert "continue with the task immediately" in payload
    assert "First print this exact acknowledgement" not in payload
    assert body not in payload
    assert str(spool_files[0]) in payload


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
    assert fake_hub.status_updates == [("msg-1", MessageStatus.SUBMITTED, "")]


def test_relay_process_next_message_creates_delivery_ticket(tmp_path) -> None:
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
    ticket_dir = tmp_path / "delivery"

    AgentTalkRelay(
        config,
        hub_client=fake_hub,
        tmux_client=tmux,
        delivery_ticket_dir=ticket_dir,
    ).process_next_message_once()

    ticket = ticket_dir / "msg-1.json"
    assert ticket.exists()
    data = ticket.read_text(encoding="utf-8")
    assert '"message_id": "msg-1"' in data
    assert '"status": "submitted_visible"' in data


def test_delivery_ticket_recovery_sends_tab_for_busy_codex_queue(monkeypatch, tmp_path) -> None:
    import agenttalk.relay as relay_module

    monkeypatch.setattr(relay_module, "DELIVERY_RECOVERY_GRACE_SECONDS", 0)
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
    tmux.captures["dev:0.1"] = "\n".join(
        [
            "Working (esc to interrupt)",
            "› [AgentTalk Message] message_id: msg-1 from: bob to: alice-codex-api.",
            "tab to queue message",
        ]
    )
    relay = AgentTalkRelay(
        config,
        hub_client=fake_hub,
        tmux_client=tmux,
        delivery_ticket_dir=tmp_path / "delivery",
    )
    relay._save_delivery_ticket(
        relay_module.DeliveryTicket(
            message_id="msg-1",
            sender="bob",
            target="alice-codex-api",
            tmux_target="dev:0.1",
            done_marker="<<<AGENTTALK_DONE:msg-1>>>",
            status="submit_attempted",
            submit_requested=True,
        )
    )

    recovered = relay.recover_delivery_tickets_once()

    assert recovered == 1
    assert tmux.sent_keys == [("dev:0.1", "Tab")]
    assert relay.delivery_tickets["msg-1"].status == "submit_retried"
    assert relay.delivery_tickets["msg-1"].recovery_attempts == 1


def test_delivery_ticket_recovery_fails_closed_after_max_attempts(monkeypatch, tmp_path) -> None:
    import agenttalk.dlq as dlq_module
    import agenttalk.relay as relay_module

    dlq_path = tmp_path / "dlq.json"
    monkeypatch.setattr(dlq_module, "default_dlq_path", lambda: dlq_path)
    monkeypatch.setattr(relay_module, "record_dead_letter", dlq_module.record_dead_letter)
    monkeypatch.setattr(relay_module, "DELIVERY_RECOVERY_GRACE_SECONDS", 0)
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
    tmux.captures["dev:0.1"] = "› [AgentTalk Message] message_id: msg-1 from: bob to: alice-codex-api."
    relay = AgentTalkRelay(
        config,
        hub_client=fake_hub,
        tmux_client=tmux,
        delivery_ticket_dir=tmp_path / "delivery",
    )
    relay._save_delivery_ticket(
        relay_module.DeliveryTicket(
            message_id="msg-1",
            sender="bob",
            target="alice-codex-api",
            tmux_target="dev:0.1",
            done_marker="<<<AGENTTALK_DONE:msg-1>>>",
            status="submit_retried",
            submit_requested=True,
            recovery_attempts=relay_module.DELIVERY_RECOVERY_MAX_ATTEMPTS,
        )
    )

    recovered = relay.recover_delivery_tickets_once()

    assert recovered == 0
    assert tmux.sent_keys == []
    assert fake_hub.status_updates == [("msg-1", MessageStatus.SUBMIT_UNCONFIRMED, relay.delivery_tickets["msg-1"].last_error)]
    records = dlq_module.load_dead_letters(dlq_path)
    assert records[0]["message_id"] == "msg-1"
    assert records[0]["reason"] == "delivery_ticket_submit_unconfirmed"


def test_classify_delivery_evidence_distinguishes_ack_active_and_pending() -> None:
    assert (
        classify_delivery_evidence(
            "› [AgentTalk Message] message_id: msg-1\nAGENTTALK_ACK:msg-1",
            "msg-1",
        )
        == "acked"
    )
    assert (
        classify_delivery_evidence(
            "› [AgentTalk Message] message_id: msg-1\n✻ Thinking about task",
            "msg-1",
        )
        == "submitted_visible"
    )
    assert (
        classify_delivery_evidence(
            "Working (esc to interrupt)\n› [AgentTalk Message] message_id: msg-1\ntab to queue message",
            "msg-1",
        )
        == "pending_input"
    )


def test_relay_persists_watch_before_status_update_failure(tmp_path) -> None:
    watch_path = tmp_path / "watch_states.json"
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
    fake_hub = FailingStatusHubClient(
        next_payload={
            "message_id": "msg-1",
            "sender": "bob",
            "target": "alice-codex-api",
            "body": "Please review.",
            "done_marker": "<<<AGENTTALK_DONE:msg-1>>>",
        }
    )
    tmux = RecordingTmuxClient([])

    try:
        AgentTalkRelay(
            config,
            hub_client=fake_hub,
            tmux_client=tmux,
            watch_state_path=watch_path,
        ).process_next_message_once()
    except RuntimeError:
        pass

    reloaded = AgentTalkRelay(
        config,
        hub_client=FakeHubClient(),
        tmux_client=tmux,
        watch_state_path=watch_path,
    )

    assert "msg-1" in reloaded.watch_states
    assert reloaded.watch_states["msg-1"].target == "dev:0.1"


def test_relay_reloads_config_from_disk_without_losing_watch_state(tmp_path) -> None:
    config_path = tmp_path / "config.json"
    watch_path = tmp_path / "watch_states.json"
    initial = AgentTalkConfig(
        hub_url="http://hub.local:8787",
        token="token",
        machine_id="machine-a",
        host_name="host-a",
        user_name="alice",
        agents=[],
    )
    updated = initial.model_copy(
        update={
            "agents": [
                AgentBinding(
                    short_id="new-agent",
                    owner="alice",
                    kind="codex",
                    workspace="/workspace/api",
                    tmux_target="dev:0.1",
                    pane_id="%1",
                )
            ]
        }
    )
    save_config(updated, config_path)
    relay = AgentTalkRelay(
        initial,
        hub_client=FakeHubClient(),
        tmux_client=RecordingTmuxClient([]),
        watch_state_path=watch_path,
    )
    relay.watch_states["msg-1"] = WatchState(
        target="dev:0.1",
        baseline="before\n",
        done_marker="<<<AGENTTALK_DONE:msg-1>>>",
    )

    relay.run_once(config_path=config_path)

    assert [agent.short_id for agent in relay.config.agents] == ["new-agent"]
    assert "msg-1" in relay.watch_states


def test_relay_process_next_message_spools_long_body(monkeypatch, tmp_path) -> None:
    import agenttalk.relay as relay_module

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
    body = "\n".join(f"review item {index}" for index in range(60))
    fake_hub = FakeHubClient(
        next_payload={
            "message_id": "msg-long",
            "sender": "bob",
            "target": "alice-codex-api",
            "body": body,
            "done_marker": "<<<AGENTTALK_DONE:msg-long>>>",
        }
    )
    tmux = RecordingTmuxClient([])
    monkeypatch.setattr(relay_module, "default_message_spool_dir", lambda: tmp_path)

    processed = AgentTalkRelay(config, hub_client=fake_hub, tmux_client=tmux).process_next_message_once()

    assert processed is True
    injected = tmux.injections[0][1]
    assert tmux.injections[0][2] is True
    assert body not in injected
    assert "\n" not in injected
    spool_files = list(tmp_path.glob("*.md"))
    assert len(spool_files) == 1
    assert body in spool_files[0].read_text(encoding="utf-8")
    assert fake_hub.status_updates == [("msg-long", MessageStatus.SUBMITTED, "")]


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
    # Paste-only deliveries must surface a distinct status so the caller can tell
    # the message is sitting in the pane's input box, not yet seen by the agent.
    assert fake_hub.status_updates == [("msg-1", MessageStatus.INJECTED_PASTE_ONLY, "")]


def test_relay_process_next_message_records_submit_unconfirmed(tmp_path, monkeypatch) -> None:
    import agenttalk.dlq as dlq_module
    import agenttalk.relay as relay_module

    dlq_path = tmp_path / "dlq.json"
    monkeypatch.setattr(dlq_module, "default_dlq_path", lambda: dlq_path)
    monkeypatch.setattr(relay_module, "record_dead_letter", dlq_module.record_dead_letter)
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
    tmux.injection_result = InjectionResult(
        pasted=True,
        submit_requested=True,
        submit_confirmed=False,
        pending_input_detected=True,
        attempts=5,
    )

    AgentTalkRelay(config, hub_client=fake_hub, tmux_client=tmux).process_next_message_once()

    assert fake_hub.status_updates == [("msg-1", MessageStatus.SUBMIT_UNCONFIRMED, "")]
    records = dlq_module.load_dead_letters(dlq_path)
    assert records[0]["message_id"] == "msg-1"
    assert records[0]["reason"] == "submit_unconfirmed"


def test_relay_auto_submit_uses_injected_status() -> None:
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

    AgentTalkRelay(config, hub_client=fake_hub, tmux_client=tmux).process_next_message_once()

    # Auto-submit deliveries become SUBMITTED only after the tmux driver
    # confirms that Enter took effect.
    assert fake_hub.status_updates == [("msg-1", MessageStatus.SUBMITTED, "")]


def test_strip_agenttalk_ack_removes_ack_line() -> None:
    acked, stripped = strip_agenttalk_ack(
        "AGENTTALK_ACK:msg-1\nanswer\n<<<AGENTTALK_DONE:msg-1>>>\n",
        "msg-1",
    )

    assert acked is True
    assert stripped == "answer\n<<<AGENTTALK_DONE:msg-1>>>"


def test_relay_watch_marks_acked_without_completion() -> None:
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
    tmux.captures["dev:0.1"] = "before\nAGENTTALK_ACK:msg-1\n"
    relay = AgentTalkRelay(config, hub_client=fake_hub, tmux_client=tmux)
    relay.watch_states["msg-1"] = WatchState(
        target="dev:0.1",
        baseline="before\n",
        done_marker="<<<AGENTTALK_DONE:msg-1>>>",
    )

    relay.update_watches_once()

    assert fake_hub.response_updates == [("msg-1", "", False)]
    assert fake_hub.status_updates == [("msg-1", MessageStatus.ACKED, "")]
    assert "msg-1" in relay.watch_states


def test_relay_watch_fails_closed_when_target_pane_disappears() -> None:
    config = AgentTalkConfig(
        hub_url="http://hub.local:8787",
        token="token",
        machine_id="machine-a",
        host_name="host-a",
        user_name="alice",
        agents=[],
    )
    fake_hub = FakeHubClient()
    relay = AgentTalkRelay(config, hub_client=fake_hub, tmux_client=FailingCaptureTmuxClient([]))
    relay.watch_states["msg-1"] = WatchState(
        target="agenttalk-e2e-missing:0.0",
        baseline="before\n",
        done_marker="<<<AGENTTALK_DONE:msg-1>>>",
    )

    updates = relay.update_watches_once()

    assert updates == 0
    assert fake_hub.status_updates == [
        ("msg-1", MessageStatus.FAILED, "watch target unavailable: agenttalk-e2e-missing:0.0")
    ]
    assert "msg-1" not in relay.watch_states


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
    tmux.captures["dev:0.1"] = "before\nAGENTTALK_ACK:msg-1\nanswer\n<<<AGENTTALK_DONE:msg-1>>>\n"
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


def test_relay_watch_rejects_marker_substring_in_random_output() -> None:
    """The marker must appear on its own line; a substring inside arbitrary
    output (e.g., a fenced code block in the agent's reply) must NOT trigger a
    false completion."""
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
    # The marker is embedded mid-line — not on its own line. This used to be
    # treated as a completion because the old check was ``marker in delta``.
    tmux.captures["dev:0.1"] = (
        "before\n"
        "I will print the marker like this <<<AGENTTALK_DONE:msg-1>>> as part of the explanation.\n"
    )
    relay = AgentTalkRelay(config, hub_client=fake_hub, tmux_client=tmux)
    relay.watch_states["msg-1"] = WatchState(
        target="dev:0.1",
        baseline="before\n",
        done_marker="<<<AGENTTALK_DONE:msg-1>>>",
    )

    relay.update_watches_once()

    completed_calls = [u for u in fake_hub.response_updates if u[2] is True]
    assert completed_calls == [], (
        "marker as mid-line substring must not be accepted as completion"
    )
    assert fake_hub.status_updates == [("msg-1", MessageStatus.WORKING, "")]
    assert "msg-1" in relay.watch_states


def test_relay_watch_rejects_echo_only_completion() -> None:
    """If the only thing between the echoed prompt and a stray marker line is
    blank output, that is NOT a completion — the peer never actually replied."""
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
    # Terminal echoed the prompt, then a second copy of the marker showed up
    # (e.g., zsh echoed the typed text again as a command attempt) but there is
    # no real response text between the two — only blank/whitespace lines.
    tmux.captures["dev:0.1"] = (
        f"before\n{injected}\n   \n\t\n<<<AGENTTALK_DONE:msg-1>>>\n"
    )
    relay = AgentTalkRelay(config, hub_client=fake_hub, tmux_client=tmux)
    relay.watch_states["msg-1"] = WatchState(
        target="dev:0.1",
        baseline="before\n",
        done_marker="<<<AGENTTALK_DONE:msg-1>>>",
    )

    relay.update_watches_once()

    completed_calls = [u for u in fake_hub.response_updates if u[2] is True]
    assert completed_calls == [], (
        "echo-only delta with no real response between echo and marker must "
        "not be accepted as completion"
    )
    assert "msg-1" in relay.watch_states


def test_relay_watch_does_not_downgrade_terminal_hub_status() -> None:
    config = AgentTalkConfig(
        hub_url="http://hub.local:8787",
        token="token",
        machine_id="machine-a",
        host_name="host-a",
        user_name="alice",
        agents=[],
    )
    fake_hub = FakeHubClient()
    fake_hub.messages["msg-1"] = {
        "message_id": "msg-1",
        "status": MessageStatus.COMPLETED.value,
    }
    tmux = RecordingTmuxClient([])
    tmux.captures["dev:0.1"] = "before\nstill visible output\n"
    relay = AgentTalkRelay(config, hub_client=fake_hub, tmux_client=tmux)
    relay.watch_states["msg-1"] = WatchState(
        target="dev:0.1",
        baseline="before\n",
        done_marker="<<<AGENTTALK_DONE:msg-1>>>",
    )

    updates = relay.update_watches_once()

    assert updates == 0
    assert fake_hub.status_updates == []
    assert fake_hub.response_updates == []
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
