from __future__ import annotations

from pathlib import Path

from agenttalk.config import AgentBinding, AgentTalkConfig, load_config, save_config, upsert_binding


def test_save_and_load_multiple_bindings(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    config = AgentTalkConfig(
        hub_url="http://hub.local:8787",
        token="token",
        machine_id="machine-a",
        host_name="host-a",
        user_name="alice",
    )
    config = upsert_binding(
        config,
        AgentBinding(
            short_id="alice-codex-api",
            owner="alice",
            kind="codex",
            workspace="/workspace/api",
            tmux_target="dev:0.1",
            pane_id="%1",
        ),
    )
    config = upsert_binding(
        config,
        AgentBinding(
            short_id="alice-claude-ui",
            owner="alice",
            kind="claude",
            workspace="/workspace/ui",
            tmux_target="dev:0.2",
            pane_id="%2",
        ),
    )

    save_config(config, path)
    loaded = load_config(path)

    assert loaded.hub_url == "http://hub.local:8787"
    assert [agent.short_id for agent in loaded.agents] == ["alice-claude-ui", "alice-codex-api"]
