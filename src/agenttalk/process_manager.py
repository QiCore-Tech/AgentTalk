from __future__ import annotations

import abc
import hashlib
import json
import os
import platform
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

SUBMIT_INITIAL_DELAY_SECONDS = 0.4
SUBMIT_RETRY_DELAY_SECONDS = 0.35
SUBMIT_MAX_ATTEMPTS = 5


@dataclass(frozen=True)
class ManagedProcess:
    target: str  # 进程标识符（类似 tmux target）
    pane_id: str  #  Pane ID（Windows 下复用为 PID 字符串）
    command: str  # 启动命令
    current_path: str  # 工作目录
    title: str  # 标题/描述
    kind: str  # agent 类型
    pane_pid: int | None  # 进程 PID


@dataclass(frozen=True)
class InjectionResult:
    pasted: bool
    submit_requested: bool
    submit_confirmed: bool
    pending_input_detected: bool
    attempts: int = 0


class ProcessManager(abc.ABC):
    """跨平台进程管理抽象接口。"""

    @abc.abstractmethod
    def list_processes(self) -> list[ManagedProcess]:
        """列出所有被管理的进程。"""

    @abc.abstractmethod
    def get_process_pid(self, target: str) -> int | None:
        """获取目标进程的 PID。"""

    @abc.abstractmethod
    def inject_text(self, target: str, text: str, *, submit: bool) -> InjectionResult | None:
        """向目标进程注入文本。"""

    @abc.abstractmethod
    def capture_output(self, target: str, *, lines: int = 300) -> str:
        """捕获目标进程最近输出。"""

    @abc.abstractmethod
    def start_process(
        self, target: str, command: list[str], cwd: str | None = None
    ) -> ManagedProcess:
        """启动新进程并纳入管理。"""


