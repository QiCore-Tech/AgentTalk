from __future__ import annotations

from types import SimpleNamespace

import agenttalk.process_manager as process_manager
from agenttalk.process_manager import _detect_agent_kind as detect_agent_kind
from agenttalk.process_manager import _tail_shows_active_agent_submission
from agenttalk.process_manager import _tail_shows_codex_queue_prompt
from agenttalk.process_manager import _tail_shows_pending_agenttalk_input
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


def test_inject_text_auto_submit_uses_single_enter(monkeypatch) -> None:
    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(process_manager.subprocess, "run", fake_run)
    monkeypatch.setattr(
        TmuxProcessManager,
        "_wait_for_active_submission",
        lambda self, target: False,
    )
    monkeypatch.setattr(TmuxProcessManager, "capture_output", lambda self, target, lines=80: "")
    monkeypatch.setattr(process_manager.time, "sleep", lambda _seconds: None)

    result = TmuxProcessManager().inject_text("dev:0.1", "large\nmessage", submit=True)

    submit_calls = [
        call for call in calls if call[:4] == ["tmux", "send-keys", "-t", "dev:0.1"]
    ]
    assert submit_calls == [["tmux", "send-keys", "-t", "dev:0.1", "Enter"]] * process_manager.SUBMIT_MAX_ATTEMPTS
    assert not result.submit_confirmed
    assert result.pending_input_detected


def test_inject_text_auto_submit_retries_when_agenttalk_input_still_pending(monkeypatch) -> None:
    calls: list[list[str]] = []
    captures = iter(
        ["› [AgentTalk Message] message_id: msg-1 from: a to: b"]
        * (process_manager.SUBMIT_MAX_ATTEMPTS - 1)
    )

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(process_manager.subprocess, "run", fake_run)
    monkeypatch.setattr(
        TmuxProcessManager,
        "_wait_for_active_submission",
        lambda self, target: False,
    )
    monkeypatch.setattr(
        TmuxProcessManager,
        "capture_output",
        lambda self, target, lines=80: next(captures),
    )
    monkeypatch.setattr(process_manager.time, "sleep", lambda _seconds: None)

    result = TmuxProcessManager().inject_text("dev:0.1", "large\nmessage", submit=True)

    submit_calls = [
        call for call in calls if call[:4] == ["tmux", "send-keys", "-t", "dev:0.1"]
    ]
    assert submit_calls == [
        ["tmux", "send-keys", "-t", "dev:0.1", "Enter"]
    ] * process_manager.SUBMIT_MAX_ATTEMPTS
    assert not result.submit_confirmed
    assert result.pending_input_detected


def test_inject_text_auto_submit_queues_busy_codex_input_with_tab(monkeypatch) -> None:
    calls: list[list[str]] = []
    captures = iter(
        [
            "\n".join(
                [
                    "Working (esc to interrupt)",
                    "› [AgentTalk Message] message_id: msg-1 from: a to: b",
                    "tab to queue message",
                ]
            ),
            "",
        ]
    )

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(process_manager.subprocess, "run", fake_run)
    monkeypatch.setattr(
        TmuxProcessManager,
        "_wait_for_active_submission",
        lambda self, target: False,
    )
    monkeypatch.setattr(
        TmuxProcessManager,
        "capture_output",
        lambda self, target, lines=80: next(captures),
    )
    monkeypatch.setattr(process_manager.time, "sleep", lambda _seconds: None)

    result = TmuxProcessManager().inject_text("dev:0.1", "large\nmessage", submit=True)

    submit_calls = [
        call for call in calls if call[:4] == ["tmux", "send-keys", "-t", "dev:0.1"]
    ]
    assert submit_calls == [
        ["tmux", "send-keys", "-t", "dev:0.1", "Enter"],
        ["tmux", "send-keys", "-t", "dev:0.1", "Tab"],
    ]
    assert result.submit_confirmed
    assert result.attempts == 2


def test_inject_text_auto_submit_does_not_assume_success_on_claude_weak_signal(monkeypatch) -> None:
    calls: list[list[str]] = []
    captures = iter([""] * process_manager.SUBMIT_MAX_ATTEMPTS)

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr(process_manager.subprocess, "run", fake_run)
    monkeypatch.setattr(
        TmuxProcessManager,
        "_wait_for_active_submission",
        lambda self, target: False,
    )
    monkeypatch.setattr(
        TmuxProcessManager,
        "capture_output",
        lambda self, target, lines=80: next(captures),
    )
    monkeypatch.setattr(process_manager.time, "sleep", lambda _seconds: None)

    result = TmuxProcessManager().inject_text("dev:0.1", "large\nmessage", submit=True)

    submit_calls = [
        call for call in calls if call[:4] == ["tmux", "send-keys", "-t", "dev:0.1"]
    ]
    assert submit_calls == [
        ["tmux", "send-keys", "-t", "dev:0.1", "Enter"]
    ] * process_manager.SUBMIT_MAX_ATTEMPTS
    assert not result.submit_confirmed
    assert result.pending_input_detected


def test_active_submission_detection_rejects_idle_completed_spinner() -> None:
    assert not _tail_shows_active_agent_submission("✻ Baked for 4m 42s")
    assert _tail_shows_active_agent_submission("✻ Thinking about task")
    assert _tail_shows_active_agent_submission("Working (esc to interrupt)")
    assert not _tail_shows_active_agent_submission(
        "\n".join(
            [
                "Working (esc to interrupt)",
                "› [AgentTalk Message] message_id: msg-1 from: a to: b",
                "tab to queue message",
            ]
        )
    )
    assert _tail_shows_active_agent_submission(
        "\n".join(
            [
                "› [AgentTalk Message] message_id: msg-1 from: a to: b",
                "✻ Thinking about task",
            ]
        )
    )


def test_pending_agenttalk_input_detection_is_tail_scoped() -> None:
    assert _tail_shows_pending_agenttalk_input(
        "header\n› [AgentTalk Message] message_id: msg-1 from: a to: b"
    )
    assert not _tail_shows_pending_agenttalk_input(
        "\n".join(
            [
                "› [AgentTalk Message] message_id: msg-1 from: a to: b",
                "• Ran pytest",
                "Verdict: ACCEPT",
            ]
        )
    )
    assert not _tail_shows_pending_agenttalk_input(
        "\n".join(["› [AgentTalk Message] message_id: msg-1"] + [f"line {i}" for i in range(20)])
    )
    assert _tail_shows_pending_agenttalk_input(
        "› [Pasted Content 1023 chars] exact marker on its own line: "
        "<<<AGENTTALK_DONE:msg-1>>>"
    )
    assert _tail_shows_codex_queue_prompt("› [AgentTalk Message] msg\n tab to queue message")
    assert _tail_shows_pending_agenttalk_input(
        "\n".join(
            [
                "Working (esc to interrupt)",
                "› [AgentTalk Message] message_id: msg-1 from: a to: b",
                "tab to queue message",
            ]
        )
    )
    assert not _tail_shows_pending_agenttalk_input(
        "\n".join(
            [
                "› [AgentTalk Message] message_id: msg-1 from: a to: b",
                "✻ Thinking about task",
            ]
        )
    )
