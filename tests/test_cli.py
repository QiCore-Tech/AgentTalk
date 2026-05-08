from __future__ import annotations

from typer.testing import CliRunner

from agenttalk.config import load_config
from agenttalk import cli
from agenttalk.cli import app


def test_list_requires_token() -> None:
    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(app, ["list", "--config-path", "missing-config.json"])

        assert result.exit_code != 0
        assert "Token is required" in result.output


def test_setup_saves_config(tmp_path) -> None:
    runner = CliRunner()
    config_path = tmp_path / "config.json"

    result = runner.invoke(
        app,
        [
            "setup",
            "http://hub.local:8787",
            "--token",
            "test-token",
            "--config-path",
            str(config_path),
        ],
    )

    assert result.exit_code == 0
    config = load_config(config_path)
    assert config.hub_url == "http://hub.local:8787"
    assert config.token == "test-token"


def test_register_without_sync_saves_binding(tmp_path) -> None:
    runner = CliRunner()
    config_path = tmp_path / "config.json"
    runner.invoke(app, ["setup", "http://hub.local:8787", "--token", "test-token", "--config-path", str(config_path)])

    result = runner.invoke(
        app,
        [
            "register",
            "--short-id",
            "alice-codex-api",
            "--tmux-target",
            "dev:0.1",
            "--owner",
            "alice",
            "--kind",
            "codex",
            "--workspace",
            "/workspace/api",
            "--pane-id",
            "%1",
            "--no-sync",
            "--config-path",
            str(config_path),
        ],
    )

    assert result.exit_code == 0
    config = load_config(config_path)
    assert config.agents[0].short_id == "alice-codex-api"


def test_send_watch_calls_watcher_with_message_id_keyword(monkeypatch) -> None:
    runner = CliRunner()
    watched: dict[str, object] = {}

    class FakeResponse:
        status_code = 200
        text = ""

        def json(self) -> dict[str, str]:
            return {
                "message_id": "msg-1",
                "target": "alice-codex-api",
                "status": "sent",
                "done_marker": "<<<AGENTTALK_DONE:msg-1>>>",
            }

    def fake_post(*args, **kwargs) -> FakeResponse:
        return FakeResponse()

    def fake_watch_message(*, message_id: str, resolved_hub_url: str, resolved_token: str, timeout: int) -> None:
        watched.update(
            {
                "message_id": message_id,
                "resolved_hub_url": resolved_hub_url,
                "resolved_token": resolved_token,
                "timeout": timeout,
            }
        )

    monkeypatch.setattr(cli.httpx, "post", fake_post)
    monkeypatch.setattr(cli, "watch_message", fake_watch_message)

    result = runner.invoke(
        app,
        [
            "send",
            "--to",
            "alice-codex-api",
            "--message",
            "Please review.",
            "--hub-url",
            "http://hub.local:8787",
            "--token",
            "test-token",
            "--watch",
            "--timeout",
            "5",
        ],
    )

    assert result.exit_code == 0
    assert watched == {
        "message_id": "msg-1",
        "resolved_hub_url": "http://hub.local:8787",
        "resolved_token": "test-token",
        "timeout": 5,
    }