class TmuxProcessManager(ProcessManager):
    """Unix/Linux/macOS 上基于 tmux 的进程管理。"""

    TMUX_LIST_FORMAT = (
        "#{session_name}:#{window_index}.#{pane_index}"
        "|#{pane_id}|#{pane_current_command}"
        "|#{pane_current_path}|#{pane_title}|#{pane_pid}"
    )

    def list_processes(self) -> list[ManagedProcess]:
        proc = subprocess.run(
            ["tmux", "list-panes", "-a", "-F", self.TMUX_LIST_FORMAT],
            text=True,
            capture_output=True,
            check=False,
        )
        if proc.returncode != 0:
            return []
        return self._parse_panes(proc.stdout)

    def _parse_panes(self, output: str) -> list[ManagedProcess]:
        processes: list[ManagedProcess] = []
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
            processes.append(
                ManagedProcess(
                    target=target,
                    pane_id=pane_id,
                    command=command,
                    current_path=current_path,
                    title=title,
                    kind=_detect_agent_kind(command=command, title=title),
                    pane_pid=pane_pid,
                )
            )
        return processes

    def get_process_pid(self, target: str) -> int | None:
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

    def inject_text(self, target: str, text: str, *, submit: bool) -> InjectionResult:
        buffer_name = f"agenttalk-{os.getpid()}-{time.time_ns()}"
        load = subprocess.run(
            ["tmux", "load-buffer", "-b", buffer_name, "-"],
            input=text,
            text=True,
            capture_output=True,
            check=False,
        )
        if load.returncode != 0:
            raise RuntimeError(load.stderr.strip() or "tmux load-buffer failed")
        try:
            paste = subprocess.run(
                ["tmux", "paste-buffer", "-t", target, "-b", buffer_name],
                text=True,
                capture_output=True,
                check=False,
            )
            if paste.returncode != 0:
                raise RuntimeError(paste.stderr.strip() or "tmux paste-buffer failed")
        finally:
            subprocess.run(
                ["tmux", "delete-buffer", "-b", buffer_name],
                text=True,
                capture_output=True,
                check=False,
            )
        if not submit:
            return InjectionResult(
                pasted=True,
                submit_requested=False,
                submit_confirmed=False,
                pending_input_detected=True,
                attempts=0,
            )
        submit_confirmed, pending_input_detected, attempts = self._submit_once(target)
        return InjectionResult(
            pasted=True,
            submit_requested=True,
            submit_confirmed=submit_confirmed,
            pending_input_detected=pending_input_detected,
            attempts=attempts,
        )

    def _submit_once(self, target: str) -> tuple[bool, bool, int]:
        """Submit pasted input, retrying only when the prompt still looks pending.

        Codex/Claude TUIs can need a short beat after a tmux paste before Enter
        is interpreted as "submit" rather than another editor keystroke. This is
        most visible for long AgentTalk messages, where the input box keeps the
        pasted prompt and humans have to press Enter again. We therefore delay
        the first submit slightly and only send follow-up Enter keys when the
        terminal tail still appears to contain an unsubmitted AgentTalk prompt.
        """

        time.sleep(SUBMIT_INITIAL_DELAY_SECONDS)
        for attempt in range(SUBMIT_MAX_ATTEMPTS):
            attempt_count = attempt + 1
            submit = subprocess.run(
                ["tmux", "send-keys", "-t", target, "Enter"],
                text=True,
                capture_output=True,
                check=False,
            )
            if submit.returncode != 0:
                raise RuntimeError(submit.stderr.strip() or "tmux submit failed")
            if self._wait_for_active_submission(target):
                return True, False, attempt_count
            if attempt + 1 >= SUBMIT_MAX_ATTEMPTS:
                break
            try:
                output = self.capture_output(target, lines=80)
            except Exception:
                return False, False, attempt_count
            pending_input = _tail_shows_pending_agenttalk_input(output)
            if not pending_input:
                return True, False, attempt_count
            time.sleep(SUBMIT_RETRY_DELAY_SECONDS)
        try:
            output = self.capture_output(target, lines=80)
        except Exception:
            return False, False, SUBMIT_MAX_ATTEMPTS
        return False, _tail_shows_pending_agenttalk_input(output), SUBMIT_MAX_ATTEMPTS

    def _wait_for_active_submission(self, target: str, *, timeout: float = 2.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                output = self.capture_output(target, lines=80)
            except Exception:
                return False
            if _tail_shows_active_agent_submission(output):
                return True
            time.sleep(0.25)
        return False

    def capture_output(self, target: str, *, lines: int = 300) -> str:
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

    def start_process(
        self, target: str, command: list[str], cwd: str | None = None
    ) -> ManagedProcess:
        session_name, _, pane_spec = target.partition(":")
        window_idx, _, _ = pane_spec.partition(".")
        if not window_idx:
            window_idx = "0"

        # 创建 session + window
        subprocess.run(
            ["tmux", "new-session", "-d", "-s", session_name, "-n", window_idx],
            text=True,
            capture_output=True,
            check=False,
        )
        # 启动命令
        cmd_str = subprocess.list2cmdline(command)
        subprocess.run(
            ["tmux", "send-keys", "-t", target, "-l", cmd_str, "Enter"],
            text=True,
            capture_output=True,
            check=False,
        )
        time.sleep(0.5)
        processes = self.list_processes()
        for p in processes:
            if p.target == target:
                return p
        raise RuntimeError(f"Failed to start process in tmux: {target}")


class SubprocessProcessManager(ProcessManager):
    """Windows 上基于 subprocess 的进程管理（无需 tmux）。

    每个 agent 作为独立 subprocess 运行，输出重定向到日志文件，
    输入通过 stdin pipe 注入。
    """

    def __init__(self, registry_path: Path | None = None) -> None:
        if registry_path is None:
            registry_path = Path.home() / ".agenttalk" / "process_registry.json"
        self._registry_path = registry_path
        self._registry_path.parent.mkdir(parents=True, exist_ok=True)
        self._procs: dict[str, subprocess.Popen[str]] = {}
        self._load_registry()

    def _load_registry(self) -> None:
        if self._registry_path.exists():
            try:
                data = json.loads(self._registry_path.read_text(encoding="utf-8"))
                for key, val in data.items():
                    pid = val.get("pid")
                    if pid and is_process_alive(pid):
                        self._procs[key] = None  # 标记为外部进程，不持有引用
            except Exception:
                pass

    def _save_registry(self) -> None:
        data: dict[str, dict[str, Any]] = {}
        for key in self._procs:
            pid = self.get_process_pid(key)
            if pid:
                data[key] = {"pid": pid, "updated_at": time.time()}
        self._registry_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def list_processes(self) -> list[ManagedProcess]:
        processes: list[ManagedProcess] = []
        if self._registry_path.exists():
            try:
                data = json.loads(self._registry_path.read_text(encoding="utf-8"))
                for target, info in data.items():
                    pid = info.get("pid")
                    if pid and is_process_alive(pid):
                        # 尝试从进程获取命令行
                        cmd = self._get_process_cmdline(pid) or "unknown"
                        processes.append(
                            ManagedProcess(
                                target=target,
                                pane_id=str(pid),
                                command=cmd,
                                current_path="",
                                title=target,
                                kind=_detect_agent_kind(command=cmd),
                                pane_pid=pid,
                            )
                        )
            except Exception:
                pass
        return processes

    def _get_process_cmdline(self, pid: int) -> str | None:
        try:
            import psutil

            proc = psutil.Process(pid)
            return " ".join(proc.cmdline())
        except Exception:
            return None

    def get_process_pid(self, target: str) -> int | None:
        if self._registry_path.exists():
            try:
                data = json.loads(self._registry_path.read_text(encoding="utf-8"))
                return data.get(target, {}).get("pid")
            except Exception:
                pass
        return None

    def inject_text(self, target: str, text: str, *, submit: bool) -> InjectionResult:
        # Windows 下通过 stdin 注入
        proc = self._procs.get(target)
        if proc is None:
            # 尝试重新 attach
            pid = self.get_process_pid(target)
            if pid is None:
                raise RuntimeError(f"Process not found: {target}")
            # 外部启动的进程无法通过 stdin 注入
            # 回退到剪贴板或 API 方式
            raise RuntimeError(
                f"Cannot inject to external process {target} on Windows. "
                "Please use the agent's native API or restart via AgentTalk."
            )
        if proc.stdin is None:
            raise RuntimeError(f"Process stdin not available: {target}")
        proc.stdin.write(text)
        if submit:
            proc.stdin.write(os.linesep)
        proc.stdin.flush()
        return InjectionResult(
            pasted=True,
            submit_requested=submit,
            submit_confirmed=submit,
            pending_input_detected=not submit,
            attempts=1 if submit else 0,
        )

    def capture_output(self, target: str, *, lines: int = 300) -> str:
        log_file = self._log_path(target)
        if not log_file.exists():
            return ""
        content = log_file.read_text(encoding="utf-8", errors="replace")
        all_lines = content.splitlines()
        return "\n".join(all_lines[-max(lines, 1) :])

    def start_process(
        self, target: str, command: list[str], cwd: str | None = None
    ) -> ManagedProcess:
        log_file = self._log_path(target)
        log_file.parent.mkdir(parents=True, exist_ok=True)
        # 启动进程，stdout/stderr 重定向到日志文件
        with open(log_file, "a", encoding="utf-8") as f:
            proc = subprocess.Popen(
                command,
                stdout=f,
                stderr=subprocess.STDOUT,
                stdin=subprocess.PIPE,
                text=True,
                cwd=cwd,
                creationflags=subprocess.CREATE_NEW_PROCESS_GROUP
                if platform.system() == "Windows"
                else 0,
            )
        self._procs[target] = proc
        self._save_registry()
        return ManagedProcess(
            target=target,
            pane_id=str(proc.pid),
            command=subprocess.list2cmdline(command),
            current_path=cwd or "",
            title=target,
            kind=_detect_agent_kind(command=command[0] if command else ""),
            pane_pid=proc.pid,
        )

    def _log_path(self, target: str) -> Path:
        safe = target.replace(":", "_").replace(".", "_")
        return self._registry_path.parent / "logs" / f"{safe}.log"


def _detect_agent_kind(*, command: str, title: str = "") -> str:
    haystack = f"{command} {title}".lower()
    for kind in ("claude", "codex", "gemini", "opencode"):
        if kind in haystack:
            return kind
    return "unknown"


def _tail_shows_active_agent_submission(output: str) -> bool:
    tail = "\n".join(output.splitlines()[-30:])
    if "Working (" in tail or "esc to interrupt" in tail:
        return True
    active_statuses = (
        "Crystallizing",
        "Synthesizing",
        "Blanching",
        "Sautéing",
        "Churning",
        "Ionizing",
        "Thinking",
        "Working",
    )
    spinner_prefixes = ("·", "✢", "✻", "✶", "✺", "✷", "✸", "✹")
    for line in (line.strip() for line in tail.splitlines()[-10:]):
        if not line:
            continue
        if not any(line.startswith(prefix) for prefix in spinner_prefixes):
            continue
        if any(status in line for status in active_statuses):
            return True
    return False


def _tail_shows_pending_agenttalk_input(output: str) -> bool:
    """Return True when the bottom of a pane still looks like unsent input.

    This intentionally looks only at the terminal tail. Submitted prompts are
    often echoed into scrollback, so seeing an AgentTalk marker anywhere is not
    enough. We only retry when the marker is close to the bottom and there is no
    evidence that the agent has started or completed a response after it.
    """

    tail_lines = output.splitlines()[-30:]
    if not tail_lines:
        return False

    marker_index: int | None = None
    markers = (
        "[AgentTalk Message]",
        "[Pasted Content",
        "Full task is stored at",
        "message_id:",
        "<<<AGENTTALK_DONE:",
    )
    for index, line in enumerate(tail_lines):
        if any(marker in line for marker in markers):
            marker_index = index
    if marker_index is None:
        return False

    # Old scrollback should not trigger another Enter.
    if marker_index < max(len(tail_lines) - 12, 0):
        return False

    after_marker = tail_lines[marker_index + 1 :]
    response_indicators = (
        "<<<AGENTTALK_DONE:",
        "• ",
        "● ",
        "Ran ",
        "Explored",
        "Edited",
        "Findings:",
        "Verdict:",
        "ACCEPT",
        "CONDITIONAL_ACCEPT",
        "REVISE",
    )
    if any(any(indicator in line for indicator in response_indicators) for line in after_marker):
        return False
    if _tail_shows_active_agent_submission("\n".join(tail_lines)):
        return False

    prompt_window = tail_lines[max(marker_index - 2, 0) : marker_index + 1]
    if any(line.lstrip().startswith(("›", ">")) for line in prompt_window):
        return True
    # Wrapped input can push the prompt glyph above the captured marker line.
    return marker_index >= len(tail_lines) - 4


def is_process_alive(pid: int) -> bool:
    """跨平台进程存活检测。"""
    if platform.system() == "Windows":
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32
            handle = kernel32.OpenProcess(1, False, pid)  # PROCESS_TERMINATE = 1
            if handle:
                kernel32.CloseHandle(handle)
                return True
            return False
        except Exception:
            return False
    else:
        try:
            os.kill(pid, 0)
            return True
        except (OSError, ProcessLookupError):
            return False


def get_process_manager() -> ProcessManager:
    """根据平台返回合适的进程管理器。"""
    if platform.system() == "Windows":
        return SubprocessProcessManager()
    # Unix/Linux/macOS：先检测 tmux 是否可用
    try:
        subprocess.run(["tmux", "-V"], capture_output=True, check=True)
        return TmuxProcessManager()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return SubprocessProcessManager()


def output_fingerprint(output: str) -> str:
    return hashlib.sha256(output.encode()).hexdigest()[:16]
