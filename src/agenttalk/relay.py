from __future__ import annotations

import time
from dataclasses import dataclass

from agenttalk.config import AgentTalkConfig
from agenttalk.hub.client import HubClient
from agenttalk.hub.models import AgentStatus, MessageStatus, ReceiveMode
from agenttalk.tmux import TmuxClient, TmuxPane


@dataclass(frozen=True)
class RelaySyncResult:
    upserted: int
    online: int
    offline: int


class AgentTalkRelay:
    def __init__(self, config: AgentTalkConfig, *, hub_client: HubClient, tmux_client: TmuxClient) -> None:
        self.config = config
        self.hub_client = hub_client
        self.tmux_client = tmux_client

    def sync_once(self) -> RelaySyncResult:
        self.hub_client.register_relay(self.config)
        panes = self.tmux_client.list_panes()
        pane_targets = {pane.target for pane in panes}
        pane_ids = {pane.pane_id for pane in panes}
        online = 0
        offline = 0
        for binding in self.config.agents:
            status = binding_status(binding.tmux_target, binding.pane_id, pane_targets, pane_ids)
            if status == AgentStatus.ONLINE:
                online += 1
            else:
                offline += 1
            self.hub_client.upsert_agent(self.config, binding, status)
        return RelaySyncResult(upserted=len(self.config.agents), online=online, offline=offline)

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
            self.tmux_client.inject_text(
                binding.tmux_target,
                payload,
                submit=binding.receive_mode == ReceiveMode.AUTO_SUBMIT,
            )
        except Exception as exc:
            self.hub_client.update_message_status(message["message_id"], MessageStatus.FAILED, str(exc))
            return True
        self.hub_client.update_message_status(message["message_id"], MessageStatus.INJECTED)
        return True


def binding_status(
    tmux_target: str,
    pane_id: str,
    pane_targets: set[str],
    pane_ids: set[str],
) -> AgentStatus:
    if tmux_target in pane_targets:
        return AgentStatus.ONLINE
    if pane_id and pane_id in pane_ids:
        return AgentStatus.ONLINE
    return AgentStatus.OFFLINE


class StaticTmuxClient(TmuxClient):
    def __init__(self, panes: list[TmuxPane]) -> None:
        self._panes = panes

    def list_panes(self) -> list[TmuxPane]:
        return self._panes


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
