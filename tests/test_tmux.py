from __future__ import annotations

from agenttalk.tmux import detect_agent_kind, parse_list_panes


def test_parse_list_panes_detects_agent_kinds() -> None:
    output = "\n".join(
        [
            "dev:0.1|%1|claude|/workspace/a|Claude",
            "dev:0.2|%2|codex|/workspace/b|Codex",
            "api:1.0|%3|node|/workspace/c|Gemini CLI",
            "misc:0.0|%4|zsh|/workspace/d|shell",
        ]
    )

    panes = parse_list_panes(output)

    assert [pane.kind for pane in panes] == ["claude", "codex", "gemini", "unknown"]
    assert panes[0].target == "dev:0.1"
    assert panes[0].pane_id == "%1"
    assert panes[0].current_path == "/workspace/a"


def test_detect_agent_kind_is_case_insensitive() -> None:
    assert detect_agent_kind(command="Claude") == "claude"
    assert detect_agent_kind(command="node", title="CODEX") == "codex"
    assert detect_agent_kind(command="gemini") == "gemini"
    assert detect_agent_kind(command="zsh") == "unknown"
