from __future__ import annotations

from typer.testing import CliRunner

from agenttalk.config import load_config
from agenttalk.cli import app


def test_list_requires_token() -> None:
    runner = CliRunner()

    result = runner.invoke(app, ["list"])

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
