from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass

from agenttalk.config import AgentTalkConfig
from agenttalk.hub.client import HubClient
from agenttalk.hub.models import AgentHealthReport, AgentStatus, MessageStatus, ReceiveMode
from agenttalk.tmux import TmuxClient, TmuxPane, is_process_alive


@dataclass(frozen=True)
class RelaySyncResult:
    upserted: int
    online: int
    offline: int


@dataclass
class WatchState:
    target: str
    baseline: str
    done_marker: str


@dataclass
class AgentHealthState:
    short_id: str
    last_output_fingerprint: str = ""
    last_status: AgentStatus = AgentStatus.IDLE
    consecutive_errors: int = 0


ERROR_PATTERNS = [
    "error", "error:", "error-",
    "traceback", "traceback:",
    "failed", "failed:", "fail:",
    "timeout", "timeout:",
    "connection refused", "connection error",
    "rate limit", "rate-limit", "too many requests", "429",
    "unauthorized", "401", "403", "forbidden",
    "quota exceeded", "quota limit",
    "econnrefused", "enotfound", "etimedout",
    "panic:", "fatal:", "fatal error",
    "out of memory", "oom", "killed",
    "interrupted", "keyboardinterrupt",
    "npm err", "pip err", "cargo err",
    "api error", "apierror",
    "anthropic error", "openai error", "google api error", "gemini error",
    "i'm sorry, but i encountered an error",
    "i apologize, but",
    "something went wrong",
    "service unavailable", "503",
    "bad gateway", "502",
    "gateway timeout", "504",
    "internal server error", "500",
    "invalid request", "bad request", "400",
    "not found", "404",
    "max retries exceeded",
    "unable to connect",
    "network is unreachable",
    "dns error",
    "ssl error", "tls error",
    "certificate error",
]


def detect_errors(output: str) -> list[str]:
    output_lower = output.lower()
    found: list[str] = []
    for pattern in ERROR_PATTERNS:
        if pattern in output_lower:
            found.append(pattern)
    return list(set(found))


def output_fingerprint(output: str) -> str:
    return hashlib.sha256(output.encode()).hexdigest()[:16]


