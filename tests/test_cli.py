from __future__ import annotations

from typer.testing import CliRunner

from agenttalk.cli import app


def test_list_requires_token() -> None:
    runner = CliRunner()

    result = runner.invoke(app, ["list"])

    assert result.exit_code != 0
    assert "Token is required" in result.output
