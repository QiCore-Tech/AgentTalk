from __future__ import annotations

import hashlib
import logging
import re
import time
from dataclasses import dataclass

from agenttalk.config import AgentTalkConfig
from agenttalk.hub.client import HubClient
from agenttalk.hub.models import AgentHealthReport, AgentStatus, MessageStatus, ReceiveMode
from agenttalk.process_manager import (
    ManagedProcess,
    ProcessManager,
    TmuxProcessManager,
    is_process_alive,
)

# Backward compat
TmuxClient = TmuxProcessManager
TmuxPane = ManagedProcess
logger = logging.getLogger(__name__)

# Optional LLM-based status analysis
try:
    from agenttalk.agent_status_analyzer import AgentStatusAnalyzer, AgentActivityState
    _llm_available = True
except ImportError:
    _llm_available = False


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


BENIGN_ERROR_PATTERNS = [
    "auto-update failed",
    "run /review",
]

ERROR_PATTERNS = {
    "traceback": re.compile(r"\btraceback \(most recent call last\)|\btraceback:", re.IGNORECASE),
    "error": re.compile(r"^\s*(?:[-*•✗]\s*)?(?:error|api error|provider error|llm error)\b[:\s-]", re.IGNORECASE),
    "failed": re.compile(r"^\s*(?:[-*•✗]\s*)?(?:failed|fatal|panic)\b[:\s-]", re.IGNORECASE),
    "command_error": re.compile(r"^\s*(?:npm|pip|cargo)\s+err\b", re.IGNORECASE),
    "network_error": re.compile(
        r"\b(connection refused|connection error|econnrefused|enotfound|etimedout|"
        r"unable to connect|network is unreachable|dns error|ssl error|tls error|certificate error)\b",
        re.IGNORECASE,
    ),
    "provider_error": re.compile(
        r"\b(rate limit|rate-limit|too many requests|quota exceeded|quota limit|"
        r"anthropic error|openai error|google api error|gemini error|max retries exceeded)\b",
        re.IGNORECASE,
    ),
    "http_error": re.compile(
        r"\b(401|403|429|500|502|503|504|unauthorized|forbidden|"
        r"internal server error|bad gateway|gateway timeout|service unavailable)\b",
        re.IGNORECASE,
    ),
    "process_error": re.compile(r"\b(out of memory|oom|keyboardinterrupt|killed)\b", re.IGNORECASE),
}

# Patterns indicating the agent is paused waiting for LLM/network
PAUSE_PATTERNS = [
    "waiting for response",
    "generating response",
    "thinking...",
    "request timed out",
    "connection reset",
    "stream ended",
    "llm error",
    "provider error",
    "model error",
    "api timeout",
    "network error",
    "retrying",
    "rate limited",
    "service temporarily unavailable",
    "model is overloaded",
    "context length exceeded",
    "token limit",
    "max tokens",
]


def detect_errors(output: str) -> list[str]:
    found: set[str] = set()
    for line in output.splitlines()[-30:]:
        normalized = line.strip().lower()
        if not normalized:
            continue
        if any(pattern in normalized for pattern in BENIGN_ERROR_PATTERNS):
            continue
        for name, pattern in ERROR_PATTERNS.items():
            if pattern.search(line):
                found.add(name)
    return sorted(found)


def detect_pause(output: str) -> list[str]:
    """Detect LLM/provider pause patterns in terminal output."""
    output_lower = output.lower()
    found: list[str] = []
    for pattern in PAUSE_PATTERNS:
        if pattern in output_lower:
            found.append(pattern)
    return list(set(found))


def output_fingerprint(output: str) -> str:
    return hashlib.sha256(output.encode()).hexdigest()[:16]


