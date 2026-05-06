from __future__ import annotations

import subprocess
from dataclasses import dataclass


TMUX_LIST_FORMAT = "#{session_name}:#{window_index}.#{pane_index}|#{pane_id}|#{pane_current_command}|#{pane_current_path}|#{pane_title}"


@dataclass(frozen=True)
class TmuxPane:
    target: str
    pane_id: str
    command: str
    current_path: str
    title: str
    kind: str


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


def parse_list_panes(output: str) -> list[TmuxPane]:
    panes: list[TmuxPane] = []
    for line in output.splitlines():
        if not line.strip():
            continue
        parts = line.split("|", 4)
        if len(parts) != 5:
            continue
        target, pane_id, command, current_path, title = parts
        panes.append(
            TmuxPane(
                target=target,
                pane_id=pane_id,
                command=command,
                current_path=current_path,
                title=title,
                kind=detect_agent_kind(command=command, title=title),
            )
        )
    return panes


def detect_agent_kind(*, command: str, title: str = "") -> str:
    haystack = f"{command} {title}".lower()
    for kind in ("claude", "codex", "gemini"):
        if kind in haystack:
            return kind
    return "unknown"
