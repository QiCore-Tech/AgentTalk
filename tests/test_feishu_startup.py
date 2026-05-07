from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from typer.testing import CliRunner

from agenttalk.cli import app as cli_app
from agenttalk.hub.app import create_app
from agenttalk.hub.settings import HubSettings


def test_hub_cli_rejects_feishu_enabled_without_credentials() -> None:
    runner = CliRunner()

    result = runner.invoke(cli_app, ["hub", "serve", "--token", "test-token", "--feishu-enable"])

    assert result.exit_code != 0
    assert "requires --feishu-app-id/--feishu-app-secret" in result.output


def test_hub_lifespan_starts_feishu_worker_when_enabled(tmp_path: Path, monkeypatch) -> None:
    started: dict[str, object] = {}

    class FakeMessenger:
        def __init__(self, app_id: str, app_secret: str) -> None:
            started["messenger"] = (app_id, app_secret)

    class FakeWorker:
        def __init__(self, *, app_id: str, app_secret: str, handler) -> None:  # noqa: ANN001
            started["worker"] = (app_id, app_secret)
            started["handler"] = handler

        def start_background(self) -> None:
            started["started"] = True

    monkeypatch.setattr("agenttalk.hub.app.LarkMessenger", FakeMessenger)
    monkeypatch.setattr("agenttalk.hub.app.FeishuLongConnectionWorker", FakeWorker)

    app = create_app(
        HubSettings(
            database_path=tmp_path / "hub.sqlite3",
            token="test-token",
            public_base_url="https://agenttalk.company.lan",
            feishu_enable=True,
            feishu_app_id="cli_xxx",
            feishu_app_secret="secret",
        )
    )

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert started["messenger"] == ("cli_xxx", "secret")
    assert started["worker"] == ("cli_xxx", "secret")
    assert started["started"] is True
