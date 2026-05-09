from __future__ import annotations

from types import SimpleNamespace

import agenttalk.process_manager as process_manager
from agenttalk.process_manager import _detect_agent_kind as detect_agent_kind
from agenttalk.process_manager import _tail_shows_active_agent_submission
from agenttalk.process_manager import TmuxProcessManager


def parse_list_panes(output: str):
    mgr = TmuxProcessManager()
    return mgr._parse_panes(output)


def test_parse_list_panes_detects_agent_kinds() -> None:
    output = "\n".join(
        [
            "dev:0.1|%1|claude|/workspace/a|Claude|1234",
            "dev:0.2|%2|codex|/workspace/b|Codex|1235",
            "api:1.0|%3|node|/workspace/c|Gemini CLI|1236",
            "misc:0.0|%4|zsh|/workspace/d|shell|1237",
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


def test_inject_text_uses_tmux_buffer_and_deletes_it(monkeypatch) -> None:
    calls: list[tuple[list[str], str | None]] = []

    def fake_run(cmd, *, input=None, **kwargs):
        calls.append((list(cmd), input))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(process_manager.subprocess, "run", fake_run)

    TmuxProcessManager().inject_text("dev:0.1", "line 1\nline 2", submit=False)

    assert calls[0][0][:4] == ["tmux", "load-buffer", "-b", calls[0][0][3]]
    assert calls[0][0][-1] == "-"
    assert calls[0][1] == "line 1\nline 2"
    assert calls[1][0][:4] == ["tmux", "paste-buffer", "-t", "dev:0.1"]
    assert calls[1][0][4:] == ["-b", calls[0][0][3]]
    assert calls[2][0] == ["tmux", "delete-buffer", "-b", calls[0][0][3]]
    assert not any(
        call[0][:5] == ["tmux", "send-keys", "-t", "dev:0.1", "-l"] for call in calls
    )


def test_inject_text_auto_submit_retries_equivalent_submit_keys(monkeypatch) -> None:
    calls: list[list[str]] = []
    submitted = iter([False, False, True])

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(process_manager.subprocess, "run", fake_run)
    monkeypatch.setattr(
        TmuxProcessManager,
        "_wait_for_active_submission",
        lambda self, target: next(submitted),
    )

    TmuxProcessManager().inject_text("dev:0.1", "large\nmessage", submit=True)

    submit_calls = [
        call for call in calls if call[:4] == ["tmux", "send-keys", "-t", "dev:0.1"]
    ]
    assert submit_calls == [
        ["tmux", "send-keys", "-t", "dev:0.1", "Enter"],
        ["tmux", "send-keys", "-t", "dev:0.1", "C-m"],
        ["tmux", "send-keys", "-t", "dev:0.1", "C-j"],
    ]


def test_active_submission_detection_rejects_idle_completed_spinner() -> None:
    assert not _tail_shows_active_agent_submission("✻ Baked for 4m 42s")
    assert _tail_shows_active_agent_submission("✻ Thinking about task")
    assert _tail_shows_active_agent_submission("Working (esc to interrupt)")