class AgentTalkRelay:
    def __init__(self, config: AgentTalkConfig, *, hub_client: HubClient, tmux_client: ProcessManager) -> None:
        self.config = config
        self.hub_client = hub_client
        self.tmux_client = tmux_client
        self.watch_states: dict[str, WatchState] = {}
        self.health_states: dict[str, AgentHealthState] = {}
        # Initialize LLM analyzer if available and enabled in config
        self._llm_analyzer = None
        if _llm_available and config.llm.enabled:
            try:
                self._llm_analyzer = AgentStatusAnalyzer(
                    api_key=config.llm.api_key or None,
                    model=config.llm.model,
                    base_url=config.llm.base_url or None,
                )
            except Exception:
                pass  # LLM analysis disabled if configuration fails

    def sync_once(self) -> RelaySyncResult:
        self.hub_client.register_relay(self.config)
        panes = self.tmux_client.list_processes()
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
            self.hub_client.upsert_agent(self.config, binding, health.status)
            self.hub_client.report_health(health)
        return RelaySyncResult(upserted=len(self.config.agents), online=online, offline=offline)

    def _check_agent_health(self, binding, pane: ManagedProcess) -> AgentHealthReport:
        state = self.health_states.get(binding.short_id)
        if state is None:
            state = AgentHealthState(short_id=binding.short_id)
            self.health_states[binding.short_id] = state

        pane_alive = True
        process_alive = True
        recent_output = ""
        detected_errors: list[str] = []
        current_fingerprint = ""
        llm_state_description = ""
        llm_confidence = 0.0

        detected_pauses: list[str] = []
        try:
            # Capture last 30 lines for LLM analysis (reduced from 50 to save tokens)
            recent_output = self.tmux_client.capture_output(binding.tmux_target, lines=30)
            current_fingerprint = output_fingerprint(recent_output)
            detected_errors = detect_errors(recent_output)
            detected_pauses = detect_pause(recent_output)
        except Exception:
            pane_alive = False

        if pane_alive and pane.pane_pid is not None:
            process_alive = is_process_alive(pane.pane_pid)

        # Determine base status
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

        # Use LLM for semantic state analysis (if available)
        if _llm_available and self._llm_analyzer and pane_alive and process_alive:
            try:
                analysis = self._llm_analyzer.analyze(binding.short_id, recent_output)
                llm_state_description = analysis.description
                llm_confidence = analysis.confidence
                
                # Override status based on LLM analysis with confidence threshold
                if analysis.confidence > 0.7:
                    llm_status_map = {
                        AgentActivityState.IDLE: AgentStatus.IDLE,
                        AgentActivityState.WORKING: AgentStatus.WORKING,
                        AgentActivityState.THINKING: AgentStatus.WORKING,
                        AgentActivityState.ERROR: AgentStatus.ERROR,
                        AgentActivityState.CRASHED: AgentStatus.CRASHED,
                        AgentActivityState.STUCK: AgentStatus.STALE,
                        AgentActivityState.COMPLETED: AgentStatus.IDLE,
                    }
                    mapped_status = llm_status_map.get(analysis.state)
                    if mapped_status:
                        status = mapped_status
                        if status == AgentStatus.ERROR:
                            state.consecutive_errors += 1
                        else:
                            state.consecutive_errors = max(0, state.consecutive_errors - 1)
            except Exception:
                pass  # LLM analysis failed, use base status

        state.last_output_fingerprint = current_fingerprint
        state.last_status = status

        # Build enhanced description
        description = f"Status: {status.value}"
        if llm_state_description:
            description += f" | LLM: {llm_state_description} ({llm_confidence:.0%})"
        if detected_errors:
            description += f" | Errors: {', '.join(detected_errors[:3])}"

        return AgentHealthReport(
            short_id=binding.short_id,
            pane_alive=pane_alive,
            process_alive=process_alive,
            recent_output=recent_output[-500:] if recent_output else "",
            output_fingerprint=current_fingerprint,
            detected_errors=detected_errors,
            detected_pauses=detected_pauses,
            status=status,
        )

    def run_once(self, *, context_counter: int = 0) -> int:
        self.sync_once()
        self.process_next_message_once()
        self.update_watches_once()
        # Sync context every 6 intervals (~30s at the default interval).
        context_counter += 1
        if context_counter >= 6:
            self.sync_context_once()
            context_counter = 0
        self.hub_client.heartbeat(self.config.machine_id)
        return context_counter

    def run_forever(
        self,
        *,
        interval_seconds: float = 5.0,
        max_iterations: int | None = None,
    ) -> None:
        context_counter = 0
        iterations = 0
        while max_iterations is None or iterations < max_iterations:
            try:
                context_counter = self.run_once(context_counter=context_counter)
            except Exception:
                logger.exception("AgentTalk relay loop failed; retrying")
            iterations += 1
            if max_iterations is not None and iterations >= max_iterations:
                break
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
            baseline = self.tmux_client.capture_output(binding.tmux_target, lines=500)
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
            output = self.tmux_client.capture_output(state.target, lines=800)
            delta = output_delta(state.baseline, output)
            if not delta:
                continue
            response_delta = strip_injected_message_echo(delta, state.done_marker)
            done = state.done_marker in response_delta
            response_text = response_delta.replace(state.done_marker, "").rstrip()
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
                context = self.tmux_client.capture_output(binding.tmux_target, lines=lines)
            except Exception:
                continue
            self.hub_client.update_agent_context(binding.short_id, context)
            count += 1
        return count


class StaticTmuxClient(TmuxProcessManager):
    def __init__(self, panes: list[ManagedProcess]) -> None:
        self._panes = panes
        self.captures: dict[str, str] = {}

    def list_processes(self) -> list[ManagedProcess]:
        return self._panes

    def capture_output(self, target: str, *, lines: int = 300) -> str:
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


def strip_injected_message_echo(delta: str, done_marker: str) -> str:
    """Remove the terminal echo of the injected AgentTalk prompt.

    tmux-hosted CLIs often echo pasted/submitted input into the pane. The injected
    task includes the done marker as an instruction, so the watcher must ignore
    the first marker when it belongs to the echoed prompt and only complete after
    the peer prints the marker in its own response.
    """
    prompt_start = delta.find("[AgentTalk Message]")
    if prompt_start < 0:
        return delta
    marker_index = delta.find(done_marker, prompt_start)
    if marker_index < 0:
        return delta
    return delta[marker_index + len(done_marker) :].lstrip()
