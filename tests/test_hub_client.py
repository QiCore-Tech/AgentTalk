from __future__ import annotations

from agenttalk.hub.client import HubClient
from agenttalk.hub.models import MessageStatus


class FakeResponse:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"status {self.status_code}")


def test_update_message_status_falls_back_for_old_hub_enum(monkeypatch) -> None:
    calls: list[dict] = []

    def fake_request(method, _url, **kwargs) -> FakeResponse:
        assert method == "POST"
        calls.append(kwargs["json"])
        if len(calls) == 1:
            return FakeResponse(422)
        return FakeResponse(200)

    import agenttalk.hub.client as client_module

    monkeypatch.setattr(client_module, "request", fake_request)

    HubClient("http://hub.local", "token").update_message_status(
        "msg-1",
        MessageStatus.SUBMITTED,
    )

    assert calls == [
        {"status": "submitted", "error": ""},
        {"status": "injected", "error": "compat fallback from submitted"},
    ]


def test_create_alert_posts_to_hub(monkeypatch) -> None:
    calls: list[dict] = []

    class AlertResponse(FakeResponse):
        def json(self) -> dict:
            return {"feishu_status": "sent"}

    def fake_request(method, url, **kwargs) -> AlertResponse:
        calls.append({"method": method, "url": url, "json": kwargs["json"]})
        return AlertResponse(200)

    import agenttalk.hub.client as client_module

    monkeypatch.setattr(client_module, "request", fake_request)

    result = HubClient("http://hub.local", "token").create_alert(
        source="alice-codex-api",
        alert_type="warning",
        message="Need human review.",
    )

    assert result == {"feishu_status": "sent"}
    assert calls == [
        {
            "method": "POST",
            "url": "http://hub.local/api/alerts",
            "json": {
                "source": "alice-codex-api",
                "alert_type": "warning",
                "message": "Need human review.",
            },
        }
    ]
