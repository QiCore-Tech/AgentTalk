from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from agenttalk.config import default_lan_ip
import agenttalk.hub.app as hub_app_module
from agenttalk.hub.app import create_app
from agenttalk.hub.settings import HubSettings


def make_client(tmp_path: Path, *, heartbeat_ttl_seconds: int = 30) -> TestClient:
    app = create_app(
        HubSettings(
            database_path=tmp_path / "hub.sqlite3",
            token="test-token",
            heartbeat_ttl_seconds=heartbeat_ttl_seconds,
        )
    )
    return TestClient(app)


def auth() -> dict[str, str]:
    return {"Authorization": "Bearer test-token"}


def register_relay(client: TestClient, machine_id: str = "machine-a") -> None:
    response = client.post(
        "/api/relays/register",
        headers=auth(),
        json={"machine_id": machine_id, "host_name": "host-a", "user_name": "alice"},
    )
    assert response.status_code == 200


def upsert_agent(client: TestClient, short_id: str, machine_id: str = "machine-a") -> None:
    response = client.put(
        "/api/agents",
        headers=auth(),
        json={
            "short_id": short_id,
            "machine_id": machine_id,
            "owner": "alice",
            "kind": "codex",
            "workspace": "/workspace/project",
            "tmux_target": "dev:0.1",
            "receive_mode": "auto_submit",
            "status": "idle",
        },
    )
    assert response.status_code == 200


def test_health_does_not_require_token(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_api_requires_token(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    response = client.get("/api/agents")

    assert response.status_code == 401
    assert response.json() == {
        "error": {
            "code": "unauthorized",
            "message": "Missing or invalid bearer token",
        }
    }


def test_register_relay_and_two_agents(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    register_relay(client)
    upsert_agent(client, "alice-codex-api")
    upsert_agent(client, "alice-claude-ui")

    response = client.get("/api/agents", headers=auth())

    assert response.status_code == 200
    agents = response.json()["agents"]
    assert [agent["short_id"] for agent in agents] == ["alice-claude-ui", "alice-codex-api"]
    assert all(agent["status"] == "idle" for agent in agents)


def test_register_relay_stores_lan_ip(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    response = client.post(
        "/api/relays/register",
        headers=auth(),
        json={
            "machine_id": "machine-a",
            "host_name": "host-a",
            "user_name": "alice",
            "lan_ip": "10.0.0.23",
        },
    )

    assert response.status_code == 200
    assert response.json()["lan_ip"] == "10.0.0.23"


def test_default_lan_ip_can_be_overridden(monkeypatch) -> None:
    monkeypatch.setenv("AGENTTALK_LAN_IP", "10.9.8.7")

    assert default_lan_ip() == "10.9.8.7"


def test_get_agent_detail(tmp_path: Path) -> None:
    client = make_client(tmp_path)
    register_relay(client)
    upsert_agent(client, "alice-codex-api")

    response = client.get("/api/agents/alice-codex-api", headers=auth())

    assert response.status_code == 200


def test_hub_auto_resume_stops_after_agent_is_working(monkeypatch, tmp_path: Path) -> None:
    class FakeSession:
        def __init__(self) -> None:
            self.writes: list[str] = []

        def write(self, data: str) -> None:
            self.writes.append(data)

    class FakePtyManager:
        def __init__(self) -> None:
            self.session = FakeSession()

        def get_or_create(self, _short_id: str, _tmux_target: str) -> FakeSession:
            return self.session

    fake_pty = FakePtyManager()
    monkeypatch.setattr(hub_app_module, "pty_manager", fake_pty)
    client = make_client(tmp_path)
    register_relay(client)
    upsert_agent(client, "alice-codex-api")
    client.post("/api/config/llm", headers=auth(), json={"enabled": True})

    payload = {
        "short_id": "alice-codex-api",
        "pane_alive": True,
        "process_alive": True,
        "recent_output": "Selected model is at capacity",
        "output_fingerprint": "pause-fp",
        "detected_errors": [],
        "detected_pauses": ["selected model is at capacity"],
        "status": "idle",
    }

    first = client.post("/api/agents/alice-codex-api/health", headers=auth(), json=payload)
    second = client.post("/api/agents/alice-codex-api/health", headers=auth(), json=payload)

    assert first.status_code == 200
    assert second.status_code == 200
    assert fake_pty.session.writes == ["继续\n"]


def test_hub_auto_resume_does_not_fire_for_working_report(monkeypatch, tmp_path: Path) -> None:
    class FakePtyManager:
        def __init__(self) -> None:
            self.writes: list[str] = []

        def get_or_create(self, _short_id: str, _tmux_target: str):
            raise AssertionError("working reports must not trigger Hub auto-resume")

    fake_pty = FakePtyManager()
    monkeypatch.setattr(hub_app_module, "pty_manager", fake_pty)
    client = make_client(tmp_path)
    register_relay(client)
    upsert_agent(client, "alice-codex-api")
    client.post("/api/config/llm", headers=auth(), json={"enabled": True})

    response = client.post(
        "/api/agents/alice-codex-api/health",
        headers=auth(),
        json={
            "short_id": "alice-codex-api",
            "pane_alive": True,
            "process_alive": True,
            "recent_output": "Selected model is at capacity",
            "output_fingerprint": "pause-fp",
            "detected_errors": [],
            "detected_pauses": ["selected model is at capacity"],
            "status": "working",
        },
    )

    assert response.status_code == 200
    assert response.json()["short_id"] == "alice-codex-api"


def test_missing_agent_returns_error_shape(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    response = client.get("/api/agents/missing-agent", headers=auth())

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "agent_not_found"


def test_unknown_relay_cannot_own_agent(tmp_path: Path) -> None:
    client = make_client(tmp_path)

    response = client.put(
        "/api/agents",
        headers=auth(),
        json={
            "short_id": "alice-codex-api",
            "machine_id": "missing-machine",
            "owner": "alice",
            "kind": "codex",
            "workspace": "/workspace/project",
            "tmux_target": "dev:0.1",
            "receive_mode": "auto_submit",
            "status": "idle",
        },
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "relay_not_found"


def test_stale_heartbeat_derives_offline(tmp_path: Path) -> None:
    client = make_client(tmp_path, heartbeat_ttl_seconds=-1)
    register_relay(client)
    upsert_agent(client, "alice-codex-api")

    response = client.get("/api/agents/alice-codex-api", headers=auth())

    assert response.status_code == 200
    assert response.json()["status"] == "offline"
