from __future__ import annotations

import httpx

from agenttalk.config import AgentBinding, AgentTalkConfig
from agenttalk.hub.models import AgentHealthReport, AgentStatus, MessageStatus


STATUS_COMPAT_FALLBACKS = {
    MessageStatus.SUBMITTED: MessageStatus.INJECTED,
    MessageStatus.ACKED: MessageStatus.WORKING,
    MessageStatus.SUBMIT_UNCONFIRMED: MessageStatus.INJECTED,
}


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

    def report_health(self, report: AgentHealthReport) -> None:
        response = httpx.post(
            f"{self.hub_url}/api/agents/{report.short_id}/health",
            headers=self.headers,
            json=report.model_dump(),
            timeout=10,
        )
        response.raise_for_status()

    def next_message(self, machine_id: str) -> dict | None:
        response = httpx.get(
            f"{self.hub_url}/api/relays/{machine_id}/messages/next",
            headers=self.headers,
            timeout=10,
        )
        response.raise_for_status()
        return response.json()["message"]

    def update_message_status(self, message_id: str, status: MessageStatus, error: str = "") -> None:
        response = httpx.post(
            f"{self.hub_url}/api/messages/{message_id}/status",
            headers=self.headers,
            json={"status": status.value, "error": error},
            timeout=10,
        )
        if response.status_code == 422 and status in STATUS_COMPAT_FALLBACKS:
            fallback = STATUS_COMPAT_FALLBACKS[status]
            compat_error = error or f"compat fallback from {status.value}"
            response = httpx.post(
                f"{self.hub_url}/api/messages/{message_id}/status",
                headers=self.headers,
                json={"status": fallback.value, "error": compat_error},
                timeout=10,
            )
        response.raise_for_status()

    def update_message_response(self, message_id: str, response_text: str, *, completed: bool) -> None:
        response = httpx.post(
            f"{self.hub_url}/api/messages/{message_id}/response",
            headers=self.headers,
            json={"response_text": response_text, "completed": completed},
            timeout=10,
        )
        response.raise_for_status()

    def get_message(self, message_id: str) -> dict:
        response = httpx.get(
            f"{self.hub_url}/api/messages/{message_id}",
            headers=self.headers,
            timeout=10,
        )
        response.raise_for_status()
        return response.json()

    def get_message_response(self, message_id: str) -> dict:
        response = httpx.get(
            f"{self.hub_url}/api/messages/{message_id}/response",
            headers=self.headers,
            timeout=10,
        )
        response.raise_for_status()
        return response.json()

    def update_agent_context(self, short_id: str, context: str) -> None:
        response = httpx.post(
            f"{self.hub_url}/api/agents/{short_id}/context",
            headers=self.headers,
            json={"context": context},
            timeout=10,
        )
        response.raise_for_status()

    def get_agent_context(self, short_id: str) -> dict:
        response = httpx.get(
            f"{self.hub_url}/api/agents/{short_id}/context",
            headers=self.headers,
            timeout=10,
        )
        response.raise_for_status()
        return response.json()
