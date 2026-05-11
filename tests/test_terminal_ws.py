from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

import agenttalk.hub.app as hub_app_module
from agenttalk.hub.app import create_app
from agenttalk.hub.settings import HubSettings


class FakeTmuxClient:
    writes: list[tuple[str, str, bool]] = []

    def capture_output(self, target: str, *, lines: int = 120) -> str:
        return f"captured {target}"

    def inject_text(self, target: str, text: str, *, submit: bool) -> None:
        self.writes.append((target, text, submit))


def make_client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(HubSettings(database_path=tmp_path / "hub.sqlite3", token="test-token")))


def auth() -> dict[str, str]:
    return {"Authorization": "Bearer test-token"}


def register_target(client: TestClient) -> None:
    client.post(
        "/api/relays/register",
        headers=auth(),
        json={"machine_id": "machine-a", "host_name": "host-a", "user_name": "alice"},
    )
    client.put(
        "/api/agents",
        headers=auth(),
        json={
            "short_id": "alice-codex-api",
            "machine_id": "machine-a",
            "owner": "alice",
            "kind": "codex",
            "workspace": "/workspace/api",
            "tmux_target": "agenttalk-e2e-api:0.0",
            "receive_mode": "auto_submit",
            "status": "idle",
        },
    )


def test_terminal_websocket_uses_registered_tmux_target(tmp_path: Path, monkeypatch) -> None:
    FakeTmuxClient.writes = []
    monkeypatch.setattr(hub_app_module, "TmuxClient", FakeTmuxClient)
    client = make_client(tmp_path)
    register_target(client)

    with client.websocket_connect("/ws/terminal/alice-codex-api") as websocket:
        assert "captured agenttalk-e2e-api:0.0" in websocket.receive_text()
        websocket.send_text("x")

    assert FakeTmuxClient.writes == [("agenttalk-e2e-api:0.0", "x", False)]