class AgentTalkRelay:
    def __init__(self, config: AgentTalkConfig, *, hub_client: HubClient, tmux_client: TmuxClient) -> None:
        self.config = config
        self.hub_client = hub_client
        self.tmux_client = tmux_client
        self.watch_states: dict[str, WatchState] = {}
        self.health_states: dict[str, AgentHealthState] = {}

    def sync_once(self) -> RelaySyncResult:
        self.hub_client.register_relay(self.config)
        panes = self.tmux_client.list_panes()
        pane_targets = {pane.target: pane for pane in panes}
        pane_ids = {pane.pane_id: pane for pane in panes}
        online = 0
        offline = 0
        for binding in self.config.agents:
            pane = pane_targets.get(binding.tmux_target) or pane_ids.get(binding.pane_id)
            if pane is None:
                offline += 1
                self.hub_client.upsert_agent(self.config, binding, AgentStatus.OFFLINE)
                continue
            
            online += 1
            health = self._check_agent_health(binding, pane)
            self.hub_client.report_health(health)
            self.hub_client.upsert_agent(self.config, binding, health.status)
        return RelaySyncResult(upserted=len(self.config.agents), online=online, offline=offline)

    def _check_agent_health(self, binding, pane: TmuxPane) -> AgentHealthReport:
        state = self.health_states.get(binding.short_id)
        if state is None:
            state = AgentHealthState(short_id=binding.short_id)
            self.health_states[binding.short_id] = state

        pane_alive = True
        process_alive = True
        recent_output = ""
        detected_errors: list[str] = []
        current_fingerprint = ""

        try:
            recent_output = self.tmux_client.capture_pane(binding.tmux_target, lines=50)
            current_fingerprint = output_fingerprint(recent_output)
            detected_errors = detect_errors(recent_output)
        except Exception:
            pane_alive = False

        if pane_alive and pane.pane_pid is not None:
            process_alive = is_process_alive(pane.pane_pid)

        if not pane_alive:
            status = AgentStatus.CRASHED
        elif not process_alive:
            status = AgentStatus.CRASHED
        elif detected_errors:
            status = AgentStatus.ERROR
            state.consecutive_errors += 1
        elif state.last_output_fingerprint and current_fingerprint != state.last_output_fingerprint:
            status = AgentStatus.WORKING
            state.consecutive_errors = 0
        else:
            status = AgentStatus.IDLE
            state.consecutive_errors = 0

        state.last_output_fingerprint = current_fingerprint
        state.last_status = status

        return AgentHealthReport(
            short_id=binding.short_id,
            pane_alive=pane_alive,
            process_alive=process_alive,
            recent_output=recent_output[-500:] if recent_output else "",
            output_fingerprint=current_fingerprint,
            detected_errors=detected_errors,
            status=status,
        )

    def run_forever(self, *, interval_seconds: float = 5.0) -> None:
        while True:
            self.sync_once()
            self.process_next_message_once()
            self.hub_client.heartbeat(self.config.machine_id)
            time.sleep(interval_seconds)

    def process_next_message_once(self) -> bool:
        message = self.hub_client.next_message(self.config.machine_id)
        if message is None:
            return False
        binding = next((agent for agent in self.config.agents if agent.short_id == message["target"]), None)
        if binding is None:
            self.hub_client.update_message_status(
                message["message_id"],
                MessageStatus.FAILED,
                "Target binding not found on relay",
            )
            return True
        payload = build_injected_message(
            message_id=message["message_id"],
            sender=message["sender"],
            target=message["target"],
            body=message["body"],
            done_marker=message["done_marker"],
        )
        try:
            baseline = self.tmux_client.capture_pane(binding.tmux_target, lines=500)
            self.tmux_client.inject_text(
                binding.tmux_target,
                payload,
                submit=binding.receive_mode == ReceiveMode.AUTO_SUBMIT,
            )
        except Exception as exc:
            self.hub_client.update_message_status(message["message_id"], MessageStatus.FAILED, str(exc))
            return True
        self.hub_client.update_message_status(message["message_id"], MessageStatus.INJECTED)
        self.watch_states[message["message_id"]] = WatchState(
            target=binding.tmux_target,
            baseline=baseline,
            done_marker=message["done_marker"],
        )
        return True

    def update_watches_once(self) -> int:
        completed: list[str] = []
        updates = 0
        for message_id, state in list(self.watch_states.items()):
            output = self.tmux_client.capture_pane(state.target, lines=800)
            delta = output_delta(state.baseline, output)
            if not delta:
                continue
            done = state.done_marker in delta
            response_text = delta.replace(state.done_marker, "").rstrip()
            self.hub_client.update_message_response(message_id, response_text, completed=done)
            if done:
                completed.append(message_id)
            else:
                self.hub_client.update_message_status(message_id, MessageStatus.WORKING)
            updates += 1
        for message_id in completed:
            self.watch_states.pop(message_id, None)
        return updates

    def sync_context_once(self, *, lines: int = 200) -> int:
        count = 0
        for binding in self.config.agents:
            try:
                context = self.tmux_client.capture_pane(binding.tmux_target, lines=lines)
            except Exception:
                continue
            self.hub_client.update_agent_context(binding.short_id, context)
            count += 1
        return count


class StaticTmuxClient(TmuxClient):
    def __init__(self, panes: list[TmuxPane]) -> None:
        self._panes = panes
        self.captures: dict[str, str] = {}

    def list_panes(self) -> list[TmuxPane]:
        return self._panes

    def capture_pane(self, target: str, *, lines: int = 300) -> str:
        return self.captures.get(target, "")


def build_injected_message(*, message_id: str, sender: str, target: str, body: str, done_marker: str) -> str:
    return "\n".join(
        [
            "[AgentTalk Message]",
            f"message_id: {message_id}",
            f"from: {sender}",
            f"to: {target}",
            "",
            "Task:",
            body.strip(),
            "",
            "When done, print this exact marker on its own line:",
            done_marker,
            "",
        ]
    )


def output_delta(baseline: str, current: str) -> str:
    if current.startswith(baseline):
        return current[len(baseline) :]
    baseline_lines = baseline.splitlines()
    current_lines = current.splitlines()
    max_overlap = min(len(baseline_lines), len(current_lines))
    for size in range(max_overlap, 0, -1):
        if baseline_lines[-size:] == current_lines[:size]:
            return "\n".join(current_lines[size:])
    return current
