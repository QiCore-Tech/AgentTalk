from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass


TMUX_LIST_FORMAT = "#{session_name}:#{window_index}.#{pane_index}|#{pane_id}|#{pane_current_command}|#{pane_current_path}|#{pane_title}|#{pane_pid}"


@dataclass(frozen=True)
class TmuxPane:
    target: str
    pane_id: str
    command: str
    current_path: str
    title: str
    kind: str
    pane_pid: int | None


class TmuxClient:
    def list_panes(self) -> list[TmuxPane]:
        proc = subprocess.run(
            ["tmux", "list-panes", "-a", "-F", TMUX_LIST_FORMAT],
            text=True,
            capture_output=True,
            check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.strip() or "tmux list-panes failed")
        return parse_list_panes(proc.stdout)

    def get_pane_pid(self, target: str) -> int | None:
        proc = subprocess.run(
            ["tmux", "list-panes", "-t", target, "-F", "#{pane_pid}"],
            text=True,
            capture_output=True,
            check=False,
        )
        if proc.returncode != 0:
            return None
        try:
            return int(proc.stdout.strip().splitlines()[0])
        except (ValueError, IndexError):
            return None

    def inject_text(self, target: str, text: str, *, submit: bool) -> None:
        proc = subprocess.run(
            ["tmux", "send-keys", "-t", target, "-l", text],
            text=True,
            capture_output=True,
            check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.strip() or "tmux send-keys failed")
        if submit:
            enter = subprocess.run(
                ["tmux", "send-keys", "-t", target, "Enter"],
                text=True,
                capture_output=True,
                check=False,
            )
            if enter.returncode != 0:
                raise RuntimeError(enter.stderr.strip() or "tmux submit failed")

    def capture_pane(self, target: str, *, lines: int = 300) -> str:
        start = f"-{max(lines, 1)}"
        proc = subprocess.run(
            ["tmux", "capture-pane", "-p", "-t", target, "-S", start],
            text=True,
            capture_output=True,
            check=False,
        )
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.strip() or "tmux capture-pane failed")
        return proc.stdout


def parse_list_panes(output: str) -> list[TmuxPane]:
    panes: list[TmuxPane] = []
    for line in output.splitlines():
        if not line.strip():
            continue
        parts = line.split("|", 5)
        if len(parts) != 6:
            continue
        target, pane_id, command, current_path, title, pid_str = parts
        try:
            pane_pid = int(pid_str)
        except ValueError:
            pane_pid = None
        panes.append(
            TmuxPane(
                target=target,
                pane_id=pane_id,
                command=command,
                current_path=current_path,
                title=title,
                kind=detect_agent_kind(command=command, title=title),
                pane_pid=pane_pid,
            )
        )
    return panes


def detect_agent_kind(*, command: str, title: str = "") -> str:
    haystack = f"{command} {title}".lower()
    for kind in ("claude", "codex", "gemini", "opencode"):
        if kind in haystack:
            return kind
    return "unknown"


def is_process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False
