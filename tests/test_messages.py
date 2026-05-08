from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from agenttalk.hub.app import create_app
from agenttalk.hub.settings import HubSettings


def make_client(tmp_path: Path, *, heartbeat_ttl_seconds: int = 30) -> TestClient:
    return TestClient(
        create_app(
            HubSettings(
                database_path=tmp_path / "hub.sqlite3",
                token="test-token",
                heartbeat_ttl_seconds=heartbeat_ttl_seconds,
            )
        )
    )


def auth() -> dict[str, str]:
    return {"Authorization": "Bearer test-token"}


def register_target(client: TestClient, *, status: str = "idle") -> None:
    assert (
        client.post(
            "/api/relays/register",
            headers=auth(),
            json={"machine_id": "machine-a", "host_name": "host-a", "user_name": "alice"},
        ).status_code
        == 200
    )
    assert (
        client.put(
            "/api/agents",
            headers=auth(),
            json={
                "short_id": "alice-codex-api",
                "machine_id": "machine-a",
                "owner": "alice",
                "kind": "codex",
                "workspace": "/workspace/api",
                "tmux_target": "dev:0.1",
                "receive_mode": "auto_submit",
                "status": status,
            },
        ).status_code
        == 200
    )


def test_create_message_to_online_agent(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    register_target(client)

    response = client.post(
        "/api/messages",
        headers=auth(),
        json={"to": "alice-codex-api", "sender": "bob-claude-ui", "body": "Please review API."},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "sent"
    assert payload["target"] == "alice-codex-api"
    assert payload["done_marker"] == f"<<<AGENTTALK_DONE:{payload['message_id']}>>>"


def test_create_message_to_missing_agent_fails(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    response = client.post(
        "/api/messages",
        headers=auth(),
        json={"to": "missing", "sender": "bob", "body": "hello"},
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "target_not_found"


def test_create_message_to_offline_agent_fails(tmp_path: Path) -> None:
    client = make_client(tmp_path, heartbeat_ttl_seconds=-1)
    register_target(client)

    response = client.post(
        "/api/messages",
        headers=auth(),
        json={"to": "alice-codex-api", "sender": "bob", "body": "hello"},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "target_offline"


def test_relay_poll_marks_message_delivered_then_injected(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    register_target(client)
    created = client.post(
        "/api/messages",
        headers=auth(),
        json={"to": "alice-codex-api", "sender": "bob", "body": "hello"},
    ).json()

    pending = client.get("/api/relays/machine-a/messages/next", headers=auth())

    assert pending.status_code == 200
    message = pending.json()["message"]
    assert message["message_id"] == created["message_id"]
    assert message["status"] == "delivered"

    updated = client.post(
        f"/api/messages/{created['message_id']}/status",
        headers=auth(),
        json={"status": "injected", "error": ""},
    )

    assert updated.status_code == 200
    assert updated.json()["status"] == "injected"
