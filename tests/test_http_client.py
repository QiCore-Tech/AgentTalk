from __future__ import annotations

import httpx

from agenttalk import http_client


class FakeResponse:
    status_code = 200


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
