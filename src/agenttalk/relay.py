from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from dataclasses import dataclass
from pathlib import Path

from agenttalk.config import AgentTalkConfig, default_config_path, load_config
from agenttalk.dlq import record_dead_letter
from agenttalk.http_client import HubRequestError
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

INLINE_INJECTION_MAX_CHARS = 1400
INLINE_INJECTION_MAX_LINES = 8

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

    def to_dict(self) -> dict[str, str]:
        return {
            "target": self.target,
            "baseline": self.baseline,
            "done_marker": self.done_marker,
        }

    @classmethod
    def from_dict(cls, payload: dict[str, str]) -> WatchState:
        return cls(
            target=str(payload["target"]),
            baseline=str(payload["baseline"]),
            done_marker=str(payload["done_marker"]),
        )


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
        r"\b(httpstatuserror|http error|client error|server error|"
        r"internal server error|bad gateway|gateway timeout|service unavailable)\b",
        re.IGNORECASE,
    ),
    "process_error": re.compile(
        r"^\s*(?:[-*•✗]\s*)?(?:killed|keyboardinterrupt)\b|\b(out of memory|oom|process killed)\b",
        re.IGNORECASE,
    ),
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
        if normalized.startswith("│"):
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


def tail_shows_live_agent_ui(output: str) -> bool:
    tail_lines = [line.strip() for line in output.splitlines()[-12:] if line.strip()]
    if not tail_lines:
        return False
    tail = "\n".join(tail_lines)
    live_markers = (
        "› ",
        "❯",
        "gpt-",
        "bypass permissions",
        "esc to interrupt",
        "Working (",
        "evidence-based-code-review",
    )
    return any(marker in tail for marker in live_markers)


def output_fingerprint(output: str) -> str:
    return hashlib.sha256(output.encode()).hexdigest()[:16]


