from __future__ import annotations

from dataclasses import dataclass

import pytest

from agenttalk.config import AgentTalkConfig
from agenttalk.tunnel_server import TunnelServer, TunnelSession, start_tunnel_server


@dataclass
class FakeCompletedProcess:
    returncode: int = 0
    stdout: str = ""
    stderr: str = ""


def test_tunnel_input_uses_literal_tmux_send_keys(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_run(cmd, **_kwargs):
        calls.append(cmd)
        return FakeCompletedProcess()

    monkeypatch.setattr("agenttalk.tunnel_server.subprocess.run", fake_run)
    session = TunnelSession(websocket=object(), tmux_target="agenttalk-e2e-test:0.0", token="token")

    session._sync_input("abc\r")

    assert calls == [
        [
            "tmux",
            "-S",
            "/tmp/tmux-1000/default",
            "send-keys",
            "-l",
            "-t",
            "agenttalk-e2e-test:0.0",
            "abc\r",
        ]
    ]


def test_tunnel_input_reports_tmux_failure(monkeypatch) -> None:
    def fake_run(_cmd, **_kwargs):
        return FakeCompletedProcess(returncode=1, stderr="no pane")

    monkeypatch.setattr("agenttalk.tunnel_server.subprocess.run", fake_run)
    session = TunnelSession(websocket=object(), tmux_target="missing:0.0", token="token")

    with pytest.raises(RuntimeError, match="tmux input failed: no pane"):
        session._sync_input("x")


def test_start_tunnel_server_uses_env_host_and_port(monkeypatch) -> None:
    started: list[tuple[str, int]] = []

    def fake_start_background(self):
        started.append((self.host, self.port))

    monkeypatch.setenv("AGENTTALK_TUNNEL_HOST", "127.0.0.1")
    monkeypatch.setenv("AGENTTALK_TUNNEL_PORT", "9876")
    monkeypatch.setattr(TunnelServer, "start_background", fake_start_background)
    config = AgentTalkConfig(
        hub_url="http://hub.local:8787",
        token="token",
        machine_id="machine-a",
        host_name="host-a",
        user_name="alice",
        agents=[],
    )

    server = start_tunnel_server(config)

    assert (server.host, server.port) == ("127.0.0.1", 9876)
    assert started == [("127.0.0.1", 9876)]


def test_tunnel_server_keeps_config_path_for_connection_reload(tmp_path) -> None:
    config_path = tmp_path / "agenttalk.json"
    config = AgentTalkConfig(
        hub_url="http://hub.local:8787",
        token="token",
        machine_id="machine-a",
        host_name="host-a",
        user_name="alice",
        agents=[],
    )

    server = TunnelServer(config, host="127.0.0.1", port=9876, config_path=config_path)

    assert server.config_path == config_path
