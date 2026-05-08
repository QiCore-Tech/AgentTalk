from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from agenttalk.hub.app import create_app
from agenttalk.hub.settings import HubSettings
from agenttalk.relay import output_delta


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
            "tmux_target": "dev:0.1",
            "receive_mode": "auto_submit",
            "status": "idle",
        },
    )


def create_message(client: TestClient) -> str:
    response = client.post(
        "/api/messages",
        headers=auth(),
        json={"to": "alice-codex-api", "sender": "bob", "body": "review"},
    )
    return str(response.json()["message_id"])


def test_message_response_update_can_complete(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    register_target(client)
    message_id = create_message(client)

    response = client.post(
        f"/api/messages/{message_id}/response",
        headers=auth(),
        json={"response_text": "done", "completed": True},
    )

    assert response.status_code == 200
    assert response.json()["response_text"] == "done"
    message = client.get(f"/api/messages/{message_id}", headers=auth())
    assert message.json()["status"] == "completed"


def test_agent_context_update_and_get(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    register_target(client)

    response = client.post(
        "/api/agents/alice-codex-api/context",
        headers=auth(),
        json={"context": "line 1\nline 2"},
    )

    assert response.status_code == 200
    context = client.get("/api/agents/alice-codex-api/context", headers=auth())
    assert context.json()["context"] == "line 1\nline 2"


def test_output_delta_with_prefix() -> None:
    assert output_delta("a\nb\n", "a\nb\nc\n") == "c\n"


def test_output_delta_with_line_overlap() -> None:
    assert output_delta("old\nshared", "shared\nnew") == "new"
