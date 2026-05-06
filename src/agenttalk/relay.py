from __future__ import annotations

import time
from dataclasses import dataclass

from agenttalk.config import AgentTalkConfig
from agenttalk.hub.client import HubClient
from agenttalk.hub.models import AgentStatus
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
            self.hub_client.heartbeat(self.config.machine_id)
            time.sleep(interval_seconds)


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
