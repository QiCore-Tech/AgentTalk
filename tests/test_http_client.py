from __future__ import annotations

import httpx

from agenttalk import http_client


class FakeResponse:
    def __init__(self, status_code: int = 200) -> None:
        self.status_code = status_code


def test_request_retries_connect_errors(monkeypatch) -> None:
    calls: list[str] = []

    def fake_request(method, url, **_kwargs):
        calls.append(url)
        if len(calls) < 3:
            raise httpx.ConnectError("tls eof")
        return FakeResponse()

    monkeypatch.setattr(http_client.httpx, "request", fake_request)
    monkeypatch.setattr(http_client.time, "sleep", lambda _seconds: None)

    response = http_client.request("GET", "https://hub.local/health")

    assert response.status_code == 200
    assert calls == ["https://hub.local/health"] * 3


def test_request_raises_readable_connection_error_after_retries(monkeypatch) -> None:
    def fake_request(*_args, **_kwargs):
        raise httpx.ConnectError("tls eof")

    monkeypatch.setattr(http_client.httpx, "request", fake_request)
    monkeypatch.setattr(http_client.time, "sleep", lambda _seconds: None)

    try:
        http_client.request("POST", "https://hub.local/api/messages", attempts=2)
    except http_client.HubConnectionError as exc:
        assert exc.method == "POST"
        assert exc.attempts == 2
        assert "tls eof" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected HubConnectionError")


def test_request_does_not_retry_read_errors(monkeypatch) -> None:
    calls = 0

    def fake_request(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        raise httpx.ReadError("response closed")

    monkeypatch.setattr(http_client.httpx, "request", fake_request)

    try:
        http_client.request("POST", "https://hub.local/api/messages", attempts=3)
    except http_client.HubConnectionError as exc:
        assert exc.attempts == 1
        assert "response closed" in str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected HubConnectionError")
    assert calls == 1


def test_request_retries_default_safe_method_5xx(monkeypatch) -> None:
    calls = 0

    def fake_request(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return FakeResponse(200 if calls == 3 else 502)

    monkeypatch.setattr(http_client.httpx, "request", fake_request)
    monkeypatch.setattr(http_client.time, "sleep", lambda _seconds: None)

    response = http_client.request("GET", "https://hub.local/api/agents")

    assert response.status_code == 200
    assert calls == 3


def test_request_does_not_retry_post_5xx_by_default(monkeypatch) -> None:
    calls = 0

    def fake_request(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return FakeResponse(502)

    monkeypatch.setattr(http_client.httpx, "request", fake_request)

    response = http_client.request("POST", "https://hub.local/api/messages")

    assert response.status_code == 502
    assert calls == 1


def test_request_retries_post_5xx_when_explicitly_safe(monkeypatch) -> None:
    calls = 0

    def fake_request(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return FakeResponse(200 if calls == 2 else 502)

    monkeypatch.setattr(http_client.httpx, "request", fake_request)
    monkeypatch.setattr(http_client.time, "sleep", lambda _seconds: None)

    response = http_client.request(
        "POST",
        "https://hub.local/api/relays/heartbeat",
        retry_statuses={502, 503, 504},
    )

    assert response.status_code == 200
    assert calls == 2