class AgentTalkRelay:
    def __init__(
        self,
        config: AgentTalkConfig,
        *,
        hub_client: HubClient,
        tmux_client: ProcessManager,
        watch_state_path: Path | None = None,
    ) -> None:
        self.config = config
        self.hub_client = hub_client
        self.tmux_client = tmux_client
        self.watch_state_path = watch_state_path or default_watch_state_path()
        self.watch_states: dict[str, WatchState] = self._load_watch_states()
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

    def reload_config(self, config: AgentTalkConfig) -> None:
        previous_hub_url = getattr(self.hub_client, "hub_url", self.config.hub_url.rstrip("/"))
        previous_token = getattr(self.hub_client, "token", self.config.token)
        self.config = config
        if previous_hub_url != config.hub_url.rstrip("/") or previous_token != config.token:
            self.hub_client = HubClient(config.hub_url, config.token)

    def reload_config_from_disk(self, config_path: Path | None = None) -> None:
        self.reload_config(load_config(config_path))

    def _load_watch_states(self) -> dict[str, WatchState]:
        try:
            raw = json.loads(self.watch_state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        if not isinstance(raw, dict):
            return {}
        loaded: dict[str, WatchState] = {}
        for message_id, payload in raw.items():
            if not isinstance(payload, dict):
                continue
            try:
                loaded[str(message_id)] = WatchState.from_dict(payload)
            except (KeyError, TypeError, ValueError):
                continue
        return loaded

    def _save_watch_states(self) -> None:
        self.watch_state_path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            message_id: state.to_dict()
            for message_id, state in sorted(self.watch_states.items())
        }
        self.watch_state_path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")

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
        elif detected_errors and not tail_shows_live_agent_ui(recent_output):
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

    def run_once(self, *, context_counter: int = 0, config_path: Path | None = None) -> int:
        if config_path is not None:
            self.reload_config_from_disk(config_path)
        # Heartbeat first so transient failures in any sub-step below cannot keep
        # the relay's last_seen_at frozen for >heartbeat_ttl_seconds (which would
        # cause the Hub to derive every agent on this machine as OFFLINE even when
        # the panes are healthy and producing work).
        self._safe_heartbeat()
        for step in (self.sync_once, self.process_next_message_once, self.update_watches_once):
            try:
                step()
            except HubRequestError as exc:
                logger.warning("AgentTalk relay Hub request failed in %s: %s", step.__name__, exc)
            except Exception:
                logger.exception("AgentTalk relay step %s failed; continuing", step.__name__)
        # Sync context every 6 intervals (~30s at the default interval).
        context_counter += 1
        if context_counter >= 6:
            try:
                self.sync_context_once()
            except Exception:
                logger.exception("AgentTalk relay sync_context_once failed; continuing")
            context_counter = 0
        # Belt-and-braces: best-effort heartbeat at end too. If sync_once succeeded
        # it already re-registered the relay, so this refresh is cheap and gives
        # the most accurate last_seen_at.
        self._safe_heartbeat()
        return context_counter

    def _safe_heartbeat(self) -> None:
        try:
            self.hub_client.heartbeat(self.config.machine_id)
        except HubRequestError as exc:
            logger.warning("AgentTalk relay heartbeat Hub request failed; will retry next tick: %s", exc)
        except Exception:
            logger.exception("AgentTalk relay heartbeat failed; will retry next tick")

    def run_forever(
        self,
        *,
        interval_seconds: float = 5.0,
        max_iterations: int | None = None,
        config_path: Path | None = None,
    ) -> None:
        context_counter = 0
        iterations = 0
        while max_iterations is None or iterations < max_iterations:
            try:
                context_counter = self.run_once(context_counter=context_counter, config_path=config_path)
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
        payload = prepare_injected_message(
            message_id=message["message_id"],
            sender=message["sender"],
            target=message["target"],
            body=message["body"],
            done_marker=message["done_marker"],
        )
        submit = binding.receive_mode == ReceiveMode.AUTO_SUBMIT
        try:
            baseline = self.tmux_client.capture_output(binding.tmux_target, lines=500)
            injection_result = self.tmux_client.inject_text(
                binding.tmux_target,
                payload,
                submit=submit,
            )
        except Exception as exc:
            self.hub_client.update_message_status(message["message_id"], MessageStatus.FAILED, str(exc))
            record_dead_letter(message=message, reason="inject_failed", error=str(exc))
            return True
        # Distinguish "fully delivered" (Enter pressed, agent has the message)
        # from "pasted but not submitted" (text sits in the input box, agent has
        # not seen it yet). Callers must NOT treat INJECTED_PASTE_ONLY as a
        # confirmed delivery; they should verify via context or follow up.
        if not submit:
            injected_status = MessageStatus.INJECTED_PASTE_ONLY
        elif injection_result is not None and injection_result.submit_confirmed:
            injected_status = MessageStatus.SUBMITTED
        elif injection_result is not None and injection_result.pending_input_detected:
            injected_status = MessageStatus.SUBMIT_UNCONFIRMED
            record_dead_letter(
                message=message,
                reason="submit_unconfirmed",
                error=f"submit attempts: {injection_result.attempts}",
            )
        else:
            injected_status = MessageStatus.INJECTED
        self.watch_states[message["message_id"]] = WatchState(
            target=binding.tmux_target,
            baseline=baseline,
            done_marker=message["done_marker"],
        )
        self._save_watch_states()
        self.hub_client.update_message_status(message["message_id"], injected_status)
        return True

    def update_watches_once(self) -> int:
        completed: list[str] = []
        updates = 0
        for message_id, state in list(self.watch_states.items()):
            try:
                current_message = self.hub_client.get_message(message_id)
            except Exception:
                current_message = None
            if current_message and current_message.get("status") in {
                MessageStatus.COMPLETED.value,
                MessageStatus.FAILED.value,
                MessageStatus.TIMEOUT.value,
            }:
                completed.append(message_id)
                continue
            output = self.tmux_client.capture_output(state.target, lines=800)
            delta = output_delta(state.baseline, output)
            if not delta:
                continue
            response_delta = strip_injected_message_echo(delta, state.done_marker)
            acked, response_delta = strip_agenttalk_ack(response_delta, message_id)
            # Stricter completion check: the marker must appear on its own line
            # (allowing leading/trailing whitespace) AND there must be non-empty
            # response content before the marker. This rejects two failure
            # modes that used to slip through `marker in response_delta`:
            #   1. The marker as a mid-line substring of unrelated output.
            #   2. An "echo-only" completion where the terminal scrolled the
            #      injected prompt into the visible buffer twice but the agent
            #      never actually replied.
            done, response_text = _evaluate_done_marker(response_delta, state.done_marker)
            self.hub_client.update_message_response(message_id, response_text, completed=done)
            if done:
                completed.append(message_id)
            elif acked:
                self.hub_client.update_message_status(message_id, MessageStatus.ACKED)
            else:
                self.hub_client.update_message_status(message_id, MessageStatus.WORKING)
            updates += 1
        for message_id in completed:
            self.watch_states.pop(message_id, None)
        if completed:
            self._save_watch_states()
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


def default_message_spool_dir() -> Path:
    return Path.home() / ".agenttalk" / "inbox"


