from __future__ import annotations

from dataclasses import dataclass, field

from agenttalk.config import AgentBinding, AgentTalkConfig
from agenttalk.hub.models import AgentStatus
from agenttalk.relay import AgentTalkRelay, StaticTmuxClient
from agenttalk.tmux import TmuxPane


@dataclass
class FakeHubClient:
    registered: bool = False
    upserts: list[tuple[str, AgentStatus]] = field(default_factory=list)

    def register_relay(self, _config: AgentTalkConfig) -> None:
        self.registered = True

    def upsert_agent(self, _config: AgentTalkConfig, binding: AgentBinding, status: AgentStatus) -> None:
        self.upserts.append((binding.short_id, status))


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
