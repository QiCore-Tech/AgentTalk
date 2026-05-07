from __future__ import annotations

from agenttalk.feishu.commands import FeishuCommandKind, parse_command


def test_parse_empty_command_returns_help() -> None:
    command = parse_command("  ")

    assert command.kind == FeishuCommandKind.HELP


def test_parse_agents_online_command() -> None:
    command = parse_command("/agents online")

    assert command.kind == FeishuCommandKind.AGENTS
    assert command.args == ("online",)


def test_parse_send_preserves_message_spaces() -> None:
    command = parse_command("/send alice-codex-api please review API contract")

    assert command.kind == FeishuCommandKind.SEND
    assert command.args == ("alice-codex-api", "please review API contract")


def test_parse_missing_send_body_returns_usage_error() -> None:
    command = parse_command("/send alice-codex-api")

    assert command.kind == FeishuCommandKind.SEND
    assert command.error == "Usage: /send <agent-id> <message>"


def test_parse_unknown_command() -> None:
    command = parse_command("/nope")

    assert command.kind == FeishuCommandKind.UNKNOWN
    assert command.error == "Unknown command: /nope"