def default_watch_state_path() -> Path:
    configured = os.environ.get("AGENTTALK_WATCH_STATE_PATH", "").strip()
    if configured:
        return Path(configured)
    return default_config_path().parent / "watch_states.json"


def _safe_spool_filename(message_id: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", message_id).strip("._")
    return f"{safe or 'message'}.md"


def _collapse_for_inline(text: str, *, limit: int = 900) -> str:
    collapsed = " ".join(text.strip().split())
    if len(collapsed) <= limit:
        return collapsed
    return collapsed[: limit - 3].rstrip() + "..."


def _should_spool_message(body: str) -> bool:
    return (
        len(body) > INLINE_INJECTION_MAX_CHARS
        or len(body.splitlines()) > INLINE_INJECTION_MAX_LINES
    )


def prepare_injected_message(
    *,
    message_id: str,
    sender: str,
    target: str,
    body: str,
    done_marker: str,
    spool_dir: Path | None = None,
) -> str:
    """Build the tmux payload.

    Long, highly multiline prompts are fragile in Codex/Claude TUIs: the paste
    can remain in the editor and submit keys may turn into extra blank lines.
    Keep the terminal injection compact and spill the full task to a local file
    when needed. The Hub still stores the full message body.
    """

    if not _should_spool_message(body):
        task = _collapse_for_inline(body)
        return (
            f"[AgentTalk Message] message_id: {message_id} from: {sender} to: {target}. "
            f"Task: {task} "
            "First print this exact acknowledgement on its own line: "
            f"AGENTTALK_ACK:{message_id}. "
            "When done, print this exact marker on its own line: "
            f"{done_marker}"
        )

    resolved_spool_dir = spool_dir or default_message_spool_dir()
    resolved_spool_dir.mkdir(parents=True, exist_ok=True)
    spool_path = resolved_spool_dir / _safe_spool_filename(message_id)
    full_message = build_injected_message(
        message_id=message_id,
        sender=sender,
        target=target,
        body=body,
        done_marker=done_marker,
    )
    spool_path.write_text(full_message, encoding="utf-8")
    digest = hashlib.sha256(full_message.encode("utf-8")).hexdigest()[:16]
    preview = _collapse_for_inline(body, limit=240)
    return (
        f"[AgentTalk Message] message_id: {message_id} from: {sender} to: {target}. "
        f"Full task is stored at {spool_path} (sha256:{digest}). "
        "Read that file first, then perform the task. "
        f"Preview: {preview} "
        "First print this exact acknowledgement on its own line: "
        f"AGENTTALK_ACK:{message_id}. "
        "When done, print this exact marker on its own line: "
        f"{done_marker}"
    )


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
            "First print this exact acknowledgement on its own line:",
            f"AGENTTALK_ACK:{message_id}",
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


def strip_agenttalk_ack(response_delta: str, message_id: str) -> tuple[bool, str]:
    ack_line = f"AGENTTALK_ACK:{message_id}"
    acked = False
    kept_lines: list[str] = []
    for line in response_delta.splitlines():
        if line.strip() == ack_line:
            acked = True
            continue
        kept_lines.append(line)
    return acked, "\n".join(kept_lines).lstrip()


def _evaluate_done_marker(response_delta: str, done_marker: str) -> tuple[bool, str]:
    """Decide whether ``response_delta`` proves the peer printed the done marker.

    Returns ``(done, response_text)``. ``done`` is True only when:

    * The marker appears on its own line (whitespace before and after, and the
      rest of the line is empty), so a stray substring in arbitrary output
      cannot fake a completion.
    * There is at least one line of non-empty, non-marker response text BEFORE
      that marker line. The injected prompt is supposed to be stripped already;
      requiring a real reply before the marker rejects "echo-only" completions
      where the terminal scrolled the prompt into view twice but the peer never
      actually answered.

    ``response_text`` is the trimmed response with all marker lines removed.
    """
    if not done_marker:
        return False, response_delta.rstrip()
    # Locate marker lines: lines whose non-whitespace content is exactly the marker.
    lines = response_delta.splitlines()
    marker_line_indices: list[int] = []
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped == done_marker:
            marker_line_indices.append(index)
    response_lines_no_marker = [line for line in lines if line.strip() != done_marker]
    response_text = "\n".join(response_lines_no_marker).rstrip()
    if not marker_line_indices:
        return False, response_text
    # Require at least one non-empty response line BEFORE the first marker line.
    first_marker = marker_line_indices[0]
    has_real_content_before = any(
        line.strip() and line.strip() != done_marker
        for line in lines[:first_marker]
    )
    if not has_real_content_before:
        return False, response_text
    return True, response_text
