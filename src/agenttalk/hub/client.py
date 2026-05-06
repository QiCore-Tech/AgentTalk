from __future__ import annotations

import httpx

from agenttalk.config import AgentBinding, AgentTalkConfig
from agenttalk.hub.models import AgentStatus


class HubClient:
    def __init__(self, hub_url: str, token: str) -> None:
        self.hub_url = hub_url.rstrip("/")
        self.token = token

    @property
    def headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}

    def register_relay(self, config: AgentTalkConfig) -> None:
        response = httpx.post(
            f"{self.hub_url}/api/relays/register",
            headers=self.headers,
            json={
                "machine_id": config.machine_id,
                "host_name": config.host_name,
                "user_name": config.user_name,
            },
            timeout=10,
        )
        response.raise_for_status()

    def heartbeat(self, machine_id: str) -> None:
        response = httpx.post(
            f"{self.hub_url}/api/relays/heartbeat",
            headers=self.headers,
            json={"machine_id": machine_id},
            timeout=10,
        )
        response.raise_for_status()

    def upsert_agent(self, config: AgentTalkConfig, binding: AgentBinding, status: AgentStatus) -> None:
        response = httpx.put(
            f"{self.hub_url}/api/agents",
            headers=self.headers,
            json={
                "short_id": binding.short_id,
                "machine_id": config.machine_id,
                "owner": binding.owner,
                "kind": binding.kind,
                "workspace": binding.workspace,
                "tmux_target": binding.tmux_target,
                "receive_mode": binding.receive_mode.value,
                "status": status.value,
            },
            timeout=10,
        )
        response.raise_for_status()
