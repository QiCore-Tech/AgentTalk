from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

import agenttalk.hub.app as hub_app_module
from agenttalk.hub.app import create_app
from agenttalk.hub.settings import HubSettings
from agenttalk.hub.store import HubStore


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


def test_pty_websocket_falls_back_when_relay_has_no_host(tmp_path: Path) -> None:
    database_path = tmp_path / "hub.sqlite3"
    client = TestClient(create_app(HubSettings(database_path=database_path, token="test-token")))
    client.post(
        "/api/relays/register",
        headers=auth(),
        json={"machine_id": "machine-a", "host_name": "host-a", "user_name": "alice"},
    )
    store = HubStore(database_path)
    with store.connect() as conn:
        conn.execute("UPDATE relays SET host_name = '', lan_ip = '' WHERE machine_id = 'machine-a'")
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

    with client.websocket_connect("/ws/pty/alice-codex-api") as websocket:
        message = websocket.receive_text()

    assert "[Connected to PTY]" in message


def test_terminal_websocket_uses_registered_tmux_target(tmp_path: Path, monkeypatch) -> None:
    FakeTmuxClient.writes = []
    monkeypatch.setattr(hub_app_module, "TmuxClient", FakeTmuxClient)
    client = make_client(tmp_path)
    register_target(client)

    with client.websocket_connect("/ws/terminal/alice-codex-api") as websocket:
        assert "captured agenttalk-e2e-api:0.0" in websocket.receive_text()
        websocket.send_text("x")

    assert FakeTmuxClient.writes == [("agenttalk-e2e-api:0.0", "x", False)]


def test_relay_terminal_websocket_sends_hello_ok(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    with client.websocket_connect("/ws/relay-terminal/machine-a") as websocket:
        websocket.send_text(
            json.dumps(
                {
                    "type": "hello",
                    "machine_id": "machine-a",
                    "token": "test-token",
                    "version": "test",
                }
            )
        )

        assert json.loads(websocket.receive_text()) == {"type": "hello_ok"}
